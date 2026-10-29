"""fm1map.py: any MIDI controller's controls learnt onto the FM-1's, sent as FM-1 A's REMOTE OUT sends them.

  python tests/test_fm1map.py
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fm1-bt-bridge"))
import fm1map  # noqa: E402

PORT = "MPK mini IV:MPK mini IV MIDI 1 28:0"


def mapper():
    return fm1map.Mapper(Path(tempfile.mkdtemp()))


def test_the_panel():
    """the FM-1's controls by name; the keys from F, the sharps where the FM-1 has its raised keys (3, 2, 3, 2, 1)"""
    assert len(fm1map.controls()) == 14 + 7 + 1 + 27
    assert fm1map.name("btn:10") == "PLAY" and fm1map.name("knob:3") == "KNOB 1" and fm1map.name("master") == "MASTER"
    assert fm1map.name("key:0") == "KEY F3" and fm1map.name("key:26") == "KEY G5"
    sharps = [k for k in range(27) if fm1map.black(k)]
    assert len(sharps) == 11
    runs, run = [], [sharps[0]]
    for a, b in zip(sharps, sharps[1:]):
        if b - a <= 2:
            run.append(b)
        else:
            runs.append(len(run))
            run = [b]
    assert runs + [len(run)] == [3, 2, 3, 2, 1]


def test_learn_and_play():
    """a pad onto PLAY, a CC button onto REC, a pad onto a key, a knob that sends where it is onto KNOB 1, an
    endless one onto SELECT, a fader onto MASTER: each played as FM-1 A's panel, only while an app runs"""
    m, sent = mapper(), []
    m.learn("btn:10")
    assert m.handle(PORT, [0x99, 40, 90], False, sent.append)          # learning: taken, whatever runs
    assert m.learning is None and m.heard == "PLAY = MPK mini IV: NOTE 40 CH 10" and m.count == 1
    m.learn("btn:11")
    m.handle(PORT, [0xB0, 20, 0], False, sent.append)
    m.handle(PORT, [0xB0, 20, 127], False, sent.append)                # a CC up from 0: a button
    m.learn("key:5")
    m.handle(PORT, [0x99, 41, 100], False, sent.append)
    m.learn("knob:3")
    for v in (60, 61, 62, 63):                                         # a knob going one way: where it is
        m.handle(PORT, [0xB0, 70, v], False, sent.append)
    m.learn("knob:0")
    for v in (1, 1, 127, 1):                                           # steps: an endless knob
        m.handle(PORT, [0xB0, 71, v], False, sent.append)
    m.learn("master")
    for v in (10, 40, 80, 120):
        m.handle(PORT, [0xB0, 7, v], False, sent.append)
    assert sent == [] and m.count == 6
    assert m.status()["map"]["knob:0"] == "MPK mini IV: CC 71 CH 1"

    assert not m.handle(PORT, [0x99, 40, 90], False, sent.append)      # no app running: plays as it always does
    play = lambda msg: m.handle(PORT, msg, True, sent.append)           # noqa: E731
    play([0x99, 40, 90])
    play([0x89, 40, 0])
    play([0xB0, 20, 127])
    play([0x99, 41, 100])
    play([0xB0, 70, 63])                                               # (first: where it is, no turn yet)
    play([0xB0, 70, 66])                                               # 3 of its values: 3 exact steps
    play([0xB0, 71, 127])
    play([0xB0, 7, 99])
    time.sleep(fm1map.TAP + 0.1)                                       # REC never sent its 0: let go of after TAP
    assert sent == [[0xBF, 112, 127], [0xBF, 112, 0], [0xBF, 113, 127], [0x9F, 41, 100],
                    [0xBF, 88, 67], [0xBF, 85, 63], [0xBF, 123, 99], [0xBF, 113, 0]]
    assert not play([0x99, 50, 100])                                   # not mapped: not taken
    del sent[:]
    for v in (67, 68, 66):                                             # a value at a time, either way: a step each
        play([0xB0, 70, v])                                            # (CC 85 + knob: the apps' exact steps)
    assert sent == [[0xBF, 88, 65], [0xBF, 88, 65], [0xBF, 88, 62]]
    del sent[:]
    for v in (126, 127, 127, 127):                                     # an endless knob at its end, turned on: it
        play([0xB0, 70, v])                                            # sends 127 again, a step each time
    for v in (1, 0, 0):
        play([0xB0, 70, v])
    assert sent == [[0xBF, 88, 124], [0xBF, 88, 65], [0xBF, 88, 65], [0xBF, 88, 65],
                    [0xBF, 88, 1], [0xBF, 88, 63], [0xBF, 88, 63]]
    del sent[:]
    play([0xB0, 20, 0])                                                # it does let go after all: held as held
    play([0xB0, 20, 127])
    time.sleep(fm1map.TAP + 0.1)
    assert sent == [[0xBF, 113, 0], [0xBF, 113, 127]]


def test_one_job_each_saved_cleared():
    """a control of yours on one FM-1 control at a time; kept in the file; cleared; forgotten"""
    folder = Path(tempfile.mkdtemp())
    m = fm1map.Mapper(folder)
    m.learn("btn:0")
    m.handle(PORT, [0x99, 40, 90], False, lambda msg: None)
    m.learn("btn:1")
    m.handle(PORT, [0x99, 40, 90], False, lambda msg: None)            # the same pad: off FX, onto SEL
    assert set(m.status()["map"]) == {"btn:1"}
    m.learn("btn:2")
    m.handle("K.O. Sidekick:K.O. Sidekick MIDI 1 32:0", [0x90, 36, 90], False, lambda msg: None)
    again = fm1map.Mapper(folder)                                      # read back: by controller, its number gone
    assert set(again.maps) == {"MPK mini IV:MPK mini IV MIDI 1", "K.O. Sidekick:K.O. Sidekick MIDI 1"}
    again.clear("btn:1")
    assert set(fm1map.Mapper(folder).status()["map"]) == {"btn:2"}
    again.forget()
    assert fm1map.Mapper(folder).maps == {}


def test_centre_knobs_and_faders():
    """63 / 65 steps; pitch bend onto MASTER; a learn let go of"""
    m, sent = mapper(), []
    m.learn("knob:4")
    for v in (65, 65, 63, 65):
        m.handle(PORT, [0xB2, 9, v], False, sent.append)
    assert m.maps["MPK mini IV:MPK mini IV MIDI 1"][0]["how"] == "center"
    m.handle(PORT, [0xB2, 9, 61], True, sent.append)
    assert sent == [[0xBF, 89, 61]]
    m.learn("master")
    for v in (0, 30, 64, 100):
        m.handle(PORT, [0xE0, 0, v], False, sent.append)
    m.handle(PORT, [0xE0, 0, 127], True, sent.append)
    assert sent[-1] == [0xBF, 123, 127]
    m.learn("knob:5")                                                  # an MPK mini IV's relative knob speeding up
    for v in (1, 2, 3, 5):                                             # (as it sent them: not a knob going up)
        m.handle(PORT, [0xB0, 29, v], False, sent.append)
    m.learn("knob:6")
    for v in (127, 124, 119, 118):
        m.handle(PORT, [0xB0, 27, v], False, sent.append)
    hows = {b["control"]: b["how"] for b in m.maps["MPK mini IV:MPK mini IV MIDI 1"]}
    assert hows["knob:5"] == hows["knob:6"] == "twos"
    del sent[:]
    m.handle(PORT, [0xB0, 29, 13], True, sent.append)
    m.handle(PORT, [0xB0, 27, 119], True, sent.append)
    assert sent == [[0xBF, 90, 77], [0xBF, 91, 55]]
    m.learn("btn:3")
    m.learn(None)                                                      # tapped again: not learning
    assert not m.handle(PORT, [0x99, 60, 90], False, sent.append)


def test_a_controllers_other_ports():
    """the Studio opens a controller's other ports (an MPK mini IV's DAW port: PLAY, REC ... as CC 73-78, 127
    only) for the FM-1 map alone; the first port stays the routes'"""
    import blemidi
    import sloop
    was = sloop.fm1_cards
    sloop.fm1_cards = lambda: []
    try:
        c = blemidi.UsbControllers.__new__(blemidi.UsbControllers)
        c.fm1 = type("F", (), {"match": ("felucca",)})()
        names = ["Midi Through:Midi Through Port-0 14:0", "MPK mini IV:MPK mini IV MIDI Port 24:0",
                 "MPK mini IV:MPK mini IV DAW Port 24:1", "MPK mini IV:MPK mini IV Din Port 24:4",
                 "Felucca:Felucca MIDI 1 28:0"]
        assert c.wanted(names) == {"MPK mini IV": "MPK mini IV:MPK mini IV MIDI Port 24:0"}
        assert c.extras(names) == {"MPK mini IV:MPK mini IV DAW Port": "MPK mini IV:MPK mini IV DAW Port 24:1",
                                   "MPK mini IV:MPK mini IV Din Port": "MPK mini IV:MPK mini IV Din Port 24:4"}
    finally:
        sloop.fm1_cards = was
    m, sent = mapper(), []
    daw = "MPK mini IV:MPK mini IV DAW Port"
    m.learn("btn:10")
    m.handle(daw, [0xB0, 73, 127], False, sent.append)
    assert m.status()["map"]["btn:10"] == "MPK mini IV: CC 73 CH 1"
    m.handle(daw, [0xB0, 73, 127], True, sent.append)
    time.sleep(fm1map.TAP + 0.1)
    assert sent == [[0xBF, 112, 127], [0xBF, 112, 0]]


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
