"""Network MIDI (RTP-MIDI): packets both ways, a session started from a 'computer' on this machine over UDP, and
the Mackie Control state a DAW sends. No network beyond localhost needed."""

import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "fm1-bt-bridge"))

import netmidi  # noqa: E402


def test_packets():
    msgs = [b"\x90\x3c\x64", b"\xb0\x07\x50", b"\xf8", b"\xf0\x7d\x01\x02\xf7"]
    packet = netmidi.encode(msgs, 7, 0x1234)
    assert packet[:2] == b"\x80\x61" and struct.unpack(">H", packet[2:4])[0] == 7
    assert netmidi.decode(packet) == msgs
    long = [bytes([0x90, n, 100]) for n in range(10)]               # over 15 bytes: the long header
    assert netmidi.decode(netmidi.encode(long, 1, 1)) == long
    assert netmidi.encode([], 1, 1) is None
    # what a Mac sends: running status, a delta time before the first (Z), the journal flag (J) after
    body = bytes([0x90, 0x3c, 0x64, 0x00, 0x3e, 0x64, 0x00, 0xc0, 0x05])
    head = struct.pack(">BBHII", 0x80, 0x61, 1, 0, 9)
    assert netmidi.decode(head + bytes([0x60 | len(body) + 1, 0x00]) + body + b"\x20\x00") == [
        b"\x90\x3c\x64", b"\x90\x3e\x64", b"\xc0\x05"]
    assert netmidi.decode(b"\xff\xffIN") == []                      # a session command: not MIDI


def test_session():
    got = []
    session = netmidi.Session("FM-1 Companion", 15004, got.append)
    assert session.start()
    mac = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    mac_data = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    mac.settimeout(2)
    mac_data.settimeout(2)
    invite = b"\xff\xffIN" + struct.pack(">III", 2, 0xABCD, 0x5151) + b"Pat's Mac\0"
    mac.sendto(invite, ("127.0.0.1", 15004))
    reply, _ = mac.recvfrom(256)
    assert reply[:4] == b"\xff\xffOK" and struct.unpack(">I", reply[8:12])[0] == 0xABCD
    assert reply[16:].split(b"\0")[0] == b"FM-1 Companion"
    mac_data.sendto(invite, ("127.0.0.1", 15005))
    assert mac_data.recvfrom(256)[0][:4] == b"\xff\xffOK"
    time.sleep(0.05)
    assert session.names() == ["Pat's Mac"]
    mac_data.sendto(b"\xff\xffCK" + struct.pack(">IB3xQQQ", 0x5151, 0, 1000, 0, 0), ("127.0.0.1", 15005))
    ck, _ = mac_data.recvfrom(256)
    count, t1, t2 = struct.unpack(">B3xQQ", ck[8:28])
    assert ck[:4] == b"\xff\xffCK" and count == 1 and t1 == 1000 and t2 > 0
    mac_data.sendto(netmidi.encode([b"\x90\x40\x70"], 1, 0x5151), ("127.0.0.1", 15005))
    time.sleep(0.1)
    assert got == [b"\x90\x40\x70"]                                 # the DAW's note, through to the box
    session.send([b"\x80\x40\x00"])
    assert netmidi.decode(mac_data.recvfrom(256)[0]) == [b"\x80\x40\x00"]   # and the box's back
    mac.sendto(b"\xff\xffBY" + struct.pack(">III", 2, 0xABCD, 0x5151), ("127.0.0.1", 15004))
    time.sleep(0.1)
    assert session.names() == []


def test_mackie():
    m = netmidi.Mackie()
    m.feed(bytes([0xE2, 0x7F, 0x3F]))                               # strip 3's fader
    m.feed(bytes([0x90, 0x5E, 0x7F]))                               # Play lit
    m.feed(bytes([0xF0, 0x00, 0x00, 0x66, 0x14, 0x12, 0x00]) + b"BASS   LEAD" + b"\xf7")
    m.feed(bytes([0xF0, 0x00, 0x00, 0x66, 0x14, 0x12, 56]) + b"-6.0" + b"\xf7")
    s = m.state()
    assert s["faders"][2] == 0x7F | 0x3F << 7 and s["leds"] == [0x5E]
    assert s["lcd"][0].startswith("BASS   LEAD") and s["lcd"][1].startswith("-6.0") and len(s["lcd"][0]) == 56
    assert netmidi.Mackie.fader(8, 20000) == bytes([0xE8, 0x7F, 0x7F])
    # what Ableton Live adds: the handshake, the pan knobs' rings, the level meters
    query = m.feed(bytes([0xF0, 0x00, 0x00, 0x66, 0x14, 0x00, 0xF7]))
    assert query == [bytes([0xF0, 0, 0, 0x66, 0x14, 0x01]) + b"FM1CMP1" + bytes(4) + b"\xf7"]
    assert m.feed(bytes([0xF0, 0, 0, 0x66, 0x14, 0x02]) + b"FM1CMP1" + bytes(4) + b"\xf7") == [
        bytes([0xF0, 0, 0, 0x66, 0x14, 0x03]) + b"FM1CMP1\xf7"]
    m.feed(bytes([0xB0, 0x31, 0x16]))                               # strip 2's ring at 6 (the middle)
    m.feed(bytes([0xD0, 0x2B]), now=100.0)                          # strip 3's meter at 11
    assert m.state()["rings"][1] == 6
    assert m.meter_levels(100.0)[2] == 11 and m.meter_levels(101.0)[2] == 11 - 3   # falls 1 step a 0.3 s
    assert netmidi.Mackie.pan(4, -3) == bytes([0xB0, 0x14, 67]) and netmidi.Mackie.pan(0, 2) == bytes([0xB0, 0x10, 2])
    assert netmidi.Mackie.press(0x5E, False) == bytes([0x90, 0x5E, 0])


def name_bytes(name):
    return b"".join(bytes([len(part)]) + part.encode() for part in name.split(".")) + b"\0"


def record(name, rtype, data):
    return name_bytes(name) + struct.pack(">HHIH", rtype, 1, 120, len(data)) + data


def studio_reply(instance, host, address, port=5004):
    """what avahi answers for _apple-midi._udp: PTR to the instance, its SRV and its host's A"""
    full = f"{instance}._apple-midi._udp.local"
    records = [record("_apple-midi._udp.local", 12, name_bytes(full)),
               record(full, 33, struct.pack(">HHH", 0, 0, port) + name_bytes(host)),
               record(host, 1, socket.inet_aton(address))]
    return struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 2) + b"".join(records)


class Replies:
    """a socket for find_studios: the query it sent, then the replies given"""
    def __init__(self, *replies):
        self.sent, self.replies = [], list(replies)

    def setsockopt(self, *a):
        pass

    def sendto(self, packet, addr):
        self.sent.append((packet, addr))

    def recv(self, n):
        return self.replies.pop(0)

    def fileno(self):
        return -1


def test_find_studios():
    """the Pocket's Studio link finds the Studios' music sessions by DNS-SD: not their control surfaces, a computer
    or another Pocket"""
    for name, studio in (("FM-1 Companion on fm1studio", True), ("FM-1 Companion MCU on fm1studio", False),
                         ("XOXO Studio on xoxostudio", True), ("Pat's MacBook", False),
                         ("FM-1 Companion Pocket", False)):
        assert netmidi.is_studio(name + "._apple-midi._udp.local") == studio, name
    reply = studio_reply("FM-1 Companion on fm1studio", "fm1studio.local", "169.254.10.20")
    assert (("_apple-midi._udp.local", 12, "FM-1 Companion on fm1studio._apple-midi._udp.local")
            in netmidi.mdns_records(reply))
    mcu = studio_reply("FM-1 Companion MCU on fm1studio", "fm1studio.local", "169.254.10.20", 5006)
    sock = Replies(mcu, reply)
    was = netmidi.select.select
    netmidi.select.select = lambda r, w, x, t: (r if sock.replies else [], [], [])
    try:
        assert netmidi.find_studios(sock=sock) == [("FM-1 Companion on fm1studio", "169.254.10.20", 5004)]
    finally:
        netmidi.select.select = was
    assert sock.sent[0][1] == netmidi.MDNS and b"\x0b_apple-midi" in sock.sent[0][0]


def test_link():
    """the Pocket starts a session to a Studio's (as a computer does): MIDI both ways, gone from the Studio when
    the link stops"""
    at_studio, at_pocket = [], []
    studio = netmidi.Session("FM-1 Companion", 15014, at_studio.append)
    assert studio.start()
    link = netmidi.Invitation(netmidi.LINK_NAME, at_pocket.append, find=lambda: [("FM-1 Companion", "127.0.0.1",
                                                                                   15014)])
    try:
        assert link.start()
        end = time.monotonic() + 5
        while not (link.names() and studio.names()) and time.monotonic() < end:
            time.sleep(0.05)
        assert link.names() == ["FM-1 Companion"] and studio.names() == [netmidi.LINK_NAME]
        studio.send([b"\xf8", b"\x90\x3c\x64"])
        link.send([b"\xb0\x07\x50"])
        end = time.monotonic() + 2
        while (len(at_pocket) < 2 or not at_studio) and time.monotonic() < end:
            time.sleep(0.05)
        assert at_pocket == [b"\xf8", b"\x90\x3c\x64"] and at_studio == [b"\xb0\x07\x50"]
        link.stop()
        end = time.monotonic() + 2
        while studio.names() and time.monotonic() < end:
            time.sleep(0.05)
        assert studio.names() == [] and link.names() == []
    finally:
        link.stop()
    moving = netmidi.Invitation(netmidi.LINK_NAME, at_pocket.append, find=lambda: [
        ("FM-1 Companion", "169.254.10.20", 15014), ("FM-1 Companion", "127.0.0.1", 15024)])
    moving.peer = {"name": "FM-1 Companion", "control": ("127.0.0.1", 15024), "data": ("127.0.0.1", 15025)}
    moving.sock = moving.dsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # (for its BY)
    assert moving.to_cable() and moving.peer is None   # linked over Wi-Fi, the Studio on a cable too: moved
    moving.peer = {"name": "FM-1 Companion", "control": ("169.254.10.20", 15014), "data": ("169.254.10.20", 15015)}
    assert not moving.to_cable()                  # already on the cable
    moving.sock.close()
    nowhere = netmidi.Invitation(netmidi.LINK_NAME, at_pocket.append, find=lambda: [])
    assert nowhere.target() is None and nowhere.error == "no Studio found"


def test_link_clock():
    """linked, the Studio leads: the Pocket's routes to NET carry notes but never clock or start / stop"""
    import blemidi

    class Net:
        sent = []

        def send(self, messages):
            self.sent.append(list(messages))

    b = blemidi.MidiBridge(["felucca"])
    b.net, b.link = Net(), True
    b.deliver("FM-1>NET", [b"\xf8", b"\xfa", b"\x90\x3c\x64", b"\xfc"])
    b.deliver("FM-1>NET", [b"\xf8"])
    assert Net.sent == [[b"\x90\x3c\x64"]]
    b.link = False                            # (the Studio's own NET, to a computer: clock goes as before)
    b.deliver("FM-1>NET", [b"\xf8"])
    assert Net.sent[-1] == [b"\xf8"]


def test_link_audio_config():
    """the link's audio: PipeWire's RTP sender to the Studio's address (a sink the Pocket plays into), its receiver
    on the Studio (a source); the same format both sides"""
    import netaudio
    send, receive = netaudio.sender_config("169.254.10.20"), netaudio.receiver_config()
    assert 'destination.ip = "169.254.10.20"' in send and "libpipewire-module-rtp-sink" in send
    assert f"rtp.ssrc = {netaudio.stream_id()}" in send and netaudio.stream_id() == netaudio.stream_id()
    assert f'node.name = "{netaudio.SINK}"' in send and 'media.class = "Audio/Sink"' in send
    assert "libpipewire-module-rtp-source" in receive and f"source.port = {netaudio.PORT}" in receive
    assert f'node.name = "{netaudio.SOURCE}"' in receive and 'media.class = "Audio/Source"' in receive
    for text in (send, receive):
        assert netaudio.FORMAT in text and text.count("{") == text.count("}")
    sender = netaudio.Sender()
    sender.to(None)                           # not linked: nothing started
    assert not sender.running() and sender.text is None


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
