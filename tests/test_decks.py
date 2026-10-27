"""Tests for the DJ decks (decks.py) and their music folder's scan (djlib.py), on made-up tracks: no sound card,
no controller, no music files.

  python tests/test_decks.py
"""
import base64
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))

import numpy as np  # noqa: E402

import decks  # noqa: E402
import djlib  # noqa: E402

RATE = 44100


class Track(decks.Track):
    """a made-up track: a 220 Hz tone with a click on each beat"""

    def __init__(self, bpm=140.0, seconds=30, first_beat=0.0, rel="t.mp3"):
        t = np.arange(int(seconds * RATE)) / RATE
        x = np.sin(2 * np.pi * 220 * t) * 6000 * (((t - first_beat) * bpm / 60) % 1 < 0.05)
        self.audio, self.rate = np.stack([x, x], 1).astype(np.int16), RATE
        self.path, self.rel = Path(rel), rel
        self.title, self.artist, self.bpm, self.key, self.first_beat = rel, "", bpm, "Am", first_beat
        self.cues, self.cue_colors, self.overview = {}, {}, []


class Message:
    def __init__(self, b):
        self.b = b

    def bytes(self):
        return self.b


def test_sync_locks_tempo_and_beat():
    e = decks.Engine()
    a, b = e.decks
    a.load(Track(140.0))
    b.load(Track(139.6, first_beat=0.13))       # a tag a little off, its grid elsewhere
    a.play_pause(b)
    b.play_pause(a)
    b.toggle_sync(a)
    for _ in range(400):
        e.render()
    assert abs(b.bpm_now() - a.bpm_now()) < 0.01 and abs(b.phase_error(a)) < 0.01
    a.pitch = a.fader = 0.25                    # the other deck's tempo moves: it follows
    e.render()
    assert abs(b.bpm_now() - a.bpm_now()) < 0.01
    b.toggle_sync(a)                            # off: back to its own fader
    e.render()
    assert not b.synced and abs(b.bpm_now() - 139.6) < 0.01


def test_sync_double_and_half_tempo():
    e = decks.Engine()
    a, b = e.decks
    a.load(Track(140.0))
    b.load(Track(70.0))                          # (a 140 BPM track tagged 70)
    a.pitch = a.fader = -0.5
    b.toggle_sync(a)
    e.render()
    assert abs(b.bpm_now() * 2 - a.bpm_now()) < 0.01


def test_synced_faders_lead():
    e = decks.Engine()
    h = decks.Hercules(e)
    a, b = e.decks
    a.load(Track(140.0))
    b.load(Track(138.0))
    a.toggle_sync(b)
    b.toggle_sync(a)
    h.message(Message([0xB2, 8, 30]))            # deck B's tempo fader: B leads, A follows
    for _ in range(3):
        e.render()
    assert e.leader == 1 and abs(a.bpm_now() - b.bpm_now()) < 0.01 and b.bpm_now() != 138.0


def test_tempo_fader_up_is_slower():
    e = decks.Engine()
    h = decks.Hercules(e)
    e.decks[0].load(Track(140.0))
    h.message(Message([0xB1, 8, 127]))           # all the way up (what the MK2 sends there)
    assert e.decks[0].bpm_now() < 130
    h.message(Message([0xB1, 8, 0]))             # all the way down
    assert e.decks[0].bpm_now() > 150


def test_cue_like_a_cdj():
    d = decks.Deck("A")
    d.load(Track())
    d.pos = 2.0 * RATE
    d.cue_press(True)                            # stopped: the cue here, playing while held
    assert d.playing and abs(d.cue - 2.0 * RATE) < 1
    d.cue_press(False)                           # let go: back to it, stopped
    assert not d.playing and d.pos == d.cue
    d.cue_press(True)
    d.play_pause()                               # PLAY while CUE is held: it plays on
    d.cue_press(False)
    assert d.playing


def test_hot_cues_set_jump_delete():
    d = decks.Deck("A")
    d.load(Track())
    d.pos = 5.0 * RATE
    d.hotcue(1, True)                            # not set yet: set here
    d.hotcue(1, False)
    d.pos = 9.0 * RATE
    d.playing = True
    d.hotcue(1, True)                            # set: jumps there
    assert abs(d.pos - 5.0 * RATE) < 1
    d.hotcue(1, True, clear=True)                # SHIFT + pad
    assert 1 not in d.track.cues


def test_loops_and_rolls():
    e = decks.Engine()
    d = e.decks[0]
    d.load(Track(120.0))
    d.play_pause()
    d.loop_in()                                  # 4 beats from the nearest beat
    for _ in range(300):
        e.render()
    start, end = d.loop
    assert abs((end - start) - 4 * 0.5 * RATE) < 2 and start <= d.pos < end
    d.loop_size(0.5)
    assert abs((d.loop[1] - d.loop[0]) - 2 * 0.5 * RATE) < 2
    d.loop_out()
    assert d.loop is None
    before = d.pos
    d.roll_pad(1, True)                          # a 1-beat roll held, then let go: on as if it had played through
    for _ in range(200):
        e.render()
    d.roll_pad(1, False)
    assert d.loop is None and abs(d.pos - (before + 200 * decks.BLOCK * d.speed())) < 2


def test_jog_stops_at_the_ends():
    d = decks.Deck("A")
    d.load(Track(seconds=10))
    for _ in range(5000):
        d.jog_top(1)
    assert d.pos == d.track.frames - 1
    for _ in range(5000):
        d.jog_top(-1)
    assert d.pos == 0.0
    assert not d.vinyl                           # the decks start with VINYL off


def test_eq_and_filter():
    t = np.arange(10 * RATE) / RATE
    tone = (np.sin(2 * np.pi * 100 * t) + np.sin(2 * np.pi * 5000 * t)) * 8000

    def bands(**knobs):
        e = decks.Engine()
        d = e.decks[0]
        tr = Track()
        tr.audio = np.stack([tone, tone], 1).astype(np.int16)
        d.load(tr)
        d.volume, e.xfade = 1.0, 0.0
        d.play_pause()
        for k, v in knobs.items():
            setattr(d.tone, k, v)
        m = np.concatenate([e.render()[0] for _ in range(40)][4:])
        f, fr = np.abs(np.fft.rfft(m[:, 0])), np.fft.rfftfreq(len(m), 1 / RATE)
        return f[(fr > 80) & (fr < 120)].max(), f[(fr > 4900) & (fr < 5100)].max()
    low, high = bands()
    assert bands(low=0.0)[0] < low * 0.1 and bands(high=0.0)[1] < high * 0.1
    assert bands(filter=0.05)[1] < high * 0.01 and bands(filter=0.95)[0] < low * 0.01


def test_limiter_leaves_quiet_sound_alone():
    x = np.linspace(-0.8, 0.8, 100).astype(np.float32)
    assert np.array_equal(decks.limit(x), x)
    y = decks.limit(np.array([3.0, -3.0], np.float32))
    assert (np.abs(y) <= 1.0).all() and (np.abs(y) > 0.9).all()          # (never past full scale)


def test_cue_memory_over_tags():
    folder = Path(tempfile.mkdtemp())
    D = decks.Decks.__new__(decks.Decks)         # (no library, no sound: the memory alone)
    D.engine, D.folder, D.cursor, D.library, D.saved = decks.Engine(), folder, 0, [], None
    D.memory = {"tracks": {}, "session": {}}
    d = D.engine.decks[0]
    tr = Track(rel="song.mp3")
    tr.cues, tr.cue_colors = {0: 1.0 * RATE, 2: 3.0 * RATE}, {0: "#ff0000", 2: "#00ff00"}   # (Serato's)
    d.load(tr)
    d.hotcue(0, True, clear=True)                # one of Serato's deleted here, a new one set
    d.pos = 7.0 * RATE
    d.hotcue(3, True)
    D.save_memory()
    D2 = decks.Decks.__new__(decks.Decks)
    D2.folder = folder
    D2.memory = D2.read_memory()
    again = Track(rel="song.mp3")
    again.cues = {0: 1.0 * RATE, 2: 3.0 * RATE}
    again.cue_colors = {}
    D2.remembered(again)
    assert sorted(again.cues) == [2, 3] and abs(again.cues[3] - 7.0 * RATE) < 1
    assert D2.memory["session"]["decks"][0]["rel"] == "song.mp3"


def id3(frames):
    """a minimal ID3v2.3 tag: [(frame id, body)]"""
    body = b"".join(fid.encode() + struct.pack(">I", len(b)) + b"\0\0" + b for fid, b in frames)
    n = len(body)
    return b"ID3\x03\x00\x00" + bytes([(n >> 21) & 127, (n >> 14) & 127, (n >> 7) & 127, n & 127]) + body


def test_tags_read_serato():
    entry = b"CUE\0" + struct.pack(">I", 13 + 6) + b"\x00\x01" + struct.pack(">I", 12345) + b"\x00\xcc\x00\x00" + \
        b"\x00\x00" + b"DROP\0"
    markers = b"\x01\x01" + base64.b64encode(b"\x01\x01" + entry) + b"\0"
    grid = b"\x01\x00" + struct.pack(">I", 1) + struct.pack(">f", 0.25) + struct.pack(">f", 140.0) + b"\0"
    geob = lambda desc, data: b"\x00application/octet-stream\0\0" + desc + b"\0" + data   # noqa: E731
    tag = id3([("TIT2", b"\x00Test Song"), ("TPE1", b"\x00Someone"), ("TKEY", b"\x009m"),
               ("GEOB", geob(b"Serato Autotags", b"\x01\x01140.00\x00")),
               ("GEOB", geob(b"Serato Markers2", markers)), ("GEOB", geob(b"Serato BeatGrid", grid))])
    path = Path(tempfile.mkdtemp()) / "t.mp3"
    path.write_bytes(tag + b"\xff\xfb" + bytes(400))
    t = djlib.read_tags(path)
    assert (t["title"], t["artist"], t["bpm"], t["key"]) == ("Test Song", "Someone", 140.0, "Fm")
    assert t["cues"] == [{"index": 1, "ms": 12345, "color": "#cc0000", "name": "DROP"}]
    assert t["first_beat"] == 0.25 and djlib.camelot("Fm") == "4A"


def test_keys_named():
    assert [djlib.norm_key(k) for k in ("Am", "A min", "Db", "C#m", "8A", "8B", "1d", "9m", "x")] == \
        ["Am", "Am", "C#", "C#m", "Am", "C", "C", "Fm", None]


def test_detect_bpm_and_key():
    sr = 11025
    t = np.arange(int(40 * sr)) / sr
    kick = np.sin(2 * np.pi * 55 * t) * np.exp(-((t * 128 / 60) % 1) * 30)       # a kick on every beat at 128
    chord = sum(np.sin(2 * np.pi * f * t) for f in (220.0, 261.63, 329.63)) * 0.2   # A minor
    bpm = djlib.detect_bpm((kick + chord).astype(np.float32), sr)
    assert abs(bpm - 128) < 0.5
    assert djlib.detect_key((kick * 0.2 + chord).astype(np.float32), sr) in ("Am", "C")


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
