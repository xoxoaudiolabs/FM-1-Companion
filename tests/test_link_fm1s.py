"""Tests for a Pocket's FM-1s on a linked Studio (its FM-1 E, F, G): the library's --fm1 A-C, the web API's FM-1
choice and the Studio's confirmed writes, one RTP stream and one network MIDI session per FM-1. No hardware: the
FM-1s' sound cards are made up, the network is this computer.

  python tests/test_link_fm1s.py
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
TMP = Path(tempfile.mkdtemp(prefix="fm1-link-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"),
                  FM1_SETTINGS=str(TMP / "settings.json"))

import blemidi  # noqa: E402
import bridge  # noqa: E402
import library  # noqa: E402
import netaudio  # noqa: E402
import sloop  # noqa: E402
import web  # noqa: E402
from test_libui import make_app  # noqa: E402

CARDS = [3, 4, 5]                             # three FM-1s' sound cards, A to C by USB port


def with_cards(cards):
    """sloop.fm1_cards as if those FM-1s were plugged in -> a function that puts it back"""
    real = sloop.fm1_cards
    sloop.fm1_cards = lambda text=None: list(cards)
    return lambda: setattr(sloop, "fm1_cards", real)


# ---------------------------------------------------------------- the library: --fm1 A-C

def test_library_fm1_choice():
    put_back = with_cards(CARDS)
    try:
        library.SETTINGS.write_text(json.dumps({"library_fm1": "B"}))
        assert library.target_card() == 4                       # Settings > Sloop's
        library.FM1 = "C"
        assert library.target_card() == 5                       # --fm1's, before Settings'
        sloop.fm1_cards = lambda text=None: [3, 4]
        try:
            library.target_card()
            raise AssertionError("an FM-1 C that isn't there")
        except sloop.SloopError as e:                           # never another FM-1 instead
            assert "no FM-1 C" in str(e)
        library.FM1 = None
        library.SETTINGS.write_text(json.dumps({"library_fm1": "C"}))
        assert library.target_card() == 3                       # Settings' C, since unplugged: A
        sloop.fm1_cards = lambda text=None: [3]
        assert library.target_card() is None                    # one FM-1: whichever it is
    finally:
        library.FM1 = None
        library.SETTINGS.unlink()
        put_back()


def test_library_fm1_flag():
    assert library.main(["--fm1", "D", "backup"]) == 2
    assert library.main(["--fm1", "B"]) == 2
    put_back = with_cards(CARDS)
    seen = []
    real = library.connect

    def connect():
        seen.append((library.FM1, library.target_card()))
        raise sloop.SloopError("notfound", "no FM-1 here")
    library.connect = connect
    try:
        assert library.main(["--fm1", "C", "backup"]) == 1
        assert seen == [("C", 5)]
        state = library.read_state()
        assert state["fm1"] == "C" and state["state"] == "error"   # the job says which FM-1 it was on
    finally:
        library.connect, library.FM1 = real, None
        put_back()


# ---------------------------------------------------------------- the web API

BASE = ""


def setup():
    global BASE
    server = web.ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    BASE = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    library.folder("backups")
    (library.folder("backups") / "2026-10-31_100000_manual.json").write_text("{}")
    return server


def jcall(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as reply:
            return reply.status, json.loads(reply.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def linked(address):
    """the box's status, linked to a Studio at address (or not, None)"""
    library.write_status({"link": {"on": bool(address), "address": address}})


def spying():
    """library.spawn caught -> (the args it got, a function that puts it back)"""
    spawned, real = [], library.spawn
    library.spawn = lambda args: spawned.append(list(args))
    return spawned, lambda: setattr(library, "spawn", real)


def test_web_status_lists_the_fm1s():
    if not BASE:
        setup()
    put_back = with_cards(CARDS[:2])
    try:
        linked(None)
        status, reply = jcall("/api/status")
        assert status == 200 and reply["fm1s"] == ["A", "B"]
    finally:
        put_back()


def test_web_run_on_an_fm1():
    if not BASE:
        setup()
    put_back, (spawned, unspy) = with_cards(CARDS), spying()
    try:
        assert jcall("/api/run", {"cmd": "backup", "fm1": "C"})[1]["ok"]
        assert jcall("/api/run", {"cmd": "song-backup"})[1]["ok"]
        assert jcall("/api/run", {"cmd": "fetch-sloop", "fm1": "B"})[1]["ok"]   # (GitHub's, not an FM-1's)
        assert spawned == [["--fm1", "C", "backup"], ["song-backup"], ["fetch", "sloop"]]
        sloop.fm1_cards = lambda text=None: [3]
        assert jcall("/api/run", {"cmd": "backup", "fm1": "B"})[0] == 400       # not plugged in
        assert jcall("/api/run", {"cmd": "backup", "fm1": "../A"})[0] == 400
        assert len(spawned) == 3
    finally:
        unspy()
        put_back()


def test_web_ask_for_an_fm1_on_the_box():
    """a write for one FM-1 from the Pocket's own page: still the joystick's hold, with the FM-1 shown"""
    if not BASE:
        setup()
    put_back = with_cards(CARDS)
    try:
        linked(None)
        status, reply = jcall("/api/ask", {"cmd": "restore", "file": "2026-10-31_100000_manual.json", "fm1": "C"})
        assert status == 200 and "box" in reply["message"]
        request = library.take_request()
        assert request["args"][0] == "restore" and request["fm1"] == "C"
        app = make_app()
        app.start_job = lambda args, title, show=True, web=False: app.started.append(args)
        app.web_request(request)                                  # the box's confirm screen
        assert app.screen == "confirm" and app.confirm["lines"][-1] == "FM-1 C, from the web"
        app.confirm["action"]()
        assert app.started[-1][:3] == ["--fm1", "C", "restore"]
    finally:
        put_back()


def test_web_ask_confirmed_on_the_studio():
    """a write the linked Studio confirmed on its screen starts at once, but only from the Studio's address"""
    if not BASE:
        setup()
    put_back, (spawned, unspy) = with_cards(CARDS), spying()
    ask = {"cmd": "restore", "file": "2026-10-31_100000_manual.json", "fm1": "B", "confirmed": True}
    try:
        linked("169.254.10.20")                                   # linked, but not from here
        assert jcall("/api/ask", ask)[0] == 403
        linked(None)
        assert jcall("/api/ask", ask)[0] == 403                   # not linked at all
        linked("127.0.0.1")                                       # from the Studio it's linked to
        status, reply = jcall("/api/ask", ask)
        assert status == 200 and reply["ok"] and library.take_request() is None    # no hold on the Pocket
        assert spawned[-1][:3] == ["--fm1", "B", "restore"]
        assert jcall("/api/ask", {"cmd": "update", "confirmed": True})[0] == 403   # the Pocket's own: its hold
        assert len(spawned) == 1
    finally:
        linked(None)
        unspy()
        put_back()


# ---------------------------------------------------------------- the link's sound: a stream per FM-1

def test_a_stream_per_fm1():
    text = netaudio.sender_config("169.254.10.20", fm1s=["A", "B", "C"])
    assert text.count("libpipewire-module-rtp-sink") == 4 and text.count("{") == text.count("}")
    for port in (netaudio.PORT, 46002, 46004, 46006):
        assert f"destination.port = {port}" in text
    for x in "ABC":
        assert f'node.name = "{netaudio.fm1_sink(x)}"' in text and f"rtp.ssrc = {netaudio.stream_id(x)}" in text
    ids = {netaudio.stream_id(x) for x in ("", "A", "B", "C")}
    assert len(ids) == 4                                          # each stream its own id, kept across restarts
    assert netaudio.sender_config("169.254.10.20") == netaudio.sender_config("169.254.10.20", fm1s=())
    receive = netaudio.receiver_config(netaudio.FM1_PORTS["C"], name=netaudio.fm1_source("C"), description="FM-1 G")
    assert "source.port = 46006" in receive and 'node.name = "fm1-pocket-c"' in receive
    assert "core.name = fm1-pocket-c-link" in receive and "core.name = fm1-pocket-link" in netaudio.receiver_config()


def test_studio_takes_fm1s():
    answer = {}

    class Studio(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps(answer).encode()
            self.send_response(200 if self.path == "/api/status" else 404)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Studio)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        assert not netaudio.studio_takes_fm1s("127.0.0.1", port)              # an older Studio
        answer["pocket_fm1s"] = True
        assert netaudio.studio_takes_fm1s("127.0.0.1", port)
    finally:
        server.shutdown()
        server.server_close()
    assert not netaudio.studio_takes_fm1s("127.0.0.1", port, timeout=0.5)     # nobody there


def fm1_node(node_id, card):
    return {"id": node_id, "type": "PipeWire:Interface:Node",
            "info": {"props": {"media.class": "Audio/Source", "node.name": f"alsa_input.usb-Felucca-{card}",
                               "api.alsa.path": f"front:{card}", "alsa.card_name": "Felucca"}}}


def test_bridge_sends_each_fm1_on_its_own():
    objects = [fm1_node(30, 3), fm1_node(40, 4), fm1_node(50, 5)]
    assert bridge.card_node(objects, 5)["name"] == "alsa_input.usb-Felucca-5"
    assert bridge.card_node(objects, 7) is None
    put_back = with_cards(CARDS)
    app = make_app()

    class Midi:
        link_address = "169.254.10.20"

        def set_link_fm1s(self, letters):
            sent.append(letters)
    sent, app.midi = [], Midi()
    try:
        app.state.update(studio_link=False)
        assert app.link_letters() == []                           # not linked
        app.state.update(studio_link=True)
        app.studio_split["169.254.10.20"] = (False, 1e12)         # (asked: an older Studio)
        assert app.link_letters() == [] and app.link_fm1s(objects) == []
        app.studio_split["169.254.10.20"] = (True, 1e12)
        assert app.link_letters() == ["A", "B", "C"]
        assert [(x, n["id"]) for x, n in app.link_fm1s(objects)] == [("A", 30), ("B", 40), ("C", 50)]
        sloop.fm1_cards = lambda text=None: [3, 4]
        assert app.link_letters() == ["A", "B"]
        app.source, app.source_b = {"name": "fm1a", "id": 30}, {"name": "fm1b", "id": 40}
        app.others = [{"name": "alsa_input.usb-ep136", "label": "EP-136", "id": 60}]
        assert [k for k, _ in app.mix_channels()] == ["a", "b", "u-ep136"]
        app.net_audio.fm1s = ("A", "B")                           # on their own streams: not in the mix too
        assert [k for k, _ in app.mix_channels()] == ["u-ep136"]
        app.net_audio.fm1s = ()

        class Loop:
            def __init__(self):
                self.calls = []

            def follow(self, objects):
                return False

            def ensure(self, source, sink, name=None, pair=None):
                self.calls.append((source, sink, name))
        app.fm1_loops = {x: Loop() for x in "ABC"}
        app.net_loop = Loop()
        started = []
        app.net_audio.ensure = started.append                     # (no PipeWire here)
        app.link_audio(objects, None)
        assert sent == [["A", "B"]]                               # the MIDI process: a session for each
        assert app.net_audio.fm1s == ("A", "B") and "fm1-studio-link-b" in started[-1]
        assert app.fm1_loops["A"].calls[-1] == ("alsa_input.usb-Felucca-3", "fm1-studio-link-a", "fm1-net-a")
        assert app.fm1_loops["C"].calls[-1] == (None, None, "fm1-net-c")
        assert app.link_status()["fm1s"] == ["A", "B"]
        app.link_audio(objects, None)
        assert sent == [["A", "B"]]                               # told once
        app.state.update(link_audio=False)                        # no sound over the link: MIDI sessions still
        app.link_audio(objects, None)
        assert app.net_audio.fm1s == () and app.fm1_loops["A"].calls[-1][0] is None and sent == [["A", "B"]]
    finally:
        app.net_audio.fm1s = ()
        put_back()


# ---------------------------------------------------------------- the link's MIDI: a session per FM-1

class FakeUsb:
    def __init__(self):
        self.sent, self.name = [], None

    def send_messages(self, messages):
        self.sent.extend(messages)

    def poll(self):
        pass

    def close(self):
        pass


class FakeSession:
    made = []

    def __init__(self, name, on_message, host=None):
        self.name, self.on_message, self.host, self.sent, self.stopped = name, on_message, host, [], False
        FakeSession.made.append(self)

    def start(self):
        return True

    def stop(self):
        self.stopped = True

    def send(self, messages):
        self.sent.extend(messages)


def test_a_midi_session_per_fm1():
    import netmidi
    real = netmidi.Invitation
    netmidi.Invitation = FakeSession
    try:
        midi = blemidi.MidiBridge(["felucca"])
        midi.usb, midi.usb_b, midi.usb_c = FakeUsb(), FakeUsb(), FakeUsb()
        midi.set_link_fm1s(["A", "B"])
        assert midi.fm1_net == {}                                 # not linked: none
        midi.set_link(True, "studio.local")
        link = FakeSession.made[-1]
        midi.set_link_fm1s(["A", "B", "C"])
        names = {x: s.name for x, s in midi.fm1_net.items()}
        assert names == {x: f"FM-1 Companion Pocket FM-1 {x}" for x in "ABC"}
        assert all(s.host == "studio.local" for s in midi.fm1_net.values())
        midi.fm1_net["C"].on_message([0x90, 60, 100])            # the Studio plays its FM-1 G: this Pocket's C
        assert midi.usb_c.sent == [[0x90, 60, 100]] and midi.usb.sent == []
        midi.to_link_fm1("C", [0x80, 60, 0])                      # and C's MIDI back to it
        midi.to_link_fm1("C", [0xF8])                             # (not its clock: the Studio leads)
        assert midi.fm1_net["C"].sent == [[0x80, 60, 0]]
        midi.from_fm1("FM-1 B", [0x91, 64, 90])                   # B's on its session...
        assert midi.fm1_net["B"].sent == [[0x91, 64, 90]]
        midi.deliver("FM-1 B>NET", [bytes([0x91, 64, 90])])       # ...not on NET as well
        midi.deliver("BT>NET", [bytes([0x92, 65, 90])])
        assert link.sent == [bytes([0x92, 65, 90])]
        midi.paused = True                                        # a flash: nothing in
        midi.fm1_net["A"].on_message([0x90, 61, 100])
        assert midi.usb.sent == []
        midi.paused = False
        sessions = dict(midi.fm1_net)
        midi.set_link_fm1s(["A"])
        assert list(midi.fm1_net) == ["A"] and sessions["B"].stopped and sessions["C"].stopped
        midi.set_link(False)
        assert midi.fm1_net == {} and sessions["A"].stopped
    finally:
        netmidi.Invitation = real


# ---------------------------------------------------------------- the link coming back by itself

def test_link_invites_again_after_a_studio_restart():
    """a Studio that started again has a new session that doesn't know the Pocket, yet answers its syncs: the
    Pocket sees the session id change and invites again (seen 2026-10-31: linked on the Pocket, gone on the Studio,
    so the Studio hid the Pocket's sound)"""
    import struct
    import time
    import netmidi
    studio = netmidi.Session("Studio", 15034, lambda m: None)
    assert studio.start()
    link = netmidi.Invitation(netmidi.LINK_NAME, lambda m: None, find=lambda: [("Studio", "127.0.0.1", 15034)])
    link.SYNC, link.RETRY = 0.2, 0.2
    try:
        assert link.start()
        end = time.monotonic() + 5
        while not studio.names() and time.monotonic() < end:
            time.sleep(0.05)
        assert studio.names() == [netmidi.LINK_NAME] and link.peer["ssrc"] == studio.ssrc
        same = netmidi.SIGN + b"CK" + struct.pack(">IB3xQQQ", studio.ssrc, 1, 0, 0, 0)
        assert not link.restarted(studio.ssrc)
        link.received(same, True)
        assert link.peer is not None                              # its own session's sync: still linked
        with studio.lock:                                         # the Studio restarted: a new session id, no peers
            studio.ssrc, studio.peers = studio.ssrc ^ 0x5A5A5A5A, {}
        end = time.monotonic() + 5
        while not studio.names() and time.monotonic() < end:
            time.sleep(0.05)
        assert studio.names() == [netmidi.LINK_NAME] and link.peer["ssrc"] == studio.ssrc   # invited again
    finally:
        link.stop()


def test_loopback_left_unlinked_restarts():
    """a loopback whose playback side has no links while its sink is there (the link's sink started again with
    the same node id) is stopped, so the next ensure starts it afresh; linked, or just started, it's left alone"""
    class Proc:
        pid = 4321

        def __init__(self, *a, **k):
            self.alive = True

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.alive = False

        def wait(self, timeout=None):
            return 0
    real = bridge.subprocess.Popen, bridge.set_rate
    bridge.subprocess.Popen = lambda cmd, **k: Proc()
    bridge.set_rate = lambda rate: None

    def node(i, name):
        return {"type": "PipeWire:Interface:Node", "id": i, "info": {"props": {"node.name": name}}}
    fm1, sink = "alsa_input.usb-Felucca-00.analog-stereo", "fm1-studio-link"
    out = node(70, "output.pw-loopback-4321")                    # (pw-loopback's own name for its playback side)
    link = {"type": "PipeWire:Interface:Link", "id": 80, "info": {"output-node-id": 70, "input-node-id": 61}}
    try:
        loop = bridge.Loopback()
        loop.ensure(fm1, sink)
        assert not loop.follow([node(60, fm1), node(61, sink), out])             # ends noted
        assert not loop.follow([node(60, fm1), node(61, sink), out])             # just started: unlinked is fine
        loop.started -= 10
        assert not loop.follow([node(60, fm1), node(61, sink), out, link])       # linked
        assert not loop.follow([node(60, fm1), node(61, sink), out])             # unlinked once: wait and see
        assert loop.follow([node(60, fm1), node(61, sink), out]) and not loop.running()   # twice: started again
        named = bridge.Loopback()                                                # a mixer channel's: by its name
        named.ensure(fm1, sink, "fm1-net-a")
        named.started -= 10
        objects = [node(60, fm1), node(61, sink), node(71, "fm1-net-a")]
        assert not named.follow(objects) and not named.follow(objects) and named.follow(objects)
    finally:
        bridge.subprocess.Popen, bridge.set_rate = real


if __name__ == "__main__":
    server = setup()
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
