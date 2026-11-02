"""Tests for the Studio link as a snake: the Pocket's senders in small packets, the Studio's mix back to the Pocket
(on a USB sound card) or the Pocket's own sound there, and its blocks following the Studio's Latency step. No
hardware: PipeWire's objects are made up, the Studio is a web server on this computer.

  python tests/test_link_snake.py
"""
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
TMP = Path(tempfile.mkdtemp(prefix="fm1-snake-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"),
                  FM1_SETTINGS=str(TMP / "settings.json"))

import bridge  # noqa: E402
import netaudio  # noqa: E402
from test_libui import make_app  # noqa: E402


def node(node_id, name, cls="Audio/Sink", **props):
    return {"id": node_id, "type": "PipeWire:Interface:Node",
            "info": {"props": dict(props, **{"media.class": cls, "node.name": name})}}


def studio(status):
    """a Studio's web server answering /api/status with status -> (server, port)"""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(status).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_senders_keep_pipewires_packet_size():
    """1-2 ms packets dropped sound on a Pi Zero W (and on the Studio): PipeWire's own packet size, no ptime"""
    text = netaudio.sender_config("169.254.10.20", fm1s=("A",))
    assert "ptime" not in text and text.count("net.mtu = 1280") == 2                     # SINK's and FM-1 A's


def test_studio_status():
    server, port = studio({"pocket_fm1s": True, "link_return": 46010, "latency": "LOWER", "link_rec": True})
    try:
        assert netaudio.studio_status("127.0.0.1", port) == {"fm1s": True, "audio": None, "rec": True, "sees_pocket": None,
                                                             "return": 46010, "latency": "LOWER"}
    finally:
        server.shutdown()
    server, port = studio({"link_return": None, "latency": "FASTEST", "link_audio": "midi"})   # Mix to Pocket off;
    try:                                                                                        # a step not known
        assert netaudio.studio_status("127.0.0.1", port) == {"fm1s": False, "audio": "midi", "rec": False, "sees_pocket": None,
                                                             "return": None, "latency": "SAFE"}
    finally:
        server.shutdown()
    server, port = studio({"link_return": True})                                 # not a port
    try:
        assert netaudio.studio_status("127.0.0.1", port)["return"] is None
    finally:
        server.shutdown()
    assert netaudio.studio_status("127.0.0.1", port, timeout=0.5) == {"fm1s": False, "audio": None, "rec": False,
                                                                      "sees_pocket": None, "return": None, "latency": "SAFE"}   # nobody


def test_snake_timing():
    assert netaudio.snake_timing("SAFE") == (1024, 44)
    assert netaudio.snake_timing("LOW") == (512, 23)
    assert netaudio.snake_timing("LOWER") == (512, 23)       # not below POCKET_BLOCK on the Pocket
    assert netaudio.snake_timing("LOWEST") == (512, 23)
    assert netaudio.snake_timing("LOWEST", speaker=True) == (1024, 44)   # a Bluetooth speaker needs the room
    assert netaudio.snake_timing(None) == (1024, 44)
    for step in netaudio.LATENCY:                             # the buffer always more than two blocks
        block, ms = netaudio.snake_timing(step)
        assert ms * 48 > 2 * block
    mix = netaudio.receiver_config(netaudio.RETURN_PORT, 12, netaudio.MIX_BACK, "Studio mix (link)")
    assert "source.port = 46010" in mix and "sess.latency.msec = 12" in mix and '"fm1-studio-mix"' in mix
    assert "sess.ignore-ssrc = true" in mix                   # the Studio's sender started again: still heard


def test_usb_out_node():
    objects = [node(10, "alsa_output.usb-Teenage_Engineering_EP-136-00.analog-stereo", **{"alsa.card_name": "EP-136"}),
               node(20, "alsa_output.usb-XOXO_Companion_I_O-00.analog-stereo", **{"alsa.card_name": "Companion I/O"}),
               node(30, "alsa_output.usb-Generic_USB_Audio-00.analog-stereo", **{"alsa.card_name": "USB Audio"}),
               node(40, "alsa_input.usb-Generic_USB_Audio-00.analog-stereo", "Audio/Source"),
               node(50, "bluez_output.00_11_22_33_44_55.1"),
               node(60, "alsa_output.platform-bcm2835_audio.stereo-fallback")]
    assert bridge.usb_out_node(objects) == {"id": 30, "name": "alsa_output.usb-Generic_USB_Audio-00.analog-stereo",
                                            "label": "USB Audio"}            # the newest; not the I/O card's
    assert bridge.usb_out_node(objects[:2])["label"] == "EP-136"
    assert bridge.usb_out_node(objects[1:2]) is None and bridge.usb_out_node([]) is None


def test_a_usb_sound_card_plays_the_pocket_on_its_own():
    app = make_app()
    app.sink = app.jack = app.net_sink = app.card = None
    assert app.outputs() == (None, None)                                 # nothing to play to
    app.usb_any = {"id": 30, "name": "alsa_output.usb-Generic_USB_Audio-00.analog-stereo", "label": "USB Audio"}
    assert app.outputs() == ("alsa_output.usb-Generic_USB_Audio-00.analog-stereo", None)
    app.net_sink = netaudio.SINK                                         # linked: the Studio's, as before
    assert app.outputs() == (netaudio.SINK, None)
    app.net_sink, app.sink = None, {"name": "bluez_output.00_11_22_33_44_55.1", "id": 50}
    assert app.outputs()[0] == "bluez_output.00_11_22_33_44_55.1"        # a speaker: the speaker, as before


class Loop:
    made = []

    def __init__(self, rate=48000):
        self.calls, self.stopped = [], False
        Loop.made.append(self)

    def follow(self, objects):
        return False

    def ensure(self, source, sink, name=None, pair=None):
        self.calls.append((source, sink, name))

    def stop(self):
        self.stopped = True


def test_snake_on_the_pocket():
    app = make_app()

    class Midi:
        link_address = "169.254.10.20"
    box_midi, app.midi = app.midi, Midi()
    ran, listened = [], []
    real = bridge.run, bridge.Loopback, bridge.AUDIO["quantum"]
    bridge.run = lambda cmd, timeout=15, **k: ran.append(cmd) or (0, "")
    bridge.Loopback = Loop
    app.mix_back.listen = lambda port=None, latency_ms=40: listened.append((port, latency_ms))
    usb = "alsa_output.usb-Generic_USB_Audio-00.analog-stereo"
    objects = [node(30, usb, **{"alsa.card_name": "USB Audio"}), node(70, netaudio.MIX_BACK, "Audio/Source"),
               node(80, netaudio.SINK)]
    try:
        app.state.update(studio_link=True, link_hear="studio")
        app.sink, app.net_sink = None, netaudio.SINK
        app.studio_info["169.254.10.20"] = {"fm1s": False, "return": 46010, "latency": "LOWER"}
        app.snake(objects)
        assert listened[-1] == (46010, 23) and bridge.AUDIO["quantum"] == 512      # the Studio's step, followed
        assert ran[-1] == ["pw-metadata", "-n", "settings", "0", "clock.force-quantum", "512"]
        assert list(app.hear_loops) == [netaudio.MIX_BACK]
        assert app.hear_loops[netaudio.MIX_BACK].calls[-1] == (netaudio.MIX_BACK, usb, "fm1-hear-0")
        status = app.link_status()
        assert status["hear"] == "studio" and status["usb_out"] == "USB Audio" and status["block"] == 512
        app.midi, app.settings_menu = box_midi, "link"
        assert ("link_hear", "Hear", "Studio mix") in app.settings_rows()               # Settings > Studio link's row
        app.midi = Midi()
        mixed = app.hear_loops[netaudio.MIX_BACK]
        app.set_link_hear("pocket")                            # the Pocket's own sound, as it goes to the Studio
        app.snake(objects)
        assert mixed.stopped and listened[-1] == (None, 23)
        assert app.hear_loops["monitor:" + netaudio.SINK].calls[-1] == ("monitor:" + netaudio.SINK, usb, "fm1-hear-0")
        app.net_audio.fm1s = ("A",)                            # an FM-1 sent on its own: in what's heard too
        app.snake(objects + [node(81, netaudio.fm1_sink("A"))])
        assert list(app.hear_loops) == ["monitor:" + netaudio.SINK, "monitor:" + netaudio.fm1_sink("A")]
        app.net_audio.fm1s = ()
        app.set_link_hear("studio")
        app.studio_info["169.254.10.20"] = {"fm1s": False, "return": None, "latency": "LOWEST"}   # Mix to Pocket off
        app.snake(objects)
        assert listened[-1][0] is None and bridge.AUDIO["quantum"] == 1024             # not a snake: 1024 again
        assert list(app.hear_loops) == ["monitor:" + netaudio.SINK]                      # its own sound, then
        app.studio_info["169.254.10.20"] = {"fm1s": False, "return": 46010, "latency": "LOWEST"}
        app.sink = {"name": "bluez_output.00_11_22_33_44_55.1", "id": 50}             # a Bluetooth speaker too
        app.snake(objects)
        assert bridge.AUDIO["quantum"] == 1024 and listened[-1] == (46010, 44)
        app.sink = None
        sent = []
        app.net_audio.to = lambda address, fm1s=(): sent.append(address)
        app.studio_info["169.254.10.20"] = {"fm1s": False, "audio": "midi", "return": 46010, "latency": "SAFE"}
        app.link_audio(objects, None)                          # the Studio wants MIDI only: no sound sent to it,
        assert sent[-1] is None and listened[-1][0] == 46010   # its mix still comes back
        app.studio_info["169.254.10.20"]["audio"] = "mix"
        app.link_audio(objects, None)
        assert sent[-1] == "169.254.10.20"
        app.state.update(studio_link=False)                    # not linked: nothing of it
        app.snake(objects)
        assert app.hear_loops == {} and listened[-1][0] is None and app.usb_out is None
    finally:
        bridge.run, bridge.Loopback, bridge.AUDIO["quantum"] = real


def test_web_sets_hear():
    app = make_app()
    heard = []
    app.set_link_hear = heard.append
    import library
    library.queue_command({"cmd": "set", "key": "link_hear", "value": "pocket"})
    library.queue_command({"cmd": "set", "key": "link_hear", "value": "loud"})     # refused
    app.web_commands()
    assert heard == ["pocket"]


def test_link_threads_not_real_time():
    """the link's session threads can run a hook first (on_thread), but the MIDI process gives them no real-time
    priority: they route what comes in without pausing, and a real-time thread that runs 200 ms without a pause
    gets the whole MIDI process killed (RLIMIT_RTTIME, as RTKit sets it; seen on the Pocket 2026-11-02)"""
    import time
    import netmidi
    ran = []
    link = netmidi.Invitation(netmidi.LINK_NAME, lambda m: None, find=lambda: [], on_thread=lambda: ran.append(1))
    link.RETRY = 0.05
    try:
        assert link.start()
        end = time.monotonic() + 3
        while not ran and time.monotonic() < end:
            time.sleep(0.02)
        assert ran == [1]
    finally:
        link.stop()
    import blemidi
    assert "on_thread=make_realtime" not in Path(blemidi.__file__).read_text(encoding="utf-8")


def test_relink_when_the_studio_forgot_the_pocket():
    app = make_app()
    linked = []

    class Midi:
        link_address, net = "192.168.0.33", ["Studio"]

        def set_link(self, on, host=None, prefer=None):
            linked.append(on)
    app.midi = Midi()
    app.state.update(studio_link=True)
    server, port = studio({"pocket": None})                   # the Studio: no Pocket linked
    try:
        assert netaudio.studio_status("127.0.0.1", port)["sees_pocket"] is False
    finally:
        server.shutdown()
    app.link_misses = 1
    app.relink_stale()
    assert linked == []                                       # once: could be a moment while it links
    app.link_misses = 2
    app.relink_stale()
    assert linked == [True] and app.link_misses == 0          # twice in a row: linked again
    app.link_misses = 2
    app.state.update(studio_link=False)                       # the link off: left off
    app.relink_stale()
    assert linked == [True]


def test_the_studio_linked_before_is_preferred():
    import netmidi
    found = [("FM-1 Companion", "169.254.1.2", 5004), ("Studio", "192.168.0.33", 5004),
             ("Studio", "169.254.115.88", 5004)]
    link = netmidi.Invitation(netmidi.LINK_NAME, lambda m: None, find=lambda: found, prefer="Studio")
    assert link.target() == ("Studio", "192.168.0.33", 5004)      # the one linked before (in found's order)
    link.prefer = "Gone Studio"
    assert link.target()[0] == "FM-1 Companion"                       # not there: the first found, as before
    assert netmidi.Invitation.SYNC <= 5                                # (a Studio forgets one after 25 s)
    app = make_app()

    class Midi:
        net = ["Studio"]
    app.midi = Midi()
    app.state.update(studio_link=True, studio_last=None)
    app.remember_studio()
    assert app.state["studio_last"] == "Studio"


def test_a_studio_that_refuses_is_passed_over():
    """two Studios found, the first refusing (it follows the other: NO): the link tries the next at once"""
    import socket
    import struct
    import time
    import netmidi
    follower = [socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(2)]
    follower[0].bind(("127.0.0.1", 0))
    port = follower[0].getsockname()[1]
    try:
        follower[1].bind(("127.0.0.1", port + 1))
    except OSError:
        return                                                # (the next port taken here: nothing to show)

    def refuse(sock):
        try:
            packet, addr = sock.recvfrom(2048)
            token = struct.unpack(">I", packet[8:12])[0]
            sock.sendto(netmidi.SIGN + b"NO" + struct.pack(">III", netmidi.VERSION, token, 1) + b"Follower\0", addr)
        except OSError:
            pass
    threading.Thread(target=refuse, args=(follower[0],), daemon=True).start()
    studio = netmidi.Session("Studio", 15044, lambda m: None)
    assert studio.start()
    link = netmidi.Invitation(netmidi.LINK_NAME, lambda m: None,
                              find=lambda: [("Follower", "127.0.0.1", port), ("Studio", "127.0.0.1", 15044)])
    link.sock, link.dsock = (socket.socket(socket.AF_INET, socket.SOCK_DGRAM) for _ in range(2))
    link.sock.bind(("0.0.0.0", 0))
    link.dsock.bind(("0.0.0.0", 0))
    try:
        started = time.monotonic()
        assert link.connect() and link.peer["name"] == "Studio"
        assert time.monotonic() - started < 1.0               # the NO taken at once, not waited out
    finally:
        link.stop()
        for sock in follower:
            sock.close()


# ---------------------------------------------------------------- the Studio's clock, re-timed

def test_clock_relay_evens_out_bunched_ticks():
    import random
    import blemidi
    random.seed(7)
    relay, per = blemidi.ClockRelay(), 60 / (100 * 24)        # the Studio at 100 BPM: 25 ms a tick
    assert relay.due(0.0) is None                             # no clock yet: nothing sent
    for k in range(400):                                      # bunches of six, each up to 40 ms late (Wi-Fi)
        relay.tick((k // 6) * 6 * per + 6 * per + random.uniform(0, 0.04))
    now = relay.ticks[-1][1]
    assert abs(relay.bpm(now) - 100) < 0.2
    times = []
    for _ in range(24):
        times.append(relay.due(now))
        relay.sent += 1
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert max(gaps) - min(gaps) < 1e-9 and abs(gaps[0] - per) < 0.0002    # evenly, at its tempo
    assert relay.sent == relay.count + 24
    relay.sent = relay.count + 100                            # far ahead (its clock stalled): its next tick again
    relay.due(now)
    assert relay.sent == relay.count
    assert relay.due(now + 1.0) is None and relay.sent is None    # no clock for half a second: none sent
    burst = blemidi.ClockRelay()                              # 48 ticks at once (a stall let go): no line
    for k in range(48):
        burst.tick(5.0 + k * 0.0001)
    assert burst.fit(5.01) is None and burst.due(5.01) is None


def test_clock_from_the_link_is_relayed_not_passed():
    import types
    import blemidi
    routed = []
    bridge_ = types.SimpleNamespace(link=True, clock_mode="follow", mmc=[0, None, 0.0], relay=blemidi.ClockRelay(),
                                    watch={"NET": blemidi.ClockWatch()},
                                    passes=lambda src, m: True, route_from=lambda src, m: routed.append(m))
    bridge_.relaying = lambda: blemidi.MidiBridge.relaying(bridge_)
    blemidi.MidiBridge.from_net(bridge_, bytes([blemidi.CLOCK]))
    assert routed == [] and bridge_.relay.count == 1          # counted, sent again by clock_loop
    blemidi.MidiBridge.from_net(bridge_, bytes([blemidi.START]))
    assert routed == [bytes([blemidi.START])]                 # Start at once
    bridge_.clock_mode = "box"                                # the box leads: its own clock, as before
    blemidi.MidiBridge.from_net(bridge_, bytes([blemidi.CLOCK]))
    assert bridge_.relay.count == 1 and routed[-1] == bytes([blemidi.CLOCK])


# ---------------------------------------------------------------- linked REC (MMC over the link)

def test_mmc_messages():
    import blemidi
    assert blemidi.mmc_command(bytes([0xF0, 0x7F, 0x7F, 0x06, 0x06, 0xF7])) == "record"
    assert blemidi.mmc_command(bytes([0xF0, 0x7F, 0x01, 0x06, 0x01, 0xF7])) == "stop"      # any device id
    assert blemidi.mmc_command(bytes([0xF0, 0x7F, 0x7F, 0x06, 0x02, 0xF7])) is None         # (Play: not used)
    assert blemidi.mmc_command(bytes([0x90, 60, 100])) is None
    assert blemidi.mmc_message("record") == bytes([0xF0, 0x7F, 0x7F, 0x06, 0x06, 0xF7])
    assert blemidi.mmc_message("stop") == bytes([0xF0, 0x7F, 0x7F, 0x06, 0x01, 0xF7])


def test_mmc_from_the_link_is_not_routed():
    import types
    import blemidi
    routed = []
    bridge_ = types.SimpleNamespace(link=True, mmc=[0, None, 0.0], passes=lambda src, m: True,
                                    route_from=lambda src, m: routed.append(m))
    blemidi.MidiBridge.from_net(bridge_, blemidi.mmc_message("record"))
    assert bridge_.mmc[:2] == [1, "record"] and routed == []
    blemidi.MidiBridge.from_net(bridge_, bytes([0x90, 60, 100]))           # a note: routed as ever
    assert routed == [bytes([0x90, 60, 100])]
    bridge_.link = False                                                   # not the Pocket's link (a DAW's): MIDI
    blemidi.MidiBridge.from_net(bridge_, blemidi.mmc_message("stop"))
    assert bridge_.mmc[0] == 1 and len(routed) == 2


def test_linked_rec_on_the_pocket():
    app = make_app()

    class Midi:
        link_address, net = "169.254.10.20", ["Studio"]

        def __init__(self):
            self.mmc = []

        def send_mmc(self, command):
            self.mmc.append(command)
    app.midi = Midi()
    app.state.update(studio_link=True)
    recording = [False]
    app.recorder.recording = lambda: recording[0]
    pressed = []

    def toggle(linked=False):
        pressed.append(linked)
        recording[0] = not recording[0]
    app.toggle_recording = toggle
    app.linked_rec("record", 100.0)                            # the Studio's REC: the Pocket records too
    assert pressed == [True] and app.link_take == {"trigger": "linked box", "linked_with": "Studio", "at": 100.0}
    app.linked_rec("record", 101.0)                            # already recording: nothing
    assert pressed == [True]
    app.linked_rec("stop", 102.0)
    assert pressed == [True, True] and not recording[0]
    assert app.midi.mmc == []                                  # nothing sent back (no loop)
    app.studio_info["169.254.10.20"] = {"rec": False}
    app.link_rec_out("record", 5.0)                            # the Studio's Linked REC off: not sent
    assert app.midi.mmc == []
    app.studio_info["169.254.10.20"] = {"rec": True}
    recording[0] = True
    app.link_take = None
    app.link_rec_out("record", 5.0)
    assert app.midi.mmc == ["record"] and app.link_take["trigger"] == "here"
    app.link_rec_out("stop", 6.0)
    assert app.midi.mmc == ["record", "stop"]
    app.state.update(studio_link=False)                        # not linked: neither way
    app.link_rec_out("record", 7.0)
    app.linked_rec("record", 7.0)
    assert app.midi.mmc == ["record", "stop"] and pressed == [True, True]


def test_link_file():
    import wave
    import meters
    wav = TMP / "take.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(bytes(4 * 48000 * 2))                    # 2 s
    meters.write_link_file(wav, {"trigger": "linked box", "linked_with": "Studio", "at": 100.0}, 103.0)
    note = json.loads((TMP / "take.wav.link.json").read_text())
    assert note == {"trigger": "linked box", "linked_with": "Studio", "first_sample_after_trigger_ms": 1000.0,
                    "seconds": 2.0}                            # stopped at 103, 2 s long: began 1 s after the REC


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
