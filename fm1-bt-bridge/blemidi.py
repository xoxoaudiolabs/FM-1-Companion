"""Bluetooth LE MIDI for the FM-1 Companion.

The Pi appears as a BLE MIDI device ("FM-1 Companion") that phones, tablets and computers connect to,
and MIDI passes both ways between it and the FM-1's USB MIDI port:

  phone / iPad / Mac  <--BLE MIDI-->  Pi  <--USB MIDI (ALSA sequencer, via mido)-->  FM-1

It also connects out to Bluetooth MIDI keyboards that wait to be connected to (a microKEY Air, a WIDI), as the
central: found by a scan, saved, and connected again by themselves. Several of each at once; all of them are
the matrix's BT.

The packet coding (encode / strip_timestamps) is plain Python; the BlueZ side needs python3-dbus
and python3-gi, the USB side python3-mido and python3-rtmidi.
"""
import re
import threading
import time

import sloop                            # which FM-1 is A and which is B (fm1_cards, port_card)

MIDI_SERVICE = "03b80e5a-ede8-4b33-a751-6ce34ec4c700"
MIDI_IO = "7772e5db-3868-4112-a1a9-f2669d106bf3"
PACKET = 20                 # ATT payload with the minimum MTU: safe with every central
DEVICE_NAME = "FM-1 Companion"
PAIRING_SECONDS = 120
KEYBOARD_SCAN = 8           # seconds a scan for Bluetooth MIDI keyboards takes
MAX_KEYBOARDS = 4           # saved keyboards (the Zero W's radio also carries the headphones)
ADDRESS =re.compile(r"([0-9A-Fa-f]{2}[-:]){5}[0-9A-Fa-f]{2}")     # what BlueZ calls a device before its name


# ---------------------------------------------------------------- BLE MIDI packets

def encode(messages, now_ms):
    """Complete MIDI messages (bytes each, SysEx with its F0 and F7) -> BLE MIDI packets."""
    ts = now_ms & 0x1FFF
    header, stamp = 0x80 | (ts >> 7), 0x80 | (ts & 0x7F)
    packets, cur = [], bytearray([header])

    def flush():
        if len(cur) > 1:
            packets.append(bytes(cur))
            cur[:] = bytes([header])

    for m in messages:
        if not m:
            continue
        if m[0] == 0xF0:
            flush()
            cur += bytes([stamp, 0xF0])
            for b in m[1:-1] if m[-1] == 0xF7 else m[1:]:
                if len(cur) == PACKET:
                    flush()                         # continuation packet: header, then data only
                cur.append(b)
            if len(cur) + 2 > PACKET:
                flush()
            cur += bytes([stamp, 0xF7])
            continue
        if len(cur) + 1 + len(m) > PACKET:
            flush()
        cur.append(stamp)
        cur += bytes(m)
    flush()
    return packets


def strip_timestamps(packet):
    """One BLE MIDI packet -> its plain MIDI bytes (running status kept; feed them to a parser)."""
    out = bytearray()
    if len(packet) < 2 or not packet[0] & 0x80:
        return bytes(out)
    i = 1
    while i < len(packet):
        b = packet[i]
        if b & 0x80:
            # a timestamp: before a status byte, or before running-status data
            if i + 1 < len(packet) and packet[i + 1] & 0x80:
                out.append(packet[i + 1])
                i += 2
            else:
                i += 1
        else:
            out.append(b)
            i += 1
    return bytes(out)


class MidiStream:
    """Plain MIDI bytes -> complete messages, with running status (BLE senders use it), real-time
    bytes anywhere, and SysEx split across packets."""

    def __init__(self):
        self.status, self.data, self.sysex = None, bytearray(), None

    @staticmethod
    def length(status):
        if 0xC0 <= status <= 0xDF or status in (0xF1, 0xF3):
            return 1
        return 2

    def feed(self, data):
        out = []
        for b in data:
            if b >= 0xF8:                               # real-time: passes through anything
                out.append(bytes([b]))
                continue
            if self.sysex is not None:
                if b == 0xF7:
                    out.append(bytes(self.sysex) + b"\xf7")
                    self.sysex = None
                    continue
                if b < 0x80:
                    self.sysex.append(b)
                    continue
                self.sysex = None                       # a status byte aborts the SysEx
            if b == 0xF0:
                self.sysex, self.status = bytearray([0xF0]), None
            elif b & 0x80:
                self.status, self.data = b, bytearray()
                if b in (0xF6, 0xF7):                   # tune request; a stray end of SysEx
                    if b == 0xF6:
                        out.append(b"\xf6")
                    self.status = None
            elif self.status is not None:
                self.data.append(b)
                if len(self.data) == self.length(self.status):
                    out.append(bytes([self.status]) + bytes(self.data))
                    self.data = bytearray()
                    if self.status >= 0xF0:             # system common: no running status
                        self.status = None
        return out


# ---------------------------------------------------------------- the FM-1's USB MIDI

FM1_IDS = ("0x1209:0x01", "pid.codes")    # the FM-1's USB ID, its ALSA name when its own name couldn't be read


DJ_CONTROLLERS = ("djcontrol",)                # Hercules DJControl: the Studio's DJ decks read it themselves


class UsbMidi:
    """One FM-1's USB MIDI ports through mido, reopened when the FM-1 comes and goes. Found by its name (or USB
    ID) only: anything else on a USB hub is a controller (UsbControllers), never taken for the FM-1. With two
    FM-1s on a hub, slot 0 is FM-1 A and slot 1 FM-1 B (sloop.fm1_cards: by hub port)."""

    SKIP = ("through", "rtmidi", "pipewire", "midi-bridge", "bluetooth")

    def __init__(self, match, on_message, slot=0):
        import mido
        self.mido, self.slot, self.cards = mido, slot, sloop.fm1_cards
        self.match, self.on_message = tuple(m.lower() for m in match) + FM1_IDS, on_message
        self.name, self.inp, self.out = None, None, None
        self.stream = MidiStream()
        self.last_activity = 0.0
        self.lock = threading.Lock()

    def pick(self, names, cards=None):
        names = [n for n in names if not any(s in n.lower() for s in self.SKIP)]
        if cards:                             # the FM-1s' sound cards, A first: this slot's one, by card (an
            card = cards[self.slot] if self.slot < len(cards) else None   # FM-1 running Clipper too)
            return next((n for n in names if sloop.port_card(n) == card), None)
        names = [n for n in names if any(m in n.lower() for m in self.match)]
        return names[self.slot] if self.slot < len(names) else None

    def poll(self):
        try:
            cards = self.cards()
            want_in = self.pick(self.mido.get_input_names(), cards)
            want_out = self.pick(self.mido.get_output_names(), cards)
        except Exception:
            want_in = want_out = None
        if want_in == self.name and (want_in is None or self.out is not None):
            return
        self.close()
        if want_in and want_out:
            try:
                self.out = self.mido.open_output(want_out)
                self.inp = self.mido.open_input(want_in, callback=self.received)
                self.name = want_in
            except Exception:
                self.close()

    def received(self, msg):
        self.last_activity = time.monotonic()
        self.on_message(bytes(msg.bytes()))

    def send_bytes(self, data):
        """Plain MIDI bytes (running status allowed) to the FM-1."""
        with self.lock:
            messages = self.stream.feed(data)
        self.send_messages(messages)

    def send_messages(self, messages):
        """Complete MIDI messages (bytes each) to the FM-1."""
        out = self.out
        if out is None:
            return
        with self.lock:
            for raw in messages:
                try:
                    out.send(self.mido.Message.from_bytes(list(raw)))
                    self.last_activity = time.monotonic()
                except (ValueError, OSError):       # a malformed message, or the FM-1 just left
                    continue

    def label(self):
        """The port's name for the screen: "Felucca:Felucca MIDI 1 24:0" -> "Felucca"."""
        return self.name.split(":")[0] if self.name else None

    def close(self):
        for port in (self.inp, self.out):
            try:
                if port:
                    port.close()
            except Exception:
                pass
        self.name, self.inp, self.out = None, None, None


# ---------------------------------------------------------------- BlueZ: GATT server, advertisement, agent

def start_bluez(bridge):
    """Build the D-Bus objects and run their GLib main loop (blocks: call from a thread)."""
    import dbus
    import dbus.mainloop.glib
    import dbus.service
    from gi.repository import GLib

    BLUEZ, OM, PROPS = "org.bluez", "org.freedesktop.DBus.ObjectManager", "org.freedesktop.DBus.Properties"
    SERVICE, CHRC, DEVICE = "org.bluez.GattService1", "org.bluez.GattCharacteristic1", "org.bluez.Device1"
    ADV, AGENT, ADAPTER = "org.bluez.LEAdvertisement1", "org.bluez.Agent1", "org.bluez.Adapter1"
    ROOT = "/org/fm1bridge"

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    class Characteristic(dbus.service.Object):
        def __init__(self):
            self.path = ROOT + "/service0/char0"
            self.notifying = False
            super().__init__(bus, self.path)

        def props(self):
            return {CHRC: {"UUID": MIDI_IO, "Service": dbus.ObjectPath(ROOT + "/service0"),
                           "Flags": dbus.Array(["read", "write", "write-without-response", "notify"],
                                               signature="s")}}

        @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface):
            return self.props()[CHRC]

        @dbus.service.method(CHRC, in_signature="a{sv}", out_signature="ay")
        def ReadValue(self, options):
            return dbus.Array([], signature="y")    # BLE MIDI: reads return no payload

        @dbus.service.method(CHRC, in_signature="aya{sv}")
        def WriteValue(self, value, options):
            bridge.from_ble(bytes(value), options.get("device"))

        @dbus.service.method(CHRC)
        def StartNotify(self):                # the first central to subscribe (BlueZ sends to each that has)
            self.notifying = True
            GLib.idle_add(bridge.find_names)  # after replying to bluetoothd

        @dbus.service.method(CHRC)
        def StopNotify(self):
            self.notifying = False
            GLib.idle_add(bridge.find_names)

        @dbus.service.signal(PROPS, signature="sa{sv}as")
        def PropertiesChanged(self, interface, changed, invalidated):
            pass

        def notify(self, packet):
            if self.notifying:
                self.PropertiesChanged(CHRC, {"Value": dbus.Array([dbus.Byte(b) for b in packet], signature="y")}, [])

    class Service(dbus.service.Object):
        def __init__(self):
            self.path = ROOT + "/service0"
            super().__init__(bus, self.path)

        def props(self):
            return {SERVICE: {"UUID": MIDI_SERVICE, "Primary": True}}

        @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface):
            return self.props()[SERVICE]

    class Application(dbus.service.Object):
        def __init__(self, service, chrc):
            self.path, self.service, self.chrc = ROOT, service, chrc
            super().__init__(bus, self.path)

        @dbus.service.method(OM, out_signature="a{oa{sa{sv}}}")
        def GetManagedObjects(self):
            return {dbus.ObjectPath(self.service.path): self.service.props(),
                    dbus.ObjectPath(self.chrc.path): self.chrc.props()}

    class Advertisement(dbus.service.Object):
        def __init__(self):
            self.path = ROOT + "/adv0"
            super().__init__(bus, self.path)

        @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
        def GetAll(self, interface):
            return {"Type": "peripheral", "LocalName": DEVICE_NAME,
                    "ServiceUUIDs": dbus.Array([MIDI_SERVICE], signature="s")}

        @dbus.service.method(ADV)
        def Release(self):
            pass

    class Agent(dbus.service.Object):
        """Accepts "just works" pairing. Incoming pairing is only possible while the pairing
        window is open (the adapter's Pairable), so this does not let anyone pair at any time."""

        def __init__(self):
            self.path = ROOT + "/agent"
            super().__init__(bus, self.path)

        @dbus.service.method(AGENT)
        def Release(self):
            pass

        @dbus.service.method(AGENT, in_signature="os")
        def AuthorizeService(self, device, uuid):
            pass

        @dbus.service.method(AGENT, in_signature="o", out_signature="s")
        def RequestPinCode(self, device):
            return "0000"

        @dbus.service.method(AGENT, in_signature="o", out_signature="u")
        def RequestPasskey(self, device):
            return dbus.UInt32(0)

        @dbus.service.method(AGENT, in_signature="ouq")
        def DisplayPasskey(self, device, passkey, entered):
            pass

        @dbus.service.method(AGENT, in_signature="os")
        def DisplayPinCode(self, device, pincode):
            pass

        @dbus.service.method(AGENT, in_signature="ou")
        def RequestConfirmation(self, device, passkey):
            pass

        @dbus.service.method(AGENT, in_signature="o")
        def RequestAuthorization(self, device):
            pass

        @dbus.service.method(AGENT)
        def Cancel(self):
            pass

    chrc = Characteristic()
    app = Application(Service(), chrc)
    adv = Advertisement()
    agent = Agent()
    state = {"adapter": None, "advertising": False}
    links = {}                                # a linked keyboard's device path -> (its MIDI characteristic, iface)
    central = {"connecting": None, "tries": {}, "scanned": 0.0}   # tries: address -> (next try, wait after it)

    def adapter_path():
        objects = dbus.Interface(bus.get_object(BLUEZ, "/"), OM).GetManagedObjects()
        for path, ifaces in objects.items():
            if "org.bluez.GattManager1" in ifaces and "org.bluez.LEAdvertisingManager1" in ifaces:
                return path
        return None

    def ignore(*args):
        pass

    def register():
        """(Re)register everything with bluetoothd; called at start and whenever it restarts."""
        state["advertising"] = False
        for path in list(links):              # a restarted bluetoothd has dropped them: reconnect() starts again
            unlink(path)
        central["connecting"] = None
        path = adapter_path()
        state["adapter"] = path
        if not path:
            return
        obj = bus.get_object(BLUEZ, path)
        props = dbus.Interface(obj, PROPS)
        props.Set(ADAPTER, "Powered", dbus.Boolean(True))
        props.Set(ADAPTER, "Alias", DEVICE_NAME)
        props.Set(ADAPTER, "Pairable", dbus.Boolean(False))
        manager = dbus.Interface(bus.get_object(BLUEZ, "/org/bluez"), "org.bluez.AgentManager1")
        try:
            manager.RegisterAgent(agent.path, "NoInputNoOutput")
            manager.RequestDefaultAgent(agent.path)
        except dbus.DBusException:
            pass
        dbus.Interface(obj, "org.bluez.GattManager1").RegisterApplication(
            app.path, {}, reply_handler=ignore, error_handler=ignore)
        set_advertising(bridge.enabled)
        GLib.timeout_add_seconds(5, close_pairing)    # bluetoothd turns Pairable back on as it powers up
        GLib.timeout_add_seconds(2, refresh_keyboards)

    def refresh_keyboards():
        """MIDI devices still linked from before this service existed (the Companion restarted, or the keyboard
        connected first at boot) write to a service that's gone: their MIDI goes nowhere until they look it up
        again. Disconnect them so they reconnect and find it; headphones and speakers are left alone, and a saved
        keyboard the box connects to itself is taken up where it is."""
        saved = saved_addresses()
        for path, ifaces in managed().items():
            dev = ifaces.get(DEVICE)
            if not (dev and dev.get("Connected")) or is_audio(dev) or str(path) in bridge.peers:
                continue
            if str(dev.get("Address", "")).upper() in saved:
                link(str(path))
                continue
            try:
                dbus.Interface(bus.get_object(BLUEZ, path), DEVICE).Disconnect()
            except dbus.DBusException:
                pass
        return False

    def close_pairing():
        if state["adapter"] and time.monotonic() >= bridge.pairing_until:
            try:
                dbus.Interface(bus.get_object(BLUEZ, state["adapter"]), PROPS).Set(
                    ADAPTER, "Pairable", dbus.Boolean(False))
            except dbus.DBusException:
                pass
        return False

    def set_advertising(on):
        path = state["adapter"]
        if not path or on == state["advertising"]:
            return
        manager = dbus.Interface(bus.get_object(BLUEZ, path), "org.bluez.LEAdvertisingManager1")
        if on:
            manager.RegisterAdvertisement(adv.path, {}, reply_handler=ignore, error_handler=ignore)
        else:
            try:
                manager.UnregisterAdvertisement(adv.path)
            except dbus.DBusException:
                pass
        state["advertising"] = on

    def open_pairing():
        if state["adapter"]:
            props = dbus.Interface(bus.get_object(BLUEZ, state["adapter"]), PROPS)
            props.Set(ADAPTER, "PairableTimeout", dbus.UInt32(PAIRING_SECONDS))
            props.Set(ADAPTER, "Pairable", dbus.Boolean(True))

    def managed():
        return dbus.Interface(bus.get_object(BLUEZ, "/"), OM).GetManagedObjects()

    def is_audio(dev):
        return any(str(u).startswith("0000110b") for u in dev.get("UUIDs", []))

    def device_path(address):
        return f"{state['adapter']}/dev_{address.upper().replace(':', '_')}"

    def saved_addresses():
        return {a.upper() for a, _ in bridge.ble_saved}

    def connected_peers():
        """[(path, name, address)]: the connected devices that aren't headphones (MIDI centrals, keyboards)"""
        return [(str(path), str(dev.get("Alias", "")), str(dev.get("Address", "")))
                for path, ifaces in managed().items()
                for dev in [ifaces.get(DEVICE)] if dev and dev.get("Connected") and not is_audio(dev)]

    # ---- the box as the central: Bluetooth MIDI keyboards that wait to be connected to

    def reason(e):
        """a D-Bus error from BlueZ, in words that fit the screen"""
        text = f"{e.get_dbus_name()} {e.get_dbus_message()}"
        for needle, words in (("abort-by-local", "No answer: is it on?"), ("page-timeout", "No answer: is it on?"),
                              ("NoReply", "No answer: is it on?"), ("Timeout", "No answer: is it on?"),
                              ("AuthenticationFailed", "Pairing rejected"),
                              ("AuthenticationCanceled", "Pairing cancelled"),
                              ("InProgress", "Busy: try again"), ("NotReady", "Bluetooth is off"),
                              ("UnknownObject", "Not found: scan again"), ("DoesNotExist", "Not found: scan again")):
            if needle in text:
                return words
        return (e.get_dbus_message() or "failed")[:30]

    def keyboard_scan(seconds=KEYBOARD_SCAN):
        """Look for Bluetooth MIDI keyboards (the MIDI service in what they advertise) for seconds: then
        bridge.ble_found is [[address, name]]. The headphone scan (bluetoothctl, the app's) can run alongside."""
        if not state["adapter"] or bridge.ble_scanning:
            return False
        adapter = dbus.Interface(bus.get_object(BLUEZ, state["adapter"]), ADAPTER)
        try:
            adapter.SetDiscoveryFilter({"UUIDs": dbus.Array([MIDI_SERVICE], signature="s"), "Transport": "le"})
            adapter.StartDiscovery()
        except dbus.DBusException as e:
            bridge.note("Scan: " + reason(e))
            return False
        bridge.ble_scanning = True
        GLib.timeout_add_seconds(seconds, scan_done)
        return False

    def scan_done():
        found = []
        for path, ifaces in managed().items():   # before StopDiscovery: RSSI marks the ones seen just now
            dev = ifaces.get(DEVICE)
            if (dev and "RSSI" in dev and str(path).startswith(state["adapter"] + "/")
                    and MIDI_SERVICE in [str(u).lower() for u in dev.get("UUIDs", [])]):
                found.append([str(dev["Address"]), str(dev.get("Alias", dev["Address"]))])
        try:
            dbus.Interface(bus.get_object(BLUEZ, state["adapter"]), ADAPTER).StopDiscovery()
        except dbus.DBusException:
            pass
        bridge.ble_found, bridge.ble_scanning = sorted(found, key=lambda f: f[1].lower()), False
        reconnect()                           # a saved keyboard the adapter had forgotten may be in it
        return False

    def keyboard_connect(address, quiet=False):
        """Connect to a keyboard as its central (one at a time: each try holds the radio for up to ~30 s);
        linked once its services are read. quiet: an automatic try, nothing said if it fails."""
        if not state["adapter"] or central["connecting"]:
            if not quiet:
                bridge.note("Busy: try again")
            return False
        path = device_path(address)
        try:
            dev = dbus.Interface(bus.get_object(BLUEZ, path), PROPS).GetAll(DEVICE)
        except dbus.DBusException:
            if not quiet:
                bridge.note("Not found: scan again")
            return False
        if dev.get("Connected") and dev.get("ServicesResolved"):
            link(path, wanted=True)
            return False
        central["connecting"] = path
        name = str(dev.get("Alias", address))

        def done():
            central["connecting"] = None
            try:                              # kept by BlueZ (not a passing scan result) for next time
                dbus.Interface(bus.get_object(BLUEZ, path), PROPS).Set(DEVICE, "Trusted", dbus.Boolean(True))
            except dbus.DBusException:
                pass
            GLib.timeout_add(500, lambda: (link(path, wanted=True), False)[1])   # else ServicesResolved links it

        def failed(e):
            central["connecting"] = None
            if not quiet:
                bridge.note(f"{name}: {reason(e)}")

        if not quiet:
            bridge.note(f"Connecting {name}")
        dbus.Interface(bus.get_object(BLUEZ, path), DEVICE).Connect(reply_handler=done, error_handler=failed,
                                                                    timeout=35)
        return False

    def link(path, wanted=False):
        """A connected keyboard's MIDI characteristic: notifications on, its writes ready. wanted: connected
        from the list (saved now); else only a saved keyboard is taken up."""
        if path in links:
            return
        try:
            dev = dbus.Interface(bus.get_object(BLUEZ, path), PROPS).GetAll(DEVICE)
        except dbus.DBusException:
            return
        address, name = str(dev.get("Address", "")), str(dev.get("Alias", ""))
        if not (wanted or address.upper() in saved_addresses()):
            return
        found = [str(p) for p, ifaces in managed().items() if str(p).startswith(path + "/")
                 and str(ifaces.get(CHRC, {}).get("UUID", "")).lower() == MIDI_IO]
        if not found:
            if wanted and dev.get("ServicesResolved"):
                bridge.note(f"{name}: not a MIDI device")
            return                            # services still being read: ServicesResolved calls again
        chrc_obj = dbus.Interface(bus.get_object(BLUEZ, found[0], introspect=False), CHRC)
        links[path] = (found[0], chrc_obj)
        chrc_obj.StartNotify(reply_handler=ignore, error_handler=lambda e: (unlink(path),
                                                                          bridge.note(f"{name}: {reason(e)}")))
        chrc_obj.ReadValue({}, reply_handler=ignore, error_handler=ignore)    # BLE MIDI: the central reads once
        central["tries"].pop(address.upper(), None)
        bridge.keyboard_linked(path, address, name)

    def unlink(path):
        if links.pop(path, None):
            bridge.keyboard_gone(path)

    def keyboard_forget(address):
        bridge.ble_saved = [s for s in bridge.ble_saved if s[0].upper() != address.upper()]
        path = device_path(address)
        unlink(path)
        try:                                  # disconnects it, and forgets a pairing
            dbus.Interface(bus.get_object(BLUEZ, state["adapter"]), ADAPTER).RemoveDevice(path)
        except dbus.DBusException:
            pass
        return False

    def keyboard_write(path, packet):
        link_ = links.get(path)
        if link_:
            link_[1].WriteValue(dbus.Array([dbus.Byte(b) for b in packet], signature="y"), {"type": "command"},
                                reply_handler=ignore, error_handler=ignore)

    def reconnect():
        """Every few seconds: a saved keyboard that isn't linked gets a try, one at a time, each less often
        after it fails (5 s, doubling to a minute: a try that waits for a keyboard that's off takes the radio
        from the headphones a little). One the adapter no longer knows needs a scan to be seen again."""
        missing = [a.upper() for a, _ in bridge.ble_saved if device_path(a) not in links] if state["adapter"] else []
        if not (missing and bridge.enabled) or central["connecting"] or bridge.ble_scanning:
            return True
        known = {str(p) for p, ifaces in managed().items() if DEVICE in ifaces}
        now = time.monotonic()
        for address in missing:
            due, wait = central["tries"].get(address, (0.0, 5))
            if now < due:
                continue
            central["tries"][address] = (now + wait, min(60, wait * 2))
            if device_path(address) in known:
                keyboard_connect(address, quiet=True)
            elif now - central["scanned"] > 60:
                central["scanned"] = now
                keyboard_scan(5)
            break
        return True

    def set_central(on):
        """BLE MIDI off: the keyboards are let go (reconnect() leaves them alone until it's on again)"""
        if not on:
            for path in list(links):
                unlink(path)
                try:
                    dbus.Interface(bus.get_object(BLUEZ, path), DEVICE).Disconnect()
                except dbus.DBusException:
                    pass
            central["tries"].clear()

    def device_changed(interface, changed, invalidated, path=None):
        if interface != DEVICE:
            return
        path = str(path)
        if "Connected" in changed:
            if not changed["Connected"]:
                unlink(path)
                bridge.streams.pop(path, None)
            GLib.idle_add(bridge.find_names)
        if changed.get("ServicesResolved"):
            GLib.idle_add(lambda: (link(path), False)[1])

    def chrc_changed(interface, changed, invalidated, path=None):
        """a keyboard's notification: its MIDI"""
        if interface == CHRC and "Value" in changed:
            device = str(path).rsplit("/", 2)[0]
            if links.get(device, (None,))[0] == str(path):
                bridge.from_ble(bytes(changed["Value"]), device)

    def try_register():
        try:
            register()
            bridge.error = None
        except dbus.DBusException as e:     # adapter not ready yet: try again
            bridge.error = str(e)[:40]
            GLib.timeout_add_seconds(3, try_register)
        return False

    def owner_changed(owner):
        if owner:
            GLib.timeout_add(500, try_register)

    bus.add_signal_receiver(device_changed, dbus_interface=PROPS, signal_name="PropertiesChanged",
                            arg0=DEVICE, path_keyword="path")
    bus.add_signal_receiver(chrc_changed, dbus_interface=PROPS, signal_name="PropertiesChanged",
                            arg0=CHRC, bus_name=BLUEZ, path_keyword="path")    # (not our own characteristic's)
    bus.watch_name_owner(BLUEZ, owner_changed)    # also calls back now if bluetoothd is running

    bridge.bluez = {"notify": chrc.notify, "set_advertising": set_advertising, "open_pairing": open_pairing,
                    "connected_peers": connected_peers, "idle_add": GLib.idle_add,
                    "timeout_add_seconds": GLib.timeout_add_seconds, "write": keyboard_write,
                    "scan": keyboard_scan, "connect": keyboard_connect, "forget": keyboard_forget,
                    "set_central": set_central}
    GLib.timeout_add_seconds(5, reconnect)
    GLib.MainLoop().run()


CLOCK, START, CONTINUE, STOP = 0xF8, 0xFA, 0xFB, 0xFC
TRANSPORT = (CLOCK, START, CONTINUE, STOP)


def make_realtime(priority=10):
    """Real-time scheduling for the calling thread through RTKit (as PipeWire gets it; the installer's
    polkit rule allows it without a desktop session). Best effort: without it the clock just wobbles more."""
    bus = None
    try:
        import resource
        import dbus
        resource.setrlimit(resource.RLIMIT_RTTIME, (200_000, 200_000))   # RTKit insists on a limit
        # a private connection: the shared one must be made by start_bluez, with its GLib main loop,
        # or the MIDI service can't be exported ("BT error")
        bus = dbus.SystemBus(private=True)
        rtkit = dbus.Interface(bus.get_object("org.freedesktop.RealtimeKit1", "/org/freedesktop/RealtimeKit1"),
                               "org.freedesktop.RealtimeKit1")
        rtkit.MakeThreadRealtime(dbus.UInt64(threading.get_native_id()), dbus.UInt32(priority))
    except Exception:
        pass
    finally:
        if bus is not None:
            bus.close()


class ClockWatch:
    """The tempo and beat grid of a clock (24 ticks a quarter note) from the times its ticks arrived. Over
    Bluetooth ticks arrive bunched (several to a radio packet), so the grid is a straight line fitted through
    the last 48 ticks (two beats), not the arrival time of any one tick."""

    def __init__(self):
        self.ticks, self.playing = [], False   # [(tick number, arrival time)]
        self.count = 0                          # ticks since Start (or since the clock appeared)

    def message(self, status, now):
        if status == CLOCK:
            self.ticks.append((self.count, now))
            del self.ticks[:-48]
            self.count += 1
        elif status in (START, CONTINUE):
            self.playing = True
            if status == START:
                self.count, self.ticks = 0, []      # the next tick is beat 1 of bar 1
        elif status == STOP:
            self.playing = False

    def fit(self, now):
        """(seconds per tick, time of tick 0) by least squares, or None if no clock for half a second"""
        t = self.ticks
        if len(t) < 13 or now - t[-1][1] > 0.5:
            return None
        n = len(t)
        mx, my = sum(k for k, _ in t) / n, sum(v for _, v in t) / n
        sxx = sum((k - mx) ** 2 for k, _ in t)
        if not sxx:
            return None
        per = sum((k - mx) * (v - my) for k, v in t) / sxx
        return (per, my - per * mx) if per > 0 else None

    def bpm(self, now):
        f = self.fit(now)
        return 60.0 / (f[0] * 24) if f else None

    def bar(self, now):
        """when the current bar (96 ticks) began, on the fitted grid"""
        f = self.fit(now)
        if not f:
            return None
        return f[1] + f[0] * 96 * (self.ticks[-1][0] // 96)


class UsbControllers:
    """USB MIDI controllers (on a hub): every MIDI port that isn't the FM-1, a Bluetooth link or the system's own,
    opened as it appears and closed as it goes, up to MAX. They merge into one source and one destination: "USB"
    in the matrix."""

    MAX, MAX_STUDIO = 4, 8

    def __init__(self, fm1, on_message):
        import mido
        self.mido, self.fm1, self.on_message = mido, fm1, on_message
        self.ports = {}                     # client name ("SMK-37+VA") -> {"in": port, "out": port or None}
        self.last_activity = 0.0
        self.lock = threading.Lock()

    def wanted(self, names):
        """mido port names -> {client name: port name} of the controllers among them (a client's first port)"""
        out, fm1s = {}, set(sloop.fm1_cards())
        for name in names:
            low = name.lower()
            if (any(s in low for s in UsbMidi.SKIP) or any(m in low for m in self.fm1.match)
                    or ADDRESS.search(name) or sloop.port_card(name) in fm1s):   # (an FM-1's, by its card)
                continue
            if any(d in low for d in DJ_CONTROLLERS):  # a DJ controller: the decks' (decks.py), not a keyboard
                continue
            out.setdefault(name.split(":")[0], name)
        return out

    def poll(self):
        try:
            ins = self.wanted(self.mido.get_input_names())
            outs = self.wanted(self.mido.get_output_names())
        except Exception:
            return
        for name in [n for n in self.ports if n not in ins]:
            self.close(name)
        for name, port in ins.items():
            if name in self.ports or len(self.ports) >= self.MAX:
                continue
            try:
                inp = self.mido.open_input(port, callback=lambda msg, name=name: self.received(msg, name))
            except Exception:
                continue
            try:
                out = self.mido.open_output(outs[name]) if name in outs else None
            except Exception:
                out = None
            with self.lock:
                self.ports[name] = {"in": inp, "out": out}

    def received(self, msg, name=None):
        self.last_activity = time.monotonic()
        self.on_message(bytes(msg.bytes()), name)

    def send_messages(self, messages):
        """complete MIDI messages to every controller that takes MIDI in"""
        with self.lock:
            for port in self.ports.values():
                if port["out"] is None:
                    continue
                for raw in messages:
                    try:
                        port["out"].send(self.mido.Message.from_bytes(list(raw)))
                    except (ValueError, OSError):
                        break                 # a malformed message, or the controller just left

    def send_to(self, name, messages):
        """complete MIDI messages to one controller (a route to it alone, on the Studio)"""
        with self.lock:
            port = (self.ports.get(name) or {}).get("out")
            if port is None:
                return
            for raw in messages:
                try:
                    port.send(self.mido.Message.from_bytes(list(raw)))
                except (ValueError, OSError):
                    break

    def names(self):
        return sorted(self.ports)

    def close(self, name):
        with self.lock:
            port = self.ports.pop(name, None)
        for p in (port or {}).values():
            try:
                if p:
                    p.close()
            except Exception:
                pass


# ---------------------------------------------------------------- the MIDI matrix

SOURCES, DESTINATIONS = ("BT", "USB", "NET", "FM-1", "FM-1 B", "Box"), ("FM-1", "FM-1 B", "BT", "USB", "NET",
                                                                       "SMP")
# SMP: the Studio's MPC-style sampler (pads.py): notes 36-51 play its 16 pads
# NET: network MIDI (netmidi.py: a DAW on a computer, such as Kraken), on the desk box
FM1S = ("FM-1", "FM-1 B")               # FM-1 A (the only one, usually) and a second FM-1 on the hub
ROUTES = tuple(f"{s}>{d}" for s in SOURCES for d in DESTINATIONS if s != d)    # "Box": its clock, Start/Stop
DEFAULT_ROUTE = {"on": True, "channels": "same", "transpose": 0, "velocity": "normal", "fixed": 100,
                 "drop_clock": False, "drop_aftertouch": False, "drop_bend": False,
                 "chord_on": False, "chord": "maj", "arp_on": False, "arp": "up", "arp_rate": "1/8",
                 "arp_octaves": 1}
CURVES = {"normal": 1.0, "soft": 0.6, "hard": 1.6}      # velocity out = 127 * (in / 127) ** exponent
CHORDS = {"oct": (0, 12), "5th": (0, 7), "maj": (0, 4, 7), "min": (0, 3, 7), "7": (0, 4, 7, 10),
          "maj7": (0, 4, 7, 11), "m7": (0, 3, 7, 10)}    # chord memory: the notes one key plays
ARPS = ("up", "down", "updown", "played", "random")
ARP_RATES = {"1/4": 24, "1/8": 12, "1/8T": 8, "1/16": 6}  # clock ticks (24 a quarter note) per step


# USB controllers play the FM-1, and both FM-1s play together; the rest is a choice
OFF_AT_FIRST = ("USB>BT", "FM-1>USB", "BT>USB", "Box>USB", "FM-1>FM-1 B", "FM-1 B>FM-1", "FM-1 B>BT", "FM-1 B>USB",
                "USB>NET", "BT>NET", "NET>BT", "NET>USB", "Box>NET", "FM-1 B>NET",   # a DAW plays both FM-1s
                "FM-1>SMP", "FM-1 B>SMP", "Box>SMP")    # the keyboards and a DAW play the pads


# The Studio gives each USB MIDI device its own row and column ("U:" + its name: "U:EP-136"), where the Pocket
# has them all as one, USB. A device's routes start as USB's (it plays both FM-1s and the pads, nothing is sent
# to it); from one device to another: off at first. Saved by name: a device keeps its routes when replugged.
DEVICE = "U:"


def device_key(name):
    return DEVICE + str(name).replace(">", "")[:32]


def generic(end):
    """a matrix end as the Pocket's: a USB device is USB"""
    return "USB" if end.startswith(DEVICE) else end


def matrix(devices=None):
    """(sources, destinations): devices None, the Pocket's (USB, all of them as one); a list of USB MIDI device
    names, the Studio's (each its own, where USB is)"""
    if devices is None:
        return SOURCES, DESTINATIONS
    keys = [device_key(n) for n in devices]

    def put(ends):
        i = ends.index("USB")
        return ends[:i] + tuple(keys) + ends[i + 1:]
    return put(SOURCES), put(DESTINATIONS)


def route_keys(devices=None):
    sources, dests = matrix(devices)
    return [f"{s}>{d}" for s in sources for d in dests if s != d]


def known_route(key):
    """a route the matrix can have: the fixed ones, or a USB device's"""
    if key in ROUTES:
        return True
    src, sep, dest = key.partition(">")
    ok = lambda end, ends: end in ends or (end.startswith(DEVICE) and 2 < len(end) <= 34)   # noqa: E731
    return bool(sep) and src != dest and ok(src, SOURCES) and ok(dest, DESTINATIONS) and DEVICE in key


def route_default(key):
    src, _, dest = key.partition(">")
    if src.startswith(DEVICE) and dest.startswith(DEVICE):
        return dict(DEFAULT_ROUTE, on=False)
    return dict(DEFAULT_ROUTE, on=f"{generic(src)}>{generic(dest)}" not in OFF_AT_FIRST)


def default_routes():
    """every route on but the USB ones above, nothing changed: MIDI passes as it always did"""
    return {key: route_default(key) for key in ROUTES}


def clean_routes(routes):
    """routes from outside (the web page) -> the same, checked and complete; ValueError says what's wrong"""
    if not isinstance(routes, dict):
        raise ValueError("routes must be an object")
    out = default_routes()
    for key, route in routes.items():
        if not known_route(key) or not isinstance(route, dict):
            raise ValueError(f"no route {key!r}")
        out.setdefault(key, route_default(key))
        for name, value in route.items():
            if name not in DEFAULT_ROUTE:
                raise ValueError(f"{key}: no setting {name!r}")
            if not ROUTE_RULES[name](value):
                raise ValueError(f"{key}: bad {name} {value!r}")
            out[key][name] = value
    return out


def _int(value, lo, hi):
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


ROUTE_RULES = {                         # each route setting: what it may be (checked lazily, one rule a value)
    "on": lambda v: isinstance(v, bool), "drop_clock": lambda v: isinstance(v, bool),
    "drop_aftertouch": lambda v: isinstance(v, bool), "drop_bend": lambda v: isinstance(v, bool),
    "chord_on": lambda v: isinstance(v, bool), "arp_on": lambda v: isinstance(v, bool),
    "channels": lambda v: v == "same" or _int(v, 0, 15) or (
        isinstance(v, list) and len(v) == 16 and all(c is None or _int(c, 0, 15) for c in v)),
    "transpose": lambda v: _int(v, -24, 24),
    "velocity": lambda v: v in ("normal", "soft", "hard", "fixed"),
    "fixed": lambda v: _int(v, 1, 127),
    "chord": lambda v: isinstance(v, str) and v in CHORDS, "arp": lambda v: isinstance(v, str) and v in ARPS,
    "arp_rate": lambda v: isinstance(v, str) and v in ARP_RATES, "arp_octaves": lambda v: _int(v, 1, 3),
}


class Route:
    """One crossing of the matrix: whether it passes MIDI, and what it does to it on the way.
    channels: "same", one channel for everything (0-15), or 16 entries (a channel 0-15, or None: dropped).
    chord_on: one key plays a chord (chord: which, CHORDS). arp_on: the held notes (chords included) are played
    one at a time on the clock (tick(), 24 a quarter note), ARP_RATES apart, each for half a step (arp: the
    pattern, ARPS). Switching either off keeps the choice of chord and pattern for next time.
    A note-off always stops what its note-on started, so changing a route while a key is held can't leave a
    note hanging. apply() and tick() run on different threads: a lock keeps them apart."""

    def __init__(self, settings=None):
        self.active = {}                    # (channel, note) in -> [(channel, note) out], for held notes
        self.held = []                      # arp: [(channel, note, velocity)] in the order played
        self.sounding, self.ticks, self.step = None, 0, 0     # arp: the note playing, ticks counted, steps
        self.lock = threading.Lock()
        self.update(settings)

    def update(self, settings):
        """new settings -> the note-offs that must go out now (an arp switched off mid-note)"""
        with self.lock:
            self.s = dict(DEFAULT_ROUTE, **(settings or {}))
            if self.s["arp"] not in ARPS:     # settings saved before arp_on: "off" was a pattern then
                self.s["arp"] = "up"
            if self.s["chord"] not in CHORDS:
                self.s["chord"] = "maj"
            if not self.arp_active():
                self.held = []
                return self.silence()
            return []

    def silence(self):
        if not self.sounding:
            return []
        channel, note = self.sounding
        self.sounding = None
        return [bytes([0x80 | channel, note, 0])]

    def out_channel(self, channel):
        channels = self.s["channels"]
        if channels == "same":
            return channel
        if isinstance(channels, int):
            return channels
        return channels[channel] if isinstance(channels, list) and len(channels) == 16 else channel

    def note(self, channel, note):
        out, moved = self.out_channel(channel), note + self.s["transpose"]
        return (out, moved) if out is not None and 0 <= moved <= 127 else None

    def chord(self, channel, note):
        """the (channel, note) outs one played note makes: its chord, mapped and transposed"""
        outs = []
        for interval in self.shape():
            out = self.note(channel, note + interval)
            if out and out not in outs:
                outs.append(out)
        return outs

    def shape(self):
        """the intervals one key plays: the chord's, or just the note"""
        return CHORDS[self.s["chord"]] if self.s["chord_on"] else (0,)

    def velocity(self, value):
        if self.s["velocity"] == "fixed":
            return max(1, min(127, int(self.s["fixed"])))
        return max(1, min(127, round(127 * (value / 127) ** CURVES.get(self.s["velocity"], 1.0))))

    def apply(self, message):
        """a complete MIDI message -> the first message out of this route (bytes), or None"""
        out = self.apply_all(message)
        return out[0] if out else None

    def apply_all(self, message):
        """a complete MIDI message -> what comes out of this route: a list of messages (a chord: several;
        with the arp on, notes wait for the clock)"""
        with self.lock:
            return self._apply(message)

    def _apply(self, message):
        s, status = self.s, message[0]
        if status >= 0xF0:                                  # system: SysEx, clock, Start/Stop...
            if not s["on"] or (status in TRANSPORT and s["drop_clock"]):
                return []
            return [message]
        kind, channel = status & 0xF0, status & 0x0F
        if kind in (0x80, 0x90) and len(message) == 3:
            key = (channel, message[1])
            off = kind == 0x80 or message[2] == 0           # note off (or note on at velocity 0)
            if s["arp_on"] and s["on"]:                     # the arp plays the held notes on the clock
                self.held = [h for h in self.held if h[:2] != key]
                if not off:
                    self.held.append((channel, message[1], message[2]))
                return [] if self.held else self.silence()
            if off:
                outs = self.active.pop(key, None) or (self.chord(*key) if s["on"] else [])
                return [bytes([kind | c, n, message[2]]) for c, n in outs]
            outs = self.chord(*key) if s["on"] else []
            if outs:
                self.active[key] = outs
            return [bytes([0x90 | c, n, self.velocity(message[2])]) for c, n in outs]
        if not s["on"] or (kind in (0xA0, 0xD0) and s["drop_aftertouch"]) or (kind == 0xE0 and s["drop_bend"]):
            return []
        if kind == 0xA0 and len(message) == 3:              # poly aftertouch: follows the note
            out = self.note(channel, message[1])
            return [bytes([0xA0 | out[0], out[1], message[2]])] if out else []
        out = self.out_channel(channel)
        return [] if out is None else [bytes([kind | out]) + bytes(message[1:])]

    # ---- the arpeggiator

    def arp_notes(self):
        """the notes the arp steps through, [(channel, note, velocity)], in the pattern's order (one cycle)"""
        notes = []
        for channel, note, velocity in self.held:
            for interval in self.shape():
                notes.append((channel, note + interval, velocity))
        octaves = max(1, min(4, int(self.s["arp_octaves"])))
        notes = [(c, n + 12 * o, v) for o in range(octaves) for c, n, v in notes]
        pattern = self.s["arp"]
        if pattern == "played":
            return notes
        notes = sorted(set(notes), key=lambda x: x[1])
        if pattern == "down":
            return notes[::-1]
        if pattern == "updown":
            return notes + notes[-2:0:-1]
        return notes                                        # up, and the pool for random

    def tick(self):
        """one clock tick (24 a quarter note): the arp's note-offs and note-ons due now"""
        with self.lock:
            if not self.arp_active():
                return []
            rate = ARP_RATES.get(self.s["arp_rate"], 12)
            out = []
            if self.ticks % rate == rate // 2 or not self.held:          # half a step: the note ends
                out += self.silence()
            if self.ticks % rate == 0 and self.held:
                out += self.silence()
                notes = self.arp_notes()
                if self.s["arp"] == "random":
                    import random
                    channel, note, velocity = random.choice(notes)
                else:
                    channel, note, velocity = notes[self.step % len(notes)]
                self.step += 1
                mapped = self.note(channel, note)
                if mapped:
                    self.sounding = mapped
                    out.append(bytes([0x90 | mapped[0], mapped[1], self.velocity(velocity)]))
            self.ticks += 1
            return out

    def restart(self):
        """Start: the pattern from its first note, on the next tick"""
        with self.lock:
            self.ticks, self.step = 0, 0

    def arp_active(self):
        return self.s["on"] and self.s["arp_on"]


LIBRARY_SYSEX = (bytes([0xF0, 0x7D, 0x46, 0x4C]),   # SLOOP's editor protocol (the box's library)
                 bytes([0xF0, 0x00, 0x59]),           # firmware update frames
                 bytes([0xF0, 0x22, 0x24, 0x35]),     # update start
                 bytes([0xF0, 0x00, 0x32, 0x45]))     # update handshake


def is_library_sysex(message):
    """the FM-1's answers to the library and the updater: not for the Bluetooth MIDI device"""
    return message[:1] == b"\xf0" and message.startswith(LIBRARY_SYSEX)


TIMING_LOG = "/dev/shm/fm1-midi-timing.log"     # RAM only; for measuring Bluetooth timing


def log_timing(packet, arrived):
    """One line per received packet: arrival (ms), the sender's 13-bit timestamp, the bytes.
    Arrival minus sender time, unwrapped, shows how unevenly the radio delivers notes."""
    if len(packet) < 2 or not packet[1] & 0x80:
        return
    sent = ((packet[0] & 0x3F) << 7) | (packet[1] & 0x7F)
    try:
        with open(TIMING_LOG, "a") as f:
            if f.tell() > 512_000:
                f.truncate(0)
            f.write(f"{arrived * 1000:.1f} {sent} {packet.hex()}\n")
    except OSError:
        pass


# ---------------------------------------------------------------- the Companion between the two

class MidiBridge:
    """Joins the FM-1's USB MIDI and the BLE MIDI service. Status for the screen:
    usb_label(), peer, enabled, pairing_until, activity()."""

    def __init__(self, source_match, enabled=True, net=False, pads=None):
        self.enabled, self.paused = enabled, False
        self.pads, self.pads_lock = pads, threading.Lock()    # the sampler's pipe (the Studio), notes for its pads
        self.net = self.mcu = None            # network MIDI (the desk box): music, and a Mackie Control surface
        if net:
            import netmidi
            self.net = netmidi.Session("FM-1 Companion", 5004, self.from_net)
            self.mcu = netmidi.Session("FM-1 Companion MCU", 5006, self.from_mcu)
            self.mackie = netmidi.Mackie()
        self.peers = {}                     # device path -> name: what's connected to the box (phones, iPads, Macs)
        self.keyboards = {}                 # device path -> name: keyboards the box connected to (as the central)
        self.addresses = {}                 # their device path -> address
        self.ble_saved = []                 # [[address, name]]: keyboards to connect to whenever they're on
        self.ble_loaded = False             # the app has sent them (till then the status leaves them out)
        self.ble_found, self.ble_scanning = [], False    # the last keyboard scan's [[address, name]]
        self.ble_note = [0, None]           # [count, text]: what the screen says about a keyboard (counted: said once)
        self.name_timer = False
        self.pairing_until = 0.0
        self.last_ble = 0.0
        self.bluez = None                   # filled in by start_bluez's thread
        self.error = None
        self.pending, self.flush_queued = [], False
        self.lock = threading.Lock()
        self.usb = UsbMidi(source_match, self.from_usb)
        self.usb_b = UsbMidi(source_match, lambda message: self.from_fm1("FM-1 B", message), slot=1)
        self.controllers = UsbControllers(self.usb, self.from_controllers)
        self.split = bool(net)                # the Studio: each USB MIDI device its own row and column
        if net:                               # the Studio: four USB ports, more on a hub (the Pocket: 4, its CPU)
            self.controllers.MAX = UsbControllers.MAX_STUDIO
        self.streams = {}                   # device path -> MidiStream: each sender's running status its own
        self.clock_mode, self.bpm, self.playing = "follow", 120.0, False     # "follow" or "box"
        self.box_count, self.box_bar = 0, None      # the box clock's ticks since Start, its bar's start
        self.box_origin = None                      # when the box clock's tick 0 (after Start) was due
        self.watch = {source: ClockWatch() for source in SOURCES if source != "Box"}
        self.routes = {key: Route(route_default(key)) for key in ROUTES}
        self.saved = {}                       # the routes as the app last sent them (a USB device's, made on use)
        self.held, self.chan_seen = {}, [0.0] * 16      # for the MIDI meter: notes down, channel traffic
        self.tap_path, self.tap_fd = None, None
        self.midi_log, self.source_names = None, {}   # MIDI recording (start_midi_log); a USB key's name by key     # SLOOP on the Studio (deskui.start_sloop): FM-1 A's MIDI, its FIFO

    def set_routes(self, routes):
        self.saved = dict(routes or {})
        for key, route in self.routes.items():
            self.deliver(key, route.update(dict(route_default(key), **(self.saved.get(key) or {}))))

    def route(self, key):
        """the route key, made the first time a USB device's is used (from its saved settings)"""
        r = self.routes.get(key)
        if r is None:
            r = self.routes[key] = Route(dict(route_default(key), **(self.saved.get(key) or {})))
        return r

    def dests(self):
        return matrix(self.controllers.names() if self.split else None)[1]

    def deliver(self, key, messages):
        """messages out of a route, to its destination"""
        if not messages:
            return
        dest = key.split(">")[1]
        if dest in FM1S:                       # BLE MIDI off stops Bluetooth only; a flash pauses everything
            if not self.paused and (self.enabled or not key.startswith("BT>")):
                (self.usb if dest == "FM-1" else self.usb_b).send_messages(messages)
                for m in messages:
                    self.note_watch(m, time.monotonic())
        elif dest == "USB":
            self.controllers.send_messages(messages)
        elif dest.startswith(DEVICE):         # one USB device (the Studio)
            self.controllers.send_to(dest[len(DEVICE):], messages)
        elif dest == "NET":
            if self.net:
                self.net.send(messages)
        elif dest == "SMP":
            if self.pads is not None:
                with self.pads_lock:
                    try:
                        self.pads.send(("midi", [list(m) for m in messages]))
                    except (BrokenPipeError, OSError):
                        pass
        else:
            for m in messages:
                self.to_ble(m)

    def arp_tick(self):
        """a clock tick for the arpeggiators"""
        for key, route in self.routes.items():
            if route.arp_active():
                self.deliver(key, route.tick())

    def arp_restart(self):
        for route in self.routes.values():
            route.restart()

    def external_clock(self):
        now = time.monotonic()
        return any(watch.bpm(now) for watch in self.watch.values())

    def start(self):
        def body():
            try:
                start_bluez(self)
            except Exception as e:          # no BlueZ or no D-Bus: the audio side keeps working
                self.error = str(e)[:40]

        threading.Thread(target=body, daemon=True).start()
        threading.Thread(target=self.clock_loop, daemon=True).start()
        if self.pads is not None:
            threading.Thread(target=self.grid_loop, daemon=True).start()
        for session in (self.net, self.mcu):
            if session:
                session.start()

    # ---- clock: watch incoming clock; as clock master, send our own instead

    def clock_loop(self):
        """24 ticks a quarter note while the box is the clock master. Each tick is due at a fixed time
        (not "sleep one interval"), so the tempo doesn't drift with how long sending takes. Measured on a
        Zero W streaming to a speaker: the tempo is exact on average, single ticks ~3 ms early or late
        (the Bluetooth UART's interrupts come first, even before a real-time thread)."""
        make_realtime()
        due = time.monotonic()
        while True:
            box = self.clock_mode == "box"
            # no clock to follow but an arp to play: ticks of our own at the box's tempo, not sent anywhere
            own = not box and any(r.arp_active() for r in self.routes.values()) and not self.external_clock()
            if not (box or own):
                time.sleep(0.05)
                due = time.monotonic()
                continue
            now = time.monotonic()
            if due > now:
                time.sleep(due - now)
            if box:
                if self.box_count == 0:
                    self.box_origin = due
                if self.box_count % 96 == 0:
                    self.box_bar = due
                self.box_count += 1
                self.send_all(bytes([CLOCK]))
            self.arp_tick()
            due += 60.0 / (self.bpm * 24)
            if time.monotonic() - due > 0.1:  # far behind (the CPU was busy): start afresh
                due = time.monotonic()

    def grid(self, now):
        """(seconds a clock tick, when tick 0 after Start was, playing) of the clock the box goes by: its own
        or the one it follows (the line fitted through its ticks); (seconds at the box's tempo, None, False)
        without one"""
        if self.clock_mode == "box":
            return 60.0 / (self.bpm * 24), self.box_origin, bool(self.playing and self.box_origin)
        for watch in self.watch.values():
            f = watch.fit(now)
            if f:
                return f[0], f[1], watch.playing
        return 60.0 / (self.bpm * 24), None, False

    def grid_loop(self):
        """the beat grid to the sampler (its sequencer plays on it): when it starts or stops at once, else
        every half second while it plays (a followed clock's fitted line moves a little)"""
        sent, sent_at = None, 0.0
        while True:
            now = time.monotonic()
            grid = self.grid(now)
            if (sent is None or grid[2] != sent[2] or (grid[1] is None) != (sent[1] is None)
                    or (grid[2] and now - sent_at >= 0.5)):
                with self.pads_lock:
                    try:
                        self.pads.send(("grid",) + tuple(grid))
                    except (BrokenPipeError, OSError):
                        return
                sent, sent_at = grid, now
            time.sleep(0.02)

    def transport(self, command):
        """Start or Stop to the FM-1 and Bluetooth"""
        self.playing = command == "start"
        if self.playing:
            self.box_count, self.box_origin = 0, None    # (the next tick is tick 0: the grid starts there)
            self.arp_restart()
        self.send_all(bytes([START if self.playing else STOP]))

    def send_all(self, message):
        """the box's own clock and Start/Stop, where the matrix's Box routes are on"""
        for dest in self.dests():
            if self.route(f"Box>{dest}").s["on"]:
                self.deliver(f"Box>{dest}", [message])

    def clock_status(self, now):
        """{"bpm", "source", "playing"} for the screen, or None"""
        if self.clock_mode == "box":
            return {"bpm": round(self.bpm), "tempo": self.bpm, "source": "box", "playing": self.playing,
                    "bar": self.box_bar}
        for source, watch in self.watch.items():
            bpm = watch.bpm(now)
            if bpm:
                return {"bpm": round(bpm), "tempo": round(bpm, 2), "source": source, "playing": watch.playing,
                        "bar": round(watch.bar(now), 3)}
        return None

    def note_watch(self, message, now):
        """notes played to and from the FM-1, and when each channel last carried anything"""
        status = message[0] if message else 0xF0
        if status >= 0xF0:
            return
        channel, kind = status & 0x0F, status & 0xF0
        self.chan_seen[channel] = now
        if kind in (0x80, 0x90) and len(message) == 3:
            if kind == 0x90 and message[2]:
                self.held[(channel, message[1])] = now
            else:
                self.held.pop((channel, message[1]), None)

    def notes_status(self, now):
        """(sorted notes held, bit mask of channels busy in the last 0.3 s); a note held over 30 s with no
        note-off seen is forgotten"""
        for key in [k for k, t in self.held.items() if now - t > 30]:
            del self.held[key]
        chans = sum(1 << ch for ch, t in enumerate(self.chan_seen) if now - t < 0.3)
        return sorted({note for _, note in self.held})[:24], chans

    def passes(self, source, message):
        """Looks at clock on the way; as clock master, keeps other clock and transport to itself."""
        if message and message[0] in TRANSPORT:
            self.watch[generic(source)].message(message[0], time.monotonic())
            if self.clock_mode != "box":      # following: the arps step with the incoming clock
                if message[0] == CLOCK:
                    self.arp_tick()
                elif message[0] == START:
                    self.arp_restart()
            return self.clock_mode != "box"
        return True

    # USB -> BLE: queue, then send from the GLib thread in as few packets as possible
    def from_usb(self, message):
        self.from_fm1("FM-1", message)

    def from_fm1(self, source, message):
        """from FM-1 A or B (source), on rtmidi's thread"""
        if source == "FM-1" and self.tap_path and message and message[0] < 0xF8:
            self.tap(message)                 # (not FM-1 A's clock: the apps follow each other's, never its)
        if is_library_sysex(message) or not self.passes(source, message):
            return
        self.note_watch(message, time.monotonic())
        self.route_from(source, message)

    def tap(self, message):
        """FM-1 A's MIDI, as it comes, into SLOOP's FIFO (sloop-remote-out reads its REMOTE OUT channel from it). The
        FIFO opens once SLOOP has its end open; a message it can't take is dropped, never waited for"""
        import os
        if self.tap_fd is None:
            try:
                self.tap_fd = os.open(self.tap_path, os.O_WRONLY | os.O_NONBLOCK)
            except OSError:                   # (no reader yet: the next message tries again)
                return
        try:
            os.write(self.tap_fd, bytes(message))
        except BlockingIOError:
            pass
        except OSError:                       # SLOOP stopped
            self.set_tap(self.tap_path)

    def set_tap(self, path):
        import os
        if self.tap_fd is not None:
            try:
                os.close(self.tap_fd)
            except OSError:
                pass
        self.tap_path, self.tap_fd = path, None

    def route_from(self, source, message):
        if self.midi_log is not None:
            self.log_midi(source, message)
        for dest in self.dests():
            if dest != source:
                key = f"{source}>{dest}"
                self.deliver(key, self.route(key).apply_all(message))

    # network MIDI: a DAW's notes and clock (the routes' NET), and what it shows on the control surface
    def from_net(self, message):
        if not self.passes("NET", message):
            return
        self.route_from("NET", message)

    def from_mcu(self, message):
        replies = self.mackie.feed(message)
        if replies:                           # the handshake some DAWs make before they use a surface
            self.mcu.send(replies)

    def net_status(self):
        """{"net": computers on the music session, "mcu": the control surface's state, or None}"""
        if not self.net:
            return {}
        mcu = self.mackie.state() if self.mcu.names() else None
        return {"net": self.net.names(), "mcu": mcu, "net_error": self.net.error}

    # ---- MIDI recording: what's played in, while the recorder records, kept for a .mid beside the take

    def start_midi_log(self):
        self.midi_log = []

    def stop_midi_log(self):
        """-> the log ([(time, source, message)]), the logging stopped"""
        log, self.midi_log = self.midi_log or [], None
        return log

    def log_midi(self, source, message):
        """one message routed from source, its time taken now. Left out: clock and transport (the file has
        the tempo), SysEx, and an FM-1's channel 16 (its REMOTE OUT: its panel driving SLOOP or X0X)"""
        if not message or message[0] >= 0xF0:
            return
        if source in ("FM-1", "FM-1 B") and message[0] & 0x0F == 15:
            return
        log = self.midi_log
        if log is not None and len(log) < MIDI_LOG_MAX:
            log.append((time.monotonic(), source, bytes(message)))

    def source_label(self, source):
        """a track's name: FM-1 A, FM-1 B, a USB keyboard's own name, Bluetooth MIDI, Network MIDI"""
        if source == "FM-1":
            return "FM-1 A" if self.usb_b.label() else "FM-1"
        return {"FM-1 B": "FM-1 B", "BT": "Bluetooth MIDI", "NET": "Network MIDI",
                "USB": "USB keys"}.get(source) or self.source_names.get(source) or source

    # USB controllers -> the FM-1 (and Bluetooth, if that route is on); called on rtmidi's thread
    def from_controllers(self, message, name=None):
        """name: the controller it came from (the Studio routes each on its own)"""
        source = device_key(name) if self.split and name else "USB"
        if name and source != "USB":
            self.source_names[source] = name
        if is_library_sysex(message) or not self.passes(source, message):
            return
        self.route_from(source, message)

    def to_ble(self, message):
        if not (self.bluez and self.enabled and (self.peers or self.keyboards)):
            return
        with self.lock:
            self.pending.append(message)
            if self.flush_queued:
                return
            self.flush_queued = True
        self.bluez["idle_add"](self.flush)

    def flush(self):
        with self.lock:
            messages, self.pending, self.flush_queued = self.pending, [], False
        for packet in encode(messages, int(time.monotonic() * 1000)):
            if self.peers:
                self.bluez["notify"](packet)  # to every central that subscribed
            for path in list(self.keyboards):
                self.bluez["write"](path, packet)
        self.last_ble = time.monotonic()
        return False

    # BLE -> USB (called on the GLib thread): from a central's writes, or a keyboard's notifications
    def from_ble(self, packet, device_path):
        path = str(device_path) if device_path else None
        stream = self.streams.get(path)
        if stream is None:
            stream = self.streams[path] = MidiStream()
            if path and path not in self.peers and path not in self.keyboards and self.bluez:
                self.bluez["idle_add"](self.find_names)       # after replying to bluetoothd
        self.last_ble = time.monotonic()
        for m in stream.feed(strip_timestamps(packet)):
            if self.passes("BT", m):
                self.route_from("BT", m)
        log_timing(packet, self.last_ble)

    @property
    def peer(self):
        """the Bluetooth MIDI devices connected, for the screen ("iPad + microKEY"), or None"""
        names = list(self.keyboards.values()) + [n for p, n in self.peers.items() if p not in self.keyboards]
        return " + ".join(n or "connected" for n in names) or None

    def refresh_peers(self):
        """The centrals connected: every connected device but the headphones and the keyboards (linked, or saved
        and on the way). True while BlueZ still only has an address for one: a name is read a few seconds after
        it connects, so the first look often gets 28-9E-F6-…"""
        if not self.bluez:
            return False
        saved = {a.upper() for a, _ in self.ble_saved}
        self.peers = {path: name for path, name, address in self.bluez["connected_peers"]()
                      if path not in self.keyboards and address.upper() not in saved}
        return any(ADDRESS.fullmatch(n) for n in self.peers.values())

    def find_names(self):
        """something connected or left: look again, and every 3 s while a name is still an address"""
        if self.refresh_peers() and not self.name_timer and "timeout_add_seconds" in self.bluez:
            self.name_timer = True
            self.bluez["timeout_add_seconds"](3, self.name_tick)
        return False

    def name_tick(self):
        self.name_timer = self.refresh_peers()
        return self.name_timer

    # keyboards (the box as the central), called on the GLib thread
    def keyboard_linked(self, path, address, name):
        self.keyboards[path] = name
        self.addresses[path] = address
        self.peers.pop(path, None)
        saved = [s for s in self.ble_saved if s[0].upper() != address.upper()]
        self.ble_saved = ([[address, name]] + saved)[:MAX_KEYBOARDS]
        self.note(f"{name} connected")

    def keyboard_gone(self, path):
        name = self.keyboards.pop(path, None)
        self.addresses.pop(path, None)
        self.streams.pop(path, None)
        if name:
            self.note(f"{name} left")

    def note(self, text):
        self.ble_note = [self.ble_note[0] + 1, text]

    def keyboard_list(self):
        """the saved keyboards for the screen: [[address, name, linked]]"""
        linked = {a.upper() for a in self.addresses.values()}
        return [[a, n, a.upper() in linked] for a, n in self.ble_saved]

    def keyboard_command(self, name, *args):
        """("scan",), ("connect", address), ("forget", address): from the app, done on the GLib thread"""
        if self.bluez:
            self.bluez["idle_add"](lambda: (self.bluez[name](*args), False)[1])
        elif name != "forget":
            self.note("Bluetooth not ready")

    # from the app's threads
    def poll(self):
        self.usb.poll()
        self.usb_b.poll()
        self.controllers.poll()

    def usb_label(self):
        return self.usb.label()

    def activity(self):
        return max(self.last_ble, self.usb.last_activity, self.usb_b.last_activity, self.controllers.last_activity)

    def set_enabled(self, on):
        self.enabled = on
        if self.bluez:
            self.bluez["idle_add"](lambda: (self.bluez["set_advertising"](on), self.bluez["set_central"](on),
                                            False)[2])

    def open_pairing(self):
        self.pairing_until = time.monotonic() + PAIRING_SECONDS
        if self.bluez:
            self.bluez["idle_add"](lambda: (self.bluez["open_pairing"](), False)[1])


# ---------------------------------------------------------------- in a process of its own

def run_child(conn, source_match, enabled, net=False, pads=None):
    """The MIDI process: MidiBridge, sending its status up the pipe when it changes and taking
    ("enabled", bool) and ("pair",) commands. Exits when the app's end of the pipe closes."""
    import os
    import metronome
    bridge = MidiBridge(source_match, enabled, net, pads)
    bridge.start()
    metro = metronome.Metronome(lambda: bridge.clock_status(time.monotonic()), on_start=make_realtime)
    wanted = [False, None, "mid", 48000]    # the metronome: on, the speaker, the click's level, the rate

    def commands():
        while True:
            try:
                command = conn.recv()
            except (EOFError, OSError):
                os._exit(0)
            if command[0] == "enabled":
                bridge.set_enabled(command[1])
            elif command[0] == "pair":
                bridge.open_pairing()
            elif command[0] == "pause":            # no Bluetooth notes into the FM-1 while it's flashed
                bridge.paused = command[1]
            elif command[0] == "clock":            # ("clock", "follow" or "box", bpm)
                bridge.clock_mode, bridge.bpm = command[1], float(command[2])
            elif command[0] == "transport":        # ("transport", "start" or "stop")
                bridge.transport(command[1])
            elif command[0] == "routes":           # ("routes", {route key: settings})
                bridge.set_routes(command[1])
            elif command[0] == "metronome":        # ("metronome", on, speaker, level, rate)
                wanted[:] = command[1:5]
            elif command[0] == "mcu" and bridge.mcu:   # ("mcu", [messages]): the control surface, to the DAW
                bridge.mcu.send([bytes(m) for m in command[1]])
            elif command[0] == "ble_saved":        # ("ble_saved", [[address, name]]): the keyboards, at start
                bridge.ble_saved = [[str(a), str(n)] for a, n in command[1]][:MAX_KEYBOARDS]
                bridge.ble_loaded = True
            elif command[0] == "ble":              # ("ble", "scan") / ("ble", "connect" or "forget", address)
                bridge.keyboard_command(*command[1:])
            elif command[0] == "tap":              # ("tap", FIFO path or None): FM-1 A's MIDI to SLOOP on the Studio
                bridge.set_tap(command[1])
            elif command[0] == "midirec":          # ("midirec", True): log what's played in; (.., False): stop
                if command[1]:
                    bridge.start_midi_log()
                else:
                    held_log[:] = bridge.stop_midi_log()
            elif command[0] == "midiwrite":        # ("midiwrite", .mid path, the audio's start, BPM): the log
                write_midi(held_log, command[1], float(command[2]), float(command[3]), bridge.source_label)
                held_log[:] = []

    held_log = []                              # the last take's MIDI, until its .mid is written
    threading.Thread(target=commands, daemon=True).start()
    last, next_poll = None, 0.0
    while True:
        now = time.monotonic()
        if now >= next_poll:
            bridge.poll()
            next_poll = now + 3                # a USB controller plugged in shows up within 3 s
        metro.ensure(*wanted)                  # starts, stops, or restarts it if its stream ended
        status = {"peer": bridge.peer, "error": bridge.error, "usb": bridge.usb_label(),
                  "controllers": bridge.controllers.names(), "usb_b": bridge.usb_b.label(),
                  "activity": round(bridge.activity(), 1),  # 0.1 s steps: at most ~5 updates a second
                  "clock": bridge.clock_status(now)}
        status["notes"], status["chans"] = bridge.notes_status(now)
        status.update(bridge.net_status())
        status["pads"] = bridge.pads is not None
        status["split"] = bridge.split
        status.update(ble_keys=bridge.keyboard_list() if bridge.ble_loaded else None, ble_found=bridge.ble_found,
                      ble_scanning=bridge.ble_scanning, ble_note=bridge.ble_note)
        if status != last:
            try:
                conn.send(status)
            except (BrokenPipeError, OSError):
                os._exit(0)
            last = status
        time.sleep(0.2)


MIDI_LOG_MAX = 200000                          # (a take's messages: ~6 MB at most, then the rest left out)
PPQ = 480                                      # the .mid's ticks a beat


def write_midi(log, path, audio_start, bpm, label=str):
    """a Standard MIDI File (type 1) of log ([(time.monotonic(), source, message bytes)]): a track a source,
    named after it; time 0 is audio_start (the WAV's first frame), so the notes line up with the take in a DAW;
    one tempo (bpm). A message before 0 lands on 0; a note still held at the end is let go there."""
    import mido
    bpm = bpm if 20 <= bpm <= 400 else 120.0
    mid = mido.MidiFile(type=1, ticks_per_beat=PPQ)
    head = mido.MidiTrack()
    head.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    head.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    mid.tracks.append(head)
    by_source = {}
    for t, source, msg in log:
        by_source.setdefault(source, []).append((max(0.0, t - audio_start), msg))
    for source, events in by_source.items():
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name=str(label(source))[:60], time=0))
        last, held = 0, set()
        end = 0
        for when, msg in sorted(events, key=lambda e: e[0]):
            try:
                m = mido.Message.from_bytes(list(msg))
            except (ValueError, TypeError):
                continue
            tick = int(round(when * bpm / 60.0 * PPQ))
            track.append(m.copy(time=tick - last))
            last = end = tick
            if m.type == "note_on" and m.velocity:
                held.add((m.channel, m.note))
            elif m.type in ("note_off", "note_on"):
                held.discard((m.channel, m.note))
        for channel, note in sorted(held):    # let go at the end: no note hangs in a DAW
            track.append(mido.Message("note_off", channel=channel, note=note, velocity=0, time=end - last))
            last = end
        mid.tracks.append(track)
    if len(mid.tracks) > 1:                   # (nothing played: no file)
        mid.save(str(path))
        return True
    return False


class MidiProcess:
    """MidiBridge in a child process, with the same interface for the app. A Python process runs
    one thread at a time, and drawing a screen frame takes ~75 ms on a Zero W: in the app's process
    that held notes back, unevenly. In its own process the kernel switches to it as a note arrives."""

    def __init__(self, source_match, enabled=True, net=False, pads=None):
        import multiprocessing
        ctx = multiprocessing.get_context("fork")
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=run_child, args=(child, source_match, enabled, net, pads), daemon=True,
                                name="fm1-midi")
        self.pads = pads is not None          # the Studio's sampler takes notes (the routes' SMP)
        self.net, self.mcu = [], None        # network MIDI: computers connected; the control surface's state
        self.enabled, self.peer, self.error = enabled, None, None
        self.pairing_until = 0.0
        self.usb, self.last_activity = None, 0.0
        self.controllers = []               # USB MIDI controllers' names
        self.usb_b = None                   # a second FM-1's port name, when there is one
        self.clock = None                   # {"bpm", "source", "playing"} while there's a clock
        self.notes, self.chans = [], 0      # for the MIDI meter
        self.ble_keys, self.ble_found, self.ble_scanning = [], [], False   # Bluetooth MIDI keyboards (MidiBridge's)
        self.ble_note = 0
        self.on_note = self.on_saved = None  # the app's: a keyboard's news to say; the saved keyboards to keep

    def start(self):
        self.proc.start()
        threading.Thread(target=self.receive, daemon=True).start()

    def receive(self):
        while True:
            try:
                status = self.conn.recv()
            except (EOFError, OSError):
                self.error = "MIDI process stopped"
                return
            self.peer, self.error = status["peer"], status["error"]
            self.usb, self.last_activity = status["usb"], status["activity"]
            self.controllers = status.get("controllers") or []
            self.split = status.get("split", False)
            self.usb_b = status.get("usb_b")
            self.clock = status.get("clock")
            self.notes, self.chans = status.get("notes") or [], status.get("chans", 0)
            self.net, self.mcu = status.get("net") or [], status.get("mcu")
            self.ble_found, self.ble_scanning = status.get("ble_found") or [], status.get("ble_scanning", False)
            keys = status.get("ble_keys")
            if keys is not None:              # None: the saved ones not sent yet (not "none saved")
                if [k[:2] for k in keys] != [k[:2] for k in self.ble_keys] and self.on_saved:
                    self.on_saved([k[:2] for k in keys])
                self.ble_keys = keys
            count, text = status.get("ble_note") or (0, None)
            if count != self.ble_note and text and self.on_note:
                self.on_note(text)
            self.ble_note = count

    def poll(self):
        pass                                # the MIDI process watches the USB side itself

    def midi_record(self, on):
        """the MIDI played in logged while a take records (on), or stopped (kept for midi_write)"""
        self.send_command(("midirec", bool(on)))

    def midi_write(self, path, audio_start, bpm):
        """the take's MIDI as a .mid at path, its time 0 the audio's first frame (a time.monotonic())"""
        self.send_command(("midiwrite", str(path), float(audio_start), float(bpm)))

    def send_command(self, command):
        try:
            self.conn.send(command)
        except (BrokenPipeError, OSError):
            pass

    def usb_label(self):
        return self.usb

    def activity(self):
        return self.last_activity           # CLOCK_MONOTONIC is shared by both processes

    def set_enabled(self, on):
        self.enabled = on
        self.conn.send(("enabled", on))

    def open_pairing(self):
        self.pairing_until = time.monotonic() + PAIRING_SECONDS
        self.conn.send(("pair",))

    def pause(self, on):
        self.conn.send(("pause", on))

    def set_clock(self, mode, bpm):
        self.conn.send(("clock", mode, bpm))

    def transport(self, command):
        self.conn.send(("transport", command))

    def set_routes(self, routes):
        self.conn.send(("routes", routes))

    def set_metronome(self, on, target, level, rate):
        self.conn.send(("metronome", on, target, level, rate))

    def set_tap(self, path):
        """FM-1 A's MIDI also into the FIFO at path (SLOOP on the Studio, deskui.start_sloop); None: not"""
        self.conn.send(("tap", path))

    def set_ble_saved(self, keys):
        """the saved keyboards (the app's state), to connect to whenever they're on"""
        self.ble_keys = [list(k[:2]) + [False] for k in keys or []]
        self.conn.send(("ble_saved", [list(k[:2]) for k in keys or []]))

    def ble_scan(self):
        self.ble_scanning = True              # (till the MIDI process says otherwise: no "none found" first)
        self.conn.send(("ble", "scan"))

    def ble_connect(self, address):
        self.conn.send(("ble", "connect", address))

    def ble_forget(self, address):
        self.ble_keys = [k for k in self.ble_keys if k[0] != address]
        self.conn.send(("ble", "forget", address))

    def mcu_send(self, messages):
        """the control surface's moves (netmidi.Mackie.fader / press) to the DAW"""
        self.conn.send(("mcu", [list(m) for m in messages]))
