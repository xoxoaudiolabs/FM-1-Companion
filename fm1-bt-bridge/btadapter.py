"""Which Bluetooth adapter the Pocket uses: a USB Bluetooth adapter while one is plugged in, else the Pi's own.

The Pi's own Bluetooth shares its chip with Wi-Fi. On the Studio (a Pi 3 B+, 2026-11-03, btmon) it sent A2DP to a
speaker in stalls of up to ~140 ms at SBC bitpool 14-16, where a TP-Link UB500 sent evenly at bitpool 53. Not
measured on a Pi Zero.

The app decides (bridge.check_adapter): a USB adapter there -> the Pi's own is powered off (BlueZ's Adapter1
Powered: no root needed in the bluetooth group) and everything Bluetooth goes to the USB one; unplugged -> the Pi's
own is powered on again. The adapter in use is written to a file (aim) that Bluetooth MIDI (blemidi) reads too.
Pairings belong to each adapter: on a new one, speakers and keyboards are paired again.

bluetoothctl only works on its default controller (the Pi's own) here: BlueZ 5.82 ignores --init-script with a
command given on its command line, and run as a script it quits before "connect" has its reply (both tried on
Pocket 2, 2026-11-03). So with a USB adapter in use the app's bluetoothctl commands go to BlueZ over D-Bus instead
(Bluetoothctl), answering in bluetoothctl's words; with the Pi's own alone, bluetoothctl as before.

Don't force the USB adapter with dtoverlay=disable-bt: tried on the Studio, it came back with no Bluetooth and no
Wi-Fi until a second power cycle, and unplugging the adapter would leave no Bluetooth at all.
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path("/sys/class/bluetooth")
SELECT = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "fm1-bt-select"
ADDRESS = re.compile(r"[0-9A-F]{2}(:[0-9A-F]{2}){5}")


def _run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode, r.stdout + r.stderr
    except (subprocess.TimeoutExpired, OSError) as e:
        return -1, str(e)


def adapters(root=ROOT, resolve=os.path.realpath, listdir=os.listdir):
    """[(name, usb)] in number order: ("hci0", False) the Pi's own, ("hci1", True) one on USB (its sysfs device
    goes through a USB port). (BlueZ's Modalias is usb:v1D6B... for every adapter: no help.)"""
    try:
        names = [n for n in listdir(root) if re.fullmatch(r"hci\d+", n)]     # (hci0:11: a link, not an adapter)
    except OSError:
        return []
    found = []
    for name in sorted(names, key=lambda n: int(n[3:])):
        try:
            found.append((name, "/usb" in resolve(os.path.join(root, name, "device"))))
        except OSError:
            found.append((name, False))
    return found


def blocked(name, root=ROOT):
    """the adapter is soft-blocked by rfkill (systemd-rfkill keeps the state for each USB port, so an adapter can
    come up blocked in one port and not another; unblocking needs root)"""
    for soft in Path(root, name).glob("rfkill*/soft"):
        try:
            if soft.read_text().strip() == "1":
                return True
        except OSError:
            pass
    return False


def choose(found):
    """the adapter to use: the first USB one, else the first (the Pi's own); None with none"""
    usb = [a for a in found if a[1]]
    return (usb or found or [None])[0]


def address(name, run=_run):
    """an adapter's address (BlueZ's), or None"""
    _, out = run(["busctl", "get-property", "org.bluez", f"/org/bluez/{name}", "org.bluez.Adapter1", "Address"])
    m = ADDRESS.search(out.upper())
    return m.group(0) if m else None


def set_powered(name, on, run=_run):
    """power an adapter on or off through BlueZ; False when it refused (a USB adapter soft-blocked by rfkill: the
    installer's "rfkill unblock bluetooth" covers one there at install time; later ones need it run as root)"""
    code, _ = run(["busctl", "set-property", "org.bluez", f"/org/bluez/{name}", "org.bluez.Adapter1", "Powered",
                   "b", "true" if on else "false"])
    return code == 0


def aim(addr, path=None):
    """bluetoothctl and Bluetooth MIDI use the adapter at addr from now on; None: BlueZ's default (one adapter)"""
    path = path or SELECT
    if addr:
        path.write_text(f"select {addr}\n")
    else:
        try:
            path.unlink()
        except OSError:
            pass


def selected(path=None):
    """the address aim() chose, or None"""
    try:
        m = ADDRESS.search((path or SELECT).read_text().upper())
    except OSError:
        return None
    return m.group(0) if m else None


AUDIO_SINK = "0000110b"


class Bluetoothctl:
    """The bluetoothctl commands the app uses, on the adapter at addr through BlueZ's D-Bus API, with the lines
    bluetoothctl would print (the app reads those: "Connection successful", "Paired: yes"...). One D-Bus connection
    each, so a scan's discovery lasts as long as it does and threads don't share one."""

    BLUEZ, OM, PROPS = "org.bluez", "org.freedesktop.DBus.ObjectManager", "org.freedesktop.DBus.Properties"
    ADAPTER, DEVICE = "org.bluez.Adapter1", "org.bluez.Device1"

    def __init__(self, addr, bus=None):
        if bus is None:
            import dbus
            bus = dbus.SystemBus(private=True)
        self.bus, self.addr = bus, addr

    def objects(self):
        return self.call("/", self.OM, "GetManagedObjects")

    def call(self, path, iface, method, *args, timeout=25):
        import dbus
        return dbus.Interface(self.bus.get_object(self.BLUEZ, path), iface).get_dbus_method(method)(
            *args, timeout=timeout)

    def adapter(self):
        for path, ifaces in self.objects().items():
            if str(ifaces.get(self.ADAPTER, {}).get("Address", "")).upper() == self.addr:
                return str(path)
        return None

    def device(self, adapter, mac):
        return f"{adapter}/dev_{mac.upper().replace(':', '_')}"

    def run(self, args, timeout=15):
        """bluetoothctl's args (as bridge.bt gets them) -> (exit code, output)"""
        import dbus
        args = list(args)
        if args[:2] == ["--agent", "NoInputNoOutput"]:     # (with no agent of its own BlueZ pairs as this)
            args = args[2:]
        seconds = None
        if args[:1] == ["--timeout"]:
            seconds, args = float(args[1]), args[2:]
        try:
            adapter = self.adapter()
            if not adapter:
                return 1, "org.bluez.Error.NotReady: no such adapter"
            return self.command(adapter, args, seconds, timeout)
        except dbus.DBusException as e:
            return 1, f"Failed: {e.get_dbus_name()} {e.get_dbus_message() or ''}"

    def command(self, adapter, args, seconds, timeout):
        import dbus
        import time
        verb, rest = args[0], args[1:]
        if verb == "scan":
            self.call(adapter, self.ADAPTER, "StartDiscovery")
            time.sleep(seconds or 5)
            try:
                self.call(adapter, self.ADAPTER, "StopDiscovery")
            except dbus.DBusException:
                pass
            return 0, "Discovery stopped"
        if verb == "pairable":
            self.call(adapter, self.PROPS, "Set", self.ADAPTER, "Pairable", dbus.Boolean(rest[0] == "on"))
            return 0, f"Changing pairable {rest[0]} succeeded"
        if verb == "devices":
            return 0, "".join(f"Device {d.get('Address')} {d.get('Alias') or d.get('Address')}\n"
                              for path, ifaces in sorted(self.objects().items())
                              for d in [ifaces.get(self.DEVICE)] if d and str(path).startswith(adapter + "/"))
        mac = rest[0].upper()
        path = self.device(adapter, mac)
        found = self.objects().get(dbus.ObjectPath(path), {}).get(self.DEVICE)
        if found is None:
            return 1, f"Device {mac} not available"
        if verb == "info":
            return 0, info_text(mac, found)
        if verb == "remove":
            self.call(adapter, self.ADAPTER, "RemoveDevice", dbus.ObjectPath(path))
            return 0, "Device has been removed"
        if verb == "trust":
            self.call(path, self.PROPS, "Set", self.DEVICE, "Trusted", dbus.Boolean(True))
            return 0, f"Changing {mac} trust succeeded"
        word = {"connect": ("Connect", "Connection successful", "Failed to connect"),
                "disconnect": ("Disconnect", "Successful disconnected", "Failed to disconnect"),
                "pair": ("Pair", "Pairing successful", "Failed to pair")}.get(verb)
        if not word:
            return 1, f"Invalid command {verb}"
        try:
            self.call(path, self.DEVICE, word[0], timeout=max(5, timeout - 2))
        except dbus.DBusException as e:
            return 1, f"{word[2]}: {e.get_dbus_name()} {e.get_dbus_message() or ''}"
        return 0, word[1]


def info_text(mac, dev):
    """a Device1's properties as bluetoothctl's info prints them (the lines bridge.parse_info reads)"""
    yes = lambda v: "yes" if v else "no"      # noqa: E731
    lines = [f"Device {mac}"]
    for key in ("Name", "Alias", "Icon"):
        if key in dev:
            lines.append(f"\t{key}: {dev[key]}")
    for key in ("Paired", "Bonded", "Trusted", "Connected"):
        if key in dev:
            lines.append(f"\t{key}: {yes(dev[key])}")
    for u in dev.get("UUIDs", []):
        u = str(u)
        lines.append(f"\tUUID: {'Audio Sink' if u.startswith(AUDIO_SINK) else 'Unknown'} ({u})")
    return "\n".join(lines) + "\n"


def bluetoothctl(args, timeout=15):
    """bridge.bt's way in: None with the default adapter (run bluetoothctl itself), else (exit code, output) from
    the chosen adapter over D-Bus"""
    addr = selected()
    if not addr:
        return None
    ctl = Bluetoothctl(addr)
    try:
        return ctl.run(args, timeout)
    finally:
        ctl.bus.close()
