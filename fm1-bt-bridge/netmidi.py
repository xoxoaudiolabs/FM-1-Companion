"""Network MIDI (RTP-MIDI, as Apple's "Network MIDI" and the rtpMIDI driver on Windows speak it): the box as a
MIDI port a computer reaches over Wi-Fi or Ethernet, for a DAW such as Kraken. Lower latency than Bluetooth MIDI,
and as many ports as there are sessions: one for music (the MIDI routes' NET), one for a control surface (the
desk box's KRAKEN tab, Mackie Control).

The computer starts a session (it sends IN on our control port, then on the data port, the port after it); we
accept, answer its clock sync (CK) and swap MIDI in RTP packets on the data port. The Studio never starts one
itself, so a computer chooses it from its network MIDI directory, where avahi lists it (config/fm1-midi.service).

The Pocket's Studio link (Invitation) is the other side: the Pocket finds a Studio's music session on the network
(find_studios: DNS-SD, _apple-midi._udp, as a computer does) and starts a session to it as a computer would, so the
Studio needs nothing new: the Pocket is one more NET peer to it, the Studio one NET to the Pocket. Over one cable
with no router, each box needs an IPv4 link-local address (install.sh switches it on for the wired connection).

Only what a session needs is here: no recovery journal (packets on a local network rarely go missing, and a lost
one is a missed note, as over Bluetooth). Standard library only.
"""

import random
import select
import socket
import struct
import threading
import time

SIGN = b"\xff\xff"
VERSION = 2


def now_100us():
    """the session clock: 100 microsecond units"""
    return int(time.monotonic() * 10000)


def encode(messages, seq, ssrc, timestamp=None):
    """complete MIDI messages -> one RTP-MIDI packet (no journal, no delta time before the first message, 0 after
    each); None if there's nothing to send"""
    body = bytearray()
    for i, m in enumerate(messages):
        if i:
            body.append(0)                    # delta time 0
        body += m
    if not body:
        return None
    if len(body) <= 15:
        head = bytes([len(body)])
    else:
        head = bytes([0x80 | (len(body) >> 8) & 0x0F, len(body) & 0xFF])
    ts = (now_100us() if timestamp is None else timestamp) & 0xFFFFFFFF
    return struct.pack(">BBHII", 0x80, 0x61, seq & 0xFFFF, ts, ssrc) + head + bytes(body)


def decode(packet):
    """an RTP-MIDI packet -> its MIDI messages (bytes each); [] for anything else. Running status and delta times
    handled; the recovery journal (after the commands) skipped"""
    if len(packet) < 13 or packet[0] & 0xC0 != 0x80 or packet[1] & 0x7F != 0x61:
        return []
    i = 12
    flags = packet[i]
    length = flags & 0x0F
    i += 1
    if flags & 0x80:
        if i >= len(packet):
            return []
        length = (length << 8) | packet[i]
        i += 1
    data = packet[i:i + length]
    out, k, status, first = [], 0, None, True

    def delta(k):
        while k < len(data) and data[k] & 0x80:
            k += 1
        return k + 1

    while k < len(data):
        if not first or flags & 0x20:
            k = delta(k)
            if k >= len(data):
                break
        first = False
        if data[k] == 0xF0:                   # SysEx, to its end (F7), or to the end of a split one (F0 / F4)
            end = k + 1
            while end < len(data) and data[end] not in (0xF7, 0xF0, 0xF4):
                end += 1
            out.append(bytes(data[k:end]) + b"\xf7")
            k = end + 1
            continue
        if data[k] & 0x80:
            status = data[k]
            k += 1
        if status is None:
            break
        if status >= 0xF8:                    # real time: one byte, running status kept
            out.append(bytes([status]))
            continue
        size = 2 if (status & 0xF0) in (0xC0, 0xD0) or status in (0xF1, 0xF3) else 1 if status == 0xF6 else 3
        msg = bytes([status]) + bytes(data[k:k + size - 1])
        if len(msg) == size:
            out.append(msg)
        k += size - 1
        if status >= 0xF0:
            status = None                     # system common messages don't run
    return out


class Session:
    """One network MIDI port: the box answering on UDP port (control) and port + 1 (data). on_message(bytes) for
    each MIDI message from the computer, on this session's thread; send(messages) to every connected peer."""

    def __init__(self, name, port, on_message):
        self.name, self.port, self.on_message = name, port, on_message
        self.ssrc = random.getrandbits(32)
        self.seq = random.getrandbits(16)
        self.peers = {}                       # their SSRC -> {"name", "control", "data", "seen"}
        self.lock = threading.Lock()
        self.sock = self.dsock = None
        self.error = None

    def start(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.dsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            for s in (self.sock, self.dsock):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(("0.0.0.0", self.port))
            self.dsock.bind(("0.0.0.0", self.port + 1))
        except OSError as e:
            self.error = str(e)[:40]
            return False
        threading.Thread(target=self.run, daemon=True).start()
        return True

    def names(self):
        with self.lock:
            return sorted(p["name"] for p in self.peers.values() if p.get("data"))

    def run(self):
        while True:
            ready, _, _ = select.select([self.sock, self.dsock], [], [], 5.0)
            for s in ready:
                try:
                    packet, addr = s.recvfrom(2048)
                except OSError:
                    continue
                self.received(packet, addr, s is self.dsock)
            self.expire()

    def received(self, packet, addr, data_port):
        if packet[:2] == SIGN and len(packet) >= 4:
            self.command(packet[2:4], packet[4:], addr, data_port)
        elif data_port:
            for m in decode(packet):
                self.on_message(m)

    def command(self, cmd, body, addr, data_port):
        sock = self.dsock if data_port else self.sock
        if cmd == b"IN" and len(body) >= 12:                     # an invitation: accept it
            _, token, ssrc = struct.unpack(">III", body[:12])
            name = body[12:].split(b"\0")[0].decode("utf-8", "replace") or "computer"
            sock.sendto(SIGN + b"OK" + struct.pack(">III", VERSION, token, self.ssrc) + self.name.encode() + b"\0",
                        addr)
            with self.lock:
                peer = self.peers.setdefault(ssrc, {"name": name, "control": None, "data": None})
                peer["data" if data_port else "control"] = addr
                peer["seen"] = time.monotonic()
        elif cmd == b"CK" and len(body) >= 32:                   # clock sync: answer count 0 with count 1
            ssrc, count = struct.unpack(">IB", body[:5])
            stamps = list(struct.unpack(">QQQ", body[8:32]))
            with self.lock:
                if ssrc in self.peers:
                    self.peers[ssrc]["seen"] = time.monotonic()
            if count == 0:
                stamps[1] = now_100us()
                sock.sendto(SIGN + b"CK" + struct.pack(">IB3xQQQ", self.ssrc, 1, *stamps), addr)
        elif cmd == b"BY" and len(body) >= 12:                   # the computer ended the session
            _, _, ssrc = struct.unpack(">III", body[:12])
            with self.lock:
                self.peers.pop(ssrc, None)

    def expire(self):
        """a computer that went away without saying (sleep, Wi-Fi off): forgotten after 90 s without a sync
        (a session syncs at least every 10-60 s)"""
        now = time.monotonic()
        with self.lock:
            for ssrc in [k for k, p in self.peers.items() if now - p.get("seen", now) > 90]:
                del self.peers[ssrc]

    def send(self, messages):
        with self.lock:
            targets = [p["data"] for p in self.peers.values() if p.get("data")]
            if not targets:
                return
            self.seq = (self.seq + 1) & 0xFFFF
            packet = encode(messages, self.seq, self.ssrc)
        if packet:
            for addr in targets:
                try:
                    self.dsock.sendto(packet, addr)
                except OSError:
                    pass


# ---------------------------------------------------------------- the Pocket's Studio link

MDNS = ("224.0.0.251", 5353)
SERVICE = "_apple-midi._udp.local"
LINK_NAME = "FM-1 Companion Pocket"
ASK_AGAIN = 1.2                 # s: find_studios asks a network again that hasn't answered


def dns_name(packet, i):
    """a DNS name at i (compressed names followed) -> (name, the index after it)"""
    labels, end, jumps = [], None, 0
    while i < len(packet):
        n = packet[i]
        if n == 0:
            i += 1
            break
        if n & 0xC0 == 0xC0:
            if i + 1 >= len(packet) or jumps > 20:
                break
            end = i + 2 if end is None else end
            i, jumps = ((n & 0x3F) << 8) | packet[i + 1], jumps + 1
            continue
        labels.append(packet[i + 1:i + 1 + n].decode("utf-8", "replace"))
        i += 1 + n
    return ".".join(labels), (i if end is None else end)


def mdns_query(name, qtype=12):
    """a DNS query for name (12: PTR), asked from our own port: responders answer it to us (legacy unicast)"""
    q = b"".join(bytes([len(part)]) + part.encode() for part in name.split(".")) + b"\0"
    return struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0) + q + struct.pack(">HH", qtype, 1)


def mdns_records(packet):
    """a DNS reply -> [(name, type, data)]: PTR the instance name, SRV (port, target), A the address"""
    out = []
    try:
        _, _, qd, an, ns, ar = struct.unpack(">HHHHHH", packet[:12])
        i = 12
        for _ in range(qd):
            _, i = dns_name(packet, i)
            i += 4
        for _ in range(an + ns + ar):
            name, i = dns_name(packet, i)
            rtype, _, _, length = struct.unpack(">HHIH", packet[i:i + 10])
            i += 10
            data = packet[i:i + length]
            if rtype == 12:
                out.append((name, 12, dns_name(packet, i)[0]))
            elif rtype == 33 and length >= 6:
                out.append((name, 33, (struct.unpack(">H", data[4:6])[0], dns_name(packet, i + 6)[0])))
            elif rtype == 1 and length == 4:
                out.append((name, 1, socket.inet_ntoa(data)))
            i += length
    except (struct.error, IndexError):
        pass
    return out


def is_studio(instance):
    """a network MIDI session of a Studio's: the Companion Studio's music session ("FM-1 Companion on <its host>",
    config/fm1-midi.service), XOXO Studio's ("XOXO Studio on ..."), or any whose name says Studio; not a control
    surface's ("... MCU ...") nor a Pocket's"""
    name = instance.split("._apple-midi")[0]
    return ("MCU" not in name and "Pocket" not in name
            and (name.startswith("FM-1 Companion") or "Studio" in name))


def local_addresses():
    """this box's IPv4 addresses, one a network (Wi-Fi, the cable's link-local one), not loopback"""
    import re
    import subprocess
    try:
        out = subprocess.run(["ip", "-4", "-o", "addr", "show", "up"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [a for a in re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", out) if not a.startswith("127.")]


def studios_in(records):
    """[(instance name, address, control port)] of the Studios in one network's DNS-SD answers"""
    srv = {n: v for n, t, v in records if t == 33}
    addresses = {n: v for n, t, v in records if t == 1}
    found = []
    for _, t, instance in records:
        if t == 12 and is_studio(instance) and instance in srv:
            port, target = srv[instance]
            address = addresses.get(target)
            if address is None:
                try:
                    address = socket.gethostbyname(target)
                except OSError:
                    continue
            entry = (instance.split("._apple-midi")[0], address, port)
            if entry not in found:
                found.append(entry)
    return found


def find_studios(timeout=2.5, sock=None):
    """the Studios' music sessions on the network: [(instance name, address, control port)], by DNS-SD, asked
    on each network the box is on (a Studio answers each with its address there), one on a cable (link-local,
    169.254.x.x) first: no router or Wi-Fi in the way. A network with no answer yet is asked again after ASK_AGAIN s:
    a Studio answers the same question on a network only once a second or so (as mDNS responders do)"""
    socks = [sock] if sock else []
    if not sock:
        for address in local_addresses():
            try:
                one = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                one.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(address))
                one.bind((address, 0))
                socks.append(one)
            except OSError:
                pass
        socks = socks or [socket.socket(socket.AF_INET, socket.SOCK_DGRAM)]
    records = {id(one): [] for one in socks}

    def ask(which):
        for one in which:
            try:
                one.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
                one.sendto(mdns_query(SERVICE), MDNS)
            except OSError:
                pass

    try:
        ask(socks)
        start = time.monotonic()
        end, again = start + timeout, start + ASK_AGAIN
        while (left := end - time.monotonic()) > 0:
            if again and time.monotonic() >= again:
                ask([one for one in socks if not records[id(one)]])
                again = None
            ready, _, _ = select.select(socks, [], [], min(left, again - time.monotonic()) if again else left)
            if not ready:
                if again:
                    continue
                break
            for one in ready:
                try:
                    records[id(one)] += mdns_records(one.recv(4096))
                except OSError:
                    pass
    except (OSError, ValueError):
        return []
    finally:
        if not sock:
            for one in socks:
                one.close()
    found = []
    for one in socks:
        found += [entry for entry in studios_in(records[id(one)]) if entry not in found]
    return sorted(found, key=lambda entry: not entry[1].startswith("169.254."))


class Invitation:
    """The Pocket's session to a Studio's music session (its Studio link): found by find_studios (or at host, a
    name or address), invited as a computer invites (IN on its control port, then its data port), kept with a clock
    sync (CK) every 10 s, started again when the Studio stops answering. The same calls as Session: on_message for
    each MIDI message from the Studio, send(messages), names() (the Studio's, while linked), error."""

    SYNC, LOST, RETRY, CABLE = 10.0, 30.0, 5.0, 30.0   # (CABLE: linked over Wi-Fi, look for it on a cable)

    def __init__(self, name, on_message, host=None, port=5004, find=find_studios):
        self.name, self.on_message, self.host, self.port, self.find = name, on_message, host, port, find
        self.ssrc, self.seq = random.getrandbits(32), random.getrandbits(16)
        self.lock = threading.Lock()
        self.peer = None                      # {"name", "control", "data", "ssrc"} while linked
        self.studio_ssrc = None               # the session id in the Studio's last OK (invite)
        self.error, self.running, self.heard = None, False, 0.0
        self.sock = self.dsock = None

    def start(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.dsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("0.0.0.0", 0))
            self.dsock.bind(("0.0.0.0", 0))
        except OSError as e:
            self.error = str(e)[:40]
            return False
        self.running = True
        threading.Thread(target=self.run, daemon=True).start()
        return True

    def stop(self):
        """the link ended: the Studio told (BY), the sockets closed"""
        self.running = False
        with self.lock:
            peer, self.peer = self.peer, None
        for sock, key in ((self.sock, "control"), (self.dsock, "data")):
            try:
                if peer:
                    sock.sendto(SIGN + b"BY" + struct.pack(">III", VERSION, 0, self.ssrc), peer[key])
                sock.close()
            except OSError:
                pass

    def names(self):
        with self.lock:
            return [self.peer["name"]] if self.peer else []

    def address(self):
        """the Studio's address while linked (for the link's audio: netaudio.py), or None"""
        with self.lock:
            return self.peer["control"][0] if self.peer else None

    def target(self):
        """(name, address, control port) of the Studio to link to, or None"""
        if self.host:
            try:
                return self.host, socket.gethostbyname(self.host), self.port
            except OSError:
                self.error = f"{self.host}: not found"[:40]
                return None
        found = self.find()
        if not found:
            self.error = "no Studio found"
        return found[0] if found else None

    def invite(self, sock, addr, timeout=1.5):
        """IN to addr from sock -> the Studio's name once it's said OK, or None"""
        token = random.getrandbits(32)
        sock.sendto(SIGN + b"IN" + struct.pack(">III", VERSION, token, self.ssrc) + self.name.encode() + b"\0", addr)
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            ready, _, _ = select.select([sock], [], [], left)
            if not ready:
                break
            packet, _ = sock.recvfrom(2048)
            if packet[:4] == SIGN + b"OK" and len(packet) >= 16 and struct.unpack(">I", packet[8:12])[0] == token:
                self.studio_ssrc = struct.unpack(">I", packet[12:16])[0]
                return packet[16:].split(b"\0")[0].decode("utf-8", "replace") or "Studio"
        return None

    def connect(self):
        found = self.target()
        if not found:
            return False
        name, address, port = found
        control, data = (address, port), (address, port + 1)
        try:
            studio = self.invite(self.sock, control) and self.invite(self.dsock, data)
        except OSError as e:
            self.error = str(e)[:40]
            return False
        if not studio:
            self.error = f"{name}: no answer"[:40]
            return False
        with self.lock:
            self.peer = {"name": studio, "control": control, "data": data, "ssrc": self.studio_ssrc}
        self.error, self.heard = None, time.monotonic()
        return True

    def sync(self):
        with self.lock:
            peer = self.peer
        if peer:
            self.dsock.sendto(SIGN + b"CK" + struct.pack(">IB3xQQQ", self.ssrc, 0, now_100us(), 0, 0), peer["data"])

    def to_cable(self):
        """linked over Wi-Fi (or a router) to a Studio that's on a cable too (it blinked, and the link came back
        the other way): True, the link ended so it's made again over the cable (find_studios puts it first)"""
        address = self.address()
        if self.host or not address or address.startswith("169.254."):
            return False
        name = self.names()[0] if self.names() else ""
        if not any(a.startswith("169.254.") and (n == name or n.startswith(name)) for n, a, _ in self.find()):
            return False
        with self.lock:
            peer, self.peer = self.peer, None
        for sock, key in ((self.sock, "control"), (self.dsock, "data")):
            try:
                sock.sendto(SIGN + b"BY" + struct.pack(">III", VERSION, 0, self.ssrc), peer[key])
            except (OSError, TypeError):
                pass
        return True

    def run(self):
        next_sync = 0.0
        next_cable = time.monotonic() + self.CABLE
        while self.running:
            if not self.peer:
                if not self.connect():
                    time.sleep(self.RETRY)
                    continue
                next_sync = 0.0
                next_cable = time.monotonic() + self.CABLE
            now = time.monotonic()
            if now >= next_cable:
                next_cable = now + self.CABLE
                if self.to_cable():
                    continue
            if now >= next_sync:
                try:
                    self.sync()
                except OSError:
                    pass
                next_sync = now + self.SYNC
            if now - self.heard > self.LOST:  # the Studio went away: find it and invite again
                with self.lock:
                    self.peer = None
                self.error = "Studio lost"
                continue
            try:
                ready, _, _ = select.select([self.sock, self.dsock], [], [], 1.0)
            except (OSError, ValueError):     # (closed by stop)
                return
            for sock in ready:
                try:
                    packet, _ = sock.recvfrom(2048)
                except OSError:
                    continue
                self.received(packet, sock is self.dsock)

    def received(self, packet, data_port):
        if packet[:2] == SIGN:
            if packet[2:4] == b"CK" and len(packet) >= 8 and self.restarted(struct.unpack(">I", packet[4:8])[0]):
                with self.lock:                   # the Studio started again: its session is a new one that doesn't
                    self.peer = None              # know this one (though it answers its syncs): invite again
                self.error = "Studio restarted"
            elif packet[2:4] in (b"CK", b"OK"):
                self.heard = time.monotonic()
            elif packet[2:4] == b"BY":            # the Studio ended it: find it and invite again
                with self.lock:
                    self.peer = None
        elif data_port:
            self.heard = time.monotonic()
            for m in decode(packet):
                self.on_message(m)

    def restarted(self, ssrc):
        """a sync answered by a session other than the one that accepted the invitation: the Studio restarted
        (its session answers anyone's syncs, so going quiet never shows it)"""
        with self.lock:
            known = self.peer and self.peer.get("ssrc")
        return bool(known) and ssrc != known

    def send(self, messages):
        with self.lock:
            peer = self.peer
            if not peer:
                return
            self.seq = (self.seq + 1) & 0xFFFF
            packet = encode(messages, self.seq, self.ssrc)
        if packet:
            try:
                self.dsock.sendto(packet, peer["data"])
            except OSError:
                pass


# ---------------------------------------------------------------- the control surface (Mackie Control)

MCU = bytes([0xF0, 0x00, 0x00, 0x66, 0x14])      # Mackie Control's SysEx header
SERIAL = b"FM1CMP1"                                # the surface's serial number (7 ASCII bytes), for the handshake


class Mackie:
    """What a DAW shows on a Mackie Control surface, kept from its messages, and what the surface sends: faders
    as pitch bend on channels 0-7 (master 8), buttons and LEDs as notes, the 2 x 56 character LCD and the
    handshake as SysEx, pan knobs (V-pots) as CC 16-23 out and their LED rings as CC 48-55 back, level meters as
    channel pressure. Kraken uses part of it; Ableton Live's MackieControl uses all of that."""

    BUTTONS = {"rewind": 0x5B, "forward": 0x5C, "stop": 0x5D, "play": 0x5E, "record": 0x5F, "loop": 0x56,
               "click": 0x59, "bank-": 0x2E, "bank+": 0x2F}
    TOUCH = 0x68                              # + strip: a finger on a fader (DAWs write automation while it's on)
    METER_STEP = 0.3                          # seconds a meter takes to fall one of its 12 steps (as the hardware)

    def __init__(self):
        self.faders = [0] * 9                 # 0..16383
        self.leds = {}                        # note -> on
        self.lcd = [" "] * 112
        self.rings = [0] * 8                  # the pan knobs' positions, 0 (off) .. 11
        self.meters = [(0, 0.0)] * 8          # (level 0..12, when it was set)
        self.seen = 0.0

    def feed(self, m, now=None):
        """a message from the DAW -> the messages to answer it with ([], but for the handshake)"""
        now = time.monotonic() if now is None else now
        self.seen = now
        if len(m) == 3 and m[0] & 0xF0 == 0xE0 and (m[0] & 15) < 9:
            self.faders[m[0] & 15] = m[1] | (m[2] << 7)
        elif len(m) == 3 and m[0] == 0x90:
            self.leds[m[1]] = m[2] > 0
        elif len(m) == 3 and m[0] == 0xB0 and 0x30 <= m[1] <= 0x37:
            self.rings[m[1] - 0x30] = m[2] & 0x0F
        elif len(m) == 2 and m[0] & 0xF0 == 0xD0:          # a meter: strip in the high 4 bits, level the low 4
            strip, level = m[1] >> 4, m[1] & 0x0F
            if strip < 8 and level <= 12:
                self.meters[strip] = (level, now)
        elif m[:5] == MCU and len(m) > 6:
            return self.sysex(m[5], m[6:-1])
        return []

    def sysex(self, cmd, data):
        if cmd == 0x12:                                    # the LCD: a position, then the characters
            pos = data[0] if data else 0
            for k, c in enumerate(data[1:]):
                if pos + k < 112:
                    self.lcd[pos + k] = chr(c) if 32 <= c < 127 else " "
        elif cmd == 0x00:                                  # device query: a surface is here (serial, challenge)
            return [MCU + b"\x01" + SERIAL + b"\x00\x00\x00\x00\xf7"]
        elif cmd == 0x02:                                  # the host's reply: connected
            return [MCU + b"\x03" + SERIAL + b"\xf7"]
        elif cmd == 0x13:                                  # version request
            return [MCU + b"\x14" + b"1.0" + b"\xf7"]
        return []

    def meter_levels(self, now=None):
        """each strip's meter now (0..12), falling one step every METER_STEP since its last update"""
        now = time.monotonic() if now is None else now
        return [max(0, level - int((now - when) / self.METER_STEP)) for level, when in self.meters]

    def state(self):
        """for the app: {faders, leds (the notes lit), lcd (2 lines), rings, meters}"""
        text = "".join(self.lcd)
        return {"faders": list(self.faders), "leds": sorted(n for n, on in self.leds.items() if on),
                "lcd": [text[:56], text[56:]], "rings": list(self.rings), "meters": self.meter_levels(),
                "seen": round(self.seen, 1)}

    @staticmethod
    def fader(strip, value):
        """a fader moved (strip 0-7, 8 master; value 0..16383) -> its message"""
        value = max(0, min(16383, int(value)))
        return bytes([0xE0 | strip, value & 127, value >> 7])

    @staticmethod
    def press(note, down=True):
        return bytes([0x90, note, 127 if down else 0])

    @staticmethod
    def pan(strip, steps):
        """a pan knob turned (strip 0-7) by steps (+ right, - left) -> its message (relative: 1-63 up, 65-127 down)"""
        steps = max(-63, min(63, int(steps)))
        return bytes([0xB0, 0x10 + strip, steps if steps >= 0 else 64 - steps])
