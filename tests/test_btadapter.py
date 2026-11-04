"""Tests for the USB Bluetooth adapter: which adapter is used, the Pi's own powered off while a USB one is there and
on again when it's gone, bluetoothctl aimed at the one in use, and what the screen says.

  python tests/test_btadapter.py     (no Pi, BlueZ or adapter: sysfs and busctl are stood in for)
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-btadapter-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"))
(TMP / "run").mkdir()

import bridge  # noqa: E402
import btadapter  # noqa: E402

OWN, DONGLE = "B8:27:EB:00:00:01", "00:1A:7D:DA:71:13"
DEVICES = {"hci0": "/sys/devices/platform/soc/20201000.serial/serial0/serial0-0/bluetooth/hci0",
           "hci1": "/sys/devices/platform/soc/20980000.usb/usb1/1-1/1-1:1.0/bluetooth/hci1"}


def resolve(path):
    return DEVICES[Path(path).parent.name]


def test_adapters():
    """links (hci0:11) aren't adapters; a USB one is told by its sysfs path; the USB one is chosen"""
    found = btadapter.adapters("/sys/class/bluetooth", resolve, lambda root: ["hci1", "hci0", "hci0:11"])
    assert found == [("hci0", False), ("hci1", True)], found
    assert btadapter.choose(found) == ("hci1", True)
    assert btadapter.choose([("hci0", False)]) == ("hci0", False)
    assert btadapter.choose([]) is None
    assert btadapter.adapters(TMP / "none") == []


def test_busctl():
    calls = []

    def run(cmd):
        calls.append(cmd)
        return (0, f's "{DONGLE}"\n') if "get-property" in cmd else (1, "Blocked") if "true" in cmd else (0, "")

    assert btadapter.address("hci1", run) == DONGLE
    assert calls[0][:4] == ["busctl", "get-property", "org.bluez", "/org/bluez/hci1"]
    assert btadapter.set_powered("hci0", False, run) and not btadapter.set_powered("hci1", True, run)
    assert calls[-1][-2:] == ["b", "true"]
    assert btadapter.address("hci9", lambda cmd: (1, "Unknown object")) is None


def test_aim():
    """with an adapter chosen, bridge.bt goes to it over D-Bus (btadapter.Bluetoothctl); with none, bluetoothctl"""
    btadapter.aim(DONGLE)
    assert btadapter.selected() == DONGLE
    assert btadapter.SELECT.read_text() == f"select {DONGLE}\n"
    seen, ran = [], []
    old_run, old_ctl = bridge.run, btadapter.Bluetoothctl

    class Ctl:
        def __init__(self, addr):
            seen.append(addr)
            self.bus = self

        def run(self, args, timeout):
            seen.append(list(args))
            return 0, "Connection successful"

        def close(self):
            seen.append("closed")

    bridge.run = lambda cmd, timeout: (ran.append(cmd), (0, ""))[1]
    btadapter.Bluetoothctl = Ctl
    try:
        assert bridge.bt("connect", OWN) == (0, "Connection successful")
        btadapter.aim(None)
        bridge.bt("info", OWN)
    finally:
        bridge.run, btadapter.Bluetoothctl = old_run, old_ctl
    assert seen == [DONGLE, ["connect", OWN], "closed"], seen
    assert ran == [["bluetoothctl", "info", OWN]]
    assert btadapter.selected() is None
    btadapter.aim(None)                       # (no file: fine)


def test_info_text():
    """a Device1's properties read back as bluetoothctl's info: a speaker, paired"""
    text = btadapter.info_text(OWN, {"Name": "JBL Go 3", "Alias": "JBL Go 3", "Icon": "audio-card", "Paired": True,
                                     "Bonded": True, "Trusted": False, "Connected": False,
                                     "UUIDs": ["0000110b-0000-1000-8000-00805f9b34fb"]})
    info = bridge.parse_info(OWN, text)
    assert info["paired"] == "yes" and info["trusted"] == "no" and "Bonded: yes" in text
    assert bridge.is_audio(info) and info["name"] == "JBL Go 3"


def test_speaker_scan_lists_only_heard():
    """the speaker scan lists what was heard during it ([NEW], or a fresh RSSI), not every device BlueZ remembers:
    a paired JBL that's off was listed while the speaker being paired wasn't to be seen (the Studio, 2026-11-03)"""
    scan = ("Discovery started\n[CHG] Controller B8:27:EB:15:77:0A Discovering: yes\n"
            "[CHG] Device 7C:64:56:3F:84:6B RSSI: 0xffffffbf (-65)\n"
            "[CHG] Device 20:18:5B:EF:AA:B0 Connected: no\n"
            "[NEW] Device 11:FF:27:5A:21:89 AG-04\n")
    known = {"20:18:5B:EF:AA:B0": "JBL Go 3", "11:FF:27:5A:21:89": "AG-04", "7C:64:56:3F:84:6B": "[TV] Samsung"}

    def bt(*args, timeout=15):
        if "scan" in args:
            return 0, scan
        if args[0] == "devices":
            return 0, "".join(f"Device {mac} {name}\n" for mac, name in known.items())
        return 0, f"\tName: {known[args[1]]}\n\tIcon: audio-card\n\tPaired: no"

    old = bridge.bt
    bridge.bt = bt
    try:
        assert bridge.scan_seen(scan) == {"7C:64:56:3F:84:6B", "11:FF:27:5A:21:89"}
        assert [d["name"] for d in bridge.bt_scan(1)] == ["[TV] Samsung", "AG-04"]
    finally:
        bridge.bt = old


def test_pairing_removes_and_scans_only_when_needed():
    """pairing a speaker: removed first only if it's paired already (a stale pairing), scanned for only if BlueZ
    doesn't know it (an AG-04 that advertises now and then was removed, missed by the scan, "Not found" each time)"""
    mac = "11:FF:27:5A:21:89"
    state = {"info": "\tName: AG-04\n\tPaired: no"}
    calls = []

    def bt(*args, timeout=15):
        calls.append(["scan"] if args[0] == "--timeout" else list(args[:2]))
        if args[0] == "info":
            return 0, state["info"]
        if args[0] == "remove":
            state["info"] = f"Device {mac} not available"
        if "pair" in args:
            return 0, "Pairing successful"
        return 0, "Connection successful" if "connect" in args else ""

    old = bridge.bt
    bridge.bt = bt
    try:
        assert bridge.bt_pair(mac)[0]
        assert ["remove", mac] not in calls and ["scan"] not in calls       # known, not paired: at once
        calls.clear()
        state["info"] = f"Device {mac} not available"                       # forgotten since the scan
        bridge.bt_pair(mac)
        assert ["scan"] in calls and ["remove", mac] not in calls
        calls.clear()
        state["info"] = "\tName: AG-04\n\tPaired: yes"                      # stale: removed, seen again
        bridge.bt_pair(mac)
        assert calls.index(["remove", mac]) < calls.index(["scan"])
    finally:
        bridge.bt = old


def test_dbus_scan_says_what_it_heard():
    """on a USB adapter the scan goes through D-Bus: it prints the devices heard (an RSSI) as bluetoothctl would,
    so bt_scan's heard-only list works there too; a paired speaker that's off (no RSSI) and the Pi's own aren't"""
    class DBusException(Exception):
        pass

    fake = type(sys)("dbus")
    fake.DBusException, fake.ObjectPath, fake.Boolean = DBusException, str, bool
    hci1, called = "/org/bluez/hci1", []

    class Ctl(btadapter.Bluetoothctl):
        def objects(self):
            return {hci1: {self.ADAPTER: {"Address": DONGLE}},
                    hci1 + "/dev_11_FF_27_5A_21_89": {self.DEVICE: {"Address": "11:FF:27:5A:21:89", "RSSI": -60}},
                    hci1 + "/dev_20_18_5B_EF_AA_B0": {self.DEVICE: {"Address": "20:18:5B:EF:AA:B0"}},
                    "/org/bluez/hci0/dev_7C_64_56_3F_84_6B": {self.DEVICE: {"Address": "7C:64:56:3F:84:6B",
                                                                            "RSSI": -65}}}

        def call(self, path, iface, method, *args, timeout=25):
            called.append(method)

    old = sys.modules.get("dbus")
    sys.modules["dbus"] = fake
    try:
        code, out = Ctl(DONGLE, bus=object()).run(["--timeout", "0.01", "scan", "on"])
    finally:
        sys.modules.pop("dbus")
        if old:
            sys.modules["dbus"] = old
    assert code == 0 and called == ["StartDiscovery", "StopDiscovery"], called
    assert bridge.scan_seen(out) == {"11:FF:27:5A:21:89"}, out


class Box:
    """the app's adapter switch, without the app"""
    check_adapter = bridge.App.check_adapter
    switch_adapter = bridge.App.switch_adapter

    def __init__(self, last_mac=None):
        import threading
        self.adapter, self.bt_lock, self.state = None, threading.Lock(), {"last_mac": last_mac}
        self.adapter_seen, self.adapter_since, self.adapter_retry, self.adapter_warned = None, {}, 0.0, set()
        self.said, self.posted, self.ran = [], [], []
        self.auto, self.connecting, self.own_connect_at = True, False, -1e9

    def say(self, text, seconds=3):
        self.said.append(text)

    def post(self, *event):
        self.posted.append(event)


def switch(box, found, powered, blocked=(), paired=True, rfkill=(), fresh=()):
    """run check_adapter with found adapters; powered: {name: on} the busctl calls left"""
    stand = {"adapters": btadapter.adapters, "set_powered": btadapter.set_powered, "address": btadapter.address,
             "blocked": btadapter.blocked}
    btadapter.blocked = lambda name: name in rfkill
    import time
    for name, _ in found:                     # (settled long ago, but fresh: just plugged in)
        box.adapter_since[name] = time.monotonic() - (0 if name in fresh else 60)
    btadapter.adapters = lambda: found
    btadapter.set_powered = lambda name, on: (powered.__setitem__(name, on), name not in blocked)[1]
    btadapter.address = lambda name: {"hci0": OWN, "hci1": DONGLE}[name]
    bt = bridge.bt
    bridge.bt = lambda *a, **k: (box.ran.append(a[0]),
                                 (0, "Connection successful" if a[0] == "connect" else
                                  "Paired: yes" if paired else "Device not available"))[1]
    import threading
    start = threading.Thread.start
    threading.Thread.start = lambda t: t.run()     # (switch_adapter in this thread)
    try:
        box.check_adapter()
    finally:
        threading.Thread.start = start
        bridge.bt = bt
        for k, v in stand.items():
            setattr(btadapter, k, v)


def test_switch():
    """plugged in: the Pi's own off, the USB one used and said; unplugged: the Pi's own back on"""
    box, powered = Box(last_mac=OWN), {}
    switch(box, [("hci0", False)], powered)
    assert box.adapter == ("hci0", False) and powered == {"hci0": True} and box.said == []   # (start: nothing said)
    assert btadapter.selected() is None
    switch(box, [("hci0", False), ("hci1", True)], powered, paired=False)
    assert box.adapter == ("hci1", True) and powered == {"hci0": False, "hci1": True}
    assert btadapter.selected() == DONGLE and box.said[-1] == "USB Bluetooth: pair the speaker again"
    assert box.ran == ["info"]                                    # (not paired there: no connect)
    powered.clear()
    switch(box, [("hci0", False), ("hci1", True)], powered)     # (no change: nothing done)
    assert powered == {}
    switch(box, [("hci0", False)], powered)
    assert box.adapter == ("hci0", False) and powered == {"hci0": True} and btadapter.selected() is None
    assert box.said[-1] == "The Pi's own Bluetooth" and box.posted
    assert box.ran[-2:] == ["info", "connect"] and box.own_connect_at > 0     # (paired there: connected at once)
    assert not box.connecting


def test_blocked():
    """a soft-blocked USB adapter: the Pi's own kept on, said"""
    box, powered = Box(), {}
    switch(box, [("hci0", False), ("hci1", True)], powered, blocked=("hci1",))
    assert box.adapter == ("hci0", False) and powered["hci0"] is True
    assert btadapter.selected() == OWN and "blocked" in box.said[-1]
    box2, powered = Box(), {}
    switch(box2, [("hci0", False), ("hci1", True)], powered)       # (fine, nothing to pair again)
    assert box2.said == ["USB Bluetooth"] and "connect" not in box2.ran    # (no speaker saved)


def test_settle():
    """a USB adapter blocked as it comes up isn't judged for ADAPTER_SETTLE s (systemd-rfkill unblocks it a few
    seconds in); BlueZ refusing to power it on is tried again, and "blocked" said once"""
    box, powered = Box(last_mac=OWN), {}
    switch(box, [("hci0", False)], powered)
    two = [("hci0", False), ("hci1", True)]
    switch(box, two, powered, rfkill=("hci1",), fresh=("hci1",))
    assert box.adapter == ("hci0", False) and box.adapter_seen[1] == 1 and "rfkill" not in " ".join(box.said)
    switch(box, two, powered, blocked=("hci1",))          # (settled, unblocked, but BlueZ refuses)
    assert box.adapter == ("hci0", False) and box.adapter_retry > 0 and box.said[-1].startswith("USB Bluetooth blocked")
    n = len(box.said)
    switch(box, two, powered, blocked=("hci1",))          # (too soon: not tried)
    box.adapter_retry = 0.0
    switch(box, two, powered, blocked=("hci1",))          # (tried again, refused again: not said again)
    assert len(box.said) == n
    box.adapter_retry = 0.0
    switch(box, two, powered)                             # (BlueZ takes it now)
    assert box.adapter == ("hci1", True) and btadapter.selected() == DONGLE


def test_not_ready():
    """just plugged in, BlueZ refuses it for a second (no object yet, Pocket 2: ~1.4 s): nothing said or changed,
    tried again a second later, then used"""
    box, powered = Box(last_mac=OWN), {}
    switch(box, [("hci0", False)], powered)
    two = [("hci0", False), ("hci1", True)]
    switch(box, two, powered, blocked=("hci1",), fresh=("hci1",))
    assert box.adapter == ("hci0", False) and box.said == [] and btadapter.selected() is None
    assert 0 < box.adapter_retry - __import__("time").monotonic() <= 1
    assert "hci0" not in powered or powered["hci0"] is True        # (the Pi's own left on)
    box.adapter_retry = 0.0
    switch(box, two, powered, fresh=("hci1",))
    assert box.adapter == ("hci1", True) and btadapter.selected() == DONGLE and powered["hci0"] is False
    assert not any("blocked" in t for t in box.said)


def test_rfkill():
    """an rfkill-blocked USB adapter is left out and said once; unblocked (no replug), it's used; unplugged, the
    chosen-adapter file goes"""
    box, powered = Box(last_mac=OWN), {}
    switch(box, [("hci0", False)], powered)
    two = [("hci0", False), ("hci1", True)]
    switch(box, two, powered, rfkill=("hci1",))
    assert box.adapter == ("hci0", False) and "hci1" not in powered and "rfkill" in box.said[-1]
    assert btadapter.selected() == OWN and "connect" not in box.ran
    n = len(box.said)
    switch(box, two, powered, rfkill=("hci1",))          # (still blocked: said once)
    assert len(box.said) == n
    switch(box, two, powered)                            # (unblocked)
    assert box.adapter == ("hci1", True) and powered == {"hci0": False, "hci1": True}
    assert btadapter.selected() == DONGLE and box.ran[-1] == "connect"
    switch(box, two, powered, rfkill=("hci1",))          # (blocked again, then unplugged)
    switch(box, [("hci0", False)], powered)
    assert box.adapter == ("hci0", False) and btadapter.selected() is None
    assert btadapter.blocked("hci9", TMP) is False


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
