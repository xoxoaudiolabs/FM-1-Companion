"""Tests for the Pocket's Studio link coming back by itself: a Studio that restarted is invited again, and a
loopback left linked to nothing is started again. No hardware: the network is this computer.

  python tests/test_link.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-link-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"),
                  FM1_SETTINGS=str(TMP / "settings.json"))

import bridge  # noqa: E402


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
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
