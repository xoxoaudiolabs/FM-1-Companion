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


def test_usb_drives_found():
    """lsblk's tree: a USB stick's partition and a whole-disk filesystem found, the SD card and a USB drive with no
    filesystem we mount left out"""
    tree = {"blockdevices": [
        {"path": "/dev/mmcblk0", "fstype": None, "tran": "mmc", "children": [
            {"path": "/dev/mmcblk0p2", "fstype": "ext4", "uuid": "r00t", "mountpoint": "/"}]},
        {"path": "/dev/sda", "fstype": None, "tran": "usb", "children": [
            {"path": "/dev/sda1", "fstype": "exfat", "label": "DJ STICK", "uuid": "1234-ABCD",
             "mountpoint": "/media/fm1/DJ STICK"},
            {"path": "/dev/sda2", "fstype": "swap", "uuid": "5w4p", "mountpoint": None}]},
        {"path": "/dev/sdb", "fstype": "vfat", "label": None, "uuid": "AAAA-0001", "tran": "usb", "mountpoint": None}]}
    found = djlib.usb_volumes(tree)
    assert [(v["path"], v["label"], v["mountpoint"]) for v in found] == [
        ("/dev/sda1", "DJ STICK", "/media/fm1/DJ STICK"), ("/dev/sdb", "", None)]
    flat = {"blockdevices": [                             # (util-linux 2.41 on the Studio: a list, no tree)
        {"path": "/dev/sda", "pkname": None, "fstype": None, "uuid": None, "mountpoint": None, "tran": "usb"},
        {"path": "/dev/sda1", "pkname": "/dev/sda", "fstype": "ntfs", "label": "Zine", "uuid": "5C22CDF222CDD166",
         "mountpoint": None, "tran": None},
        {"path": "/dev/mmcblk0p1", "pkname": "/dev/mmcblk0", "fstype": "vfat", "uuid": "0398-3084",
         "mountpoint": "/boot/firmware", "tran": None}]}
    assert [(v["path"], v["label"]) for v in djlib.usb_volumes(flat)] == [("/dev/sda1", "Zine")]


def test_usb_drive_listed_before_its_scan():
    """a drive's tracks all listed, scanned or not (a title from the file name till the scan), its hidden folders
    and macOS's ._ files left out"""
    drive = Path(tempfile.mkdtemp())
    (drive / "House").mkdir()
    for name in ("House/one.mp3", "two.flac", "._two.flac", ".Trashes/old.mp3", "cover.jpg"):
        (drive / name).parent.mkdir(parents=True, exist_ok=True)
        (drive / name).write_bytes(b"x")
    (drive / djlib.CACHE).write_text('{"two.flac": {"title": "Two", "artist": "Someone", "bpm": 140.0}}')
    found = djlib.listing(drive)
    assert sorted(found) == [str(Path("House/one.mp3")), "two.flac"]
    assert found["two.flac"]["bpm"] == 140.0 and found[str(Path("House/one.mp3"))] == {"title": "one", "artist": ""}


def test_usb_drive_plugged_in_and_out():
    """a drive plugged in: browsed, its tracks keyed by its UUID (their cues kept for that drive), loadable; pulled
    out: back to the Studio's music; the source button goes between them"""
    home, drive = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
    (home / djlib.CACHE).write_text('{"a.mp3": {"title": "A"}}')
    (home / "a.mp3").write_bytes(b"x")
    (drive / "b.mp3").write_bytes(b"x")
    plugged = []
    was = djlib.usb_music
    djlib.usb_music = lambda tried=None: list(plugged)
    try:
        D = decks.Decks.__new__(decks.Decks)
        D.folder, D.sources, D.source, D.tried, D.cursor = home, [{"name": "STUDIO", "folder": home, "uuid": None}], \
            0, {}, 0
        D.listings, D.waiting, D.engine = {}, [], decks.Engine()
        said, notes = [], []
        D.say, D.note = said.append, notes.append
        D.refresh()
        assert [k for k, _e in D.library] == ["a.mp3"]
        plugged.append({"name": "DJ STICK", "folder": drive, "uuid": "1234-ABCD"})
        D.watch_drives(once=True)
        assert D.source == 1 and [k for k, _e in D.library] == ["usb:1234-ABCD/b.mp3"]
        assert said[-1]["library"][0][:2] == ["usb:1234-ABCD/b.mp3", "b"] and "DJ STICK" in notes[-1]
        assert D.path_of("usb:1234-ABCD/b.mp3") == drive / "b.mp3" and D.path_of("a.mp3") == home / "a.mp3"
        assert D.entry_of("usb:1234-ABCD/b.mp3") == ("usb:1234-ABCD/b.mp3", {"title": "b", "artist": ""})
        (home / ".usb").mkdir()                            # its scan kept on the Studio (the drive: read-only)
        (home / ".usb" / "1234-ABCD.json").write_text('{"b.mp3": {"title": "Bee", "bpm": 174.0}}')
        D.refresh()
        assert D.library[0][1].get("bpm") is None             # (the drive walked once: not again till a scan)
        D.listings.pop("1234-ABCD")                          # (what a scan's end does)
        D.refresh()
        assert D.library[0][1]["bpm"] == 174.0 and D.entry_of("usb:1234-ABCD/b.mp3")[1]["title"] == "Bee"
        D.scanning = None
        D.hercules = type("H", (), {"lights": lambda self: None})()
        D.maps, D.inputs, D.learner = {}, [], None
        D.command(["source"], said.append)                 # the button: the Studio's again, then the drive
        assert D.source == 0 and [k for k, _e in D.library] == ["a.mp3"]
        D.command(["source"], said.append)
        assert D.source == 1
        plugged.clear()
        D.watch_drives(once=True)
        assert D.source == 0 and len(D.sources) == 1 and "gone" in notes[-1]
        assert D.path_of("usb:1234-ABCD/b.mp3") is None and D.entry_of("usb:1234-ABCD/b.mp3") is None
        D.sources, D.source = D.sources[:1], 1                 # (the list shrunk, the index not fixed yet:
        assert D.status()["source"] == "STUDIO"               #  another thread's reading is still good)
        D.source = 0
        D.memory = {"session": {"decks": [{"rel": "usb:1234-ABCD/b.mp3", "pos": 3.0}, None]}}
        D.loads = decks.queue.Queue()
        D.restore()                                          # the last session's drive track: waits for it
        assert D.loads.empty() and [i for i, _s in D.waiting] == [0]
        plugged.append({"name": "DJ STICK", "folder": drive, "uuid": "1234-ABCD"})
        D.watch_drives(once=True)                            # plugged in: loaded on deck A, where it was
        deck, found, state = D.loads.get_nowait()
        assert deck == 0 and found[0] == "usb:1234-ABCD/b.mp3" and state["pos"] == 3.0 and not D.waiting
    finally:
        djlib.usb_music = was


def test_usb_drive_mounted_again_after_a_quick_replug():
    """a drive mounted, pulled out and put back between two looks: mounted again; one whose mount failed isn't
    tried again till it's been seen gone"""
    looks, mounts = [], []
    was = djlib.usb_volumes, djlib.mount
    vol = lambda at: [{"path": "/dev/sda1", "label": "Zine", "uuid": "5C22", "mountpoint": at}]   # noqa: E731
    djlib.usb_volumes = lambda tree=None: looks.pop(0)
    djlib.mount = lambda path: mounts.append(path) or ok[0]
    try:
        tried, ok = {}, [True]
        looks[:] = [vol(None), vol("/media/fm1/Zine")]
        assert [d["name"] for d in djlib.usb_music(tried)] == ["Zine"] and tried == {}
        looks[:] = [vol(None), vol("/media/fm1/Zine")]       # (pulled out and back in: its mount gone)
        assert [d["name"] for d in djlib.usb_music(tried)] == ["Zine"] and len(mounts) == 2
        ok[0] = False
        looks[:] = [vol(None), vol(None)]
        assert djlib.usb_music(tried) == [] and tried == {"/dev/sda1": False}
        looks[:] = [vol(None)]                                # (failed: not tried again while it stays in)
        assert djlib.usb_music(tried) == [] and len(mounts) == 3
    finally:
        djlib.usb_volumes, djlib.mount = was


def learn_through(L, b, now):
    """a message to a Learner: -> whether it taught the step"""
    return L.hear(b, now)


def test_midi_learn_guided():
    """the guided run: a 14-bit crossfader, a browse knob, SHIFT, PLAY, a CC button, a tempo fader on pitch bend,
    a jog (63 / 65), a hot cue with and without SHIFT; SKIP and BACK; what's learnt then played on the decks"""
    L = decks.Learner("Any DJ 1", [], True)
    now = 100.0
    assert L.action == "xfade"
    for v in (10, 40, 70, 100):                                   # CC 8 + its fine half CC 40
        taught = learn_through(L, [0xB0, 8, v], now) or learn_through(L, [0xB0, 40, 5], now)
    assert taught and L.heard == "CC 8+40 CH 1"
    L.next()
    assert L.action == "browse"
    assert not learn_through(L, [0xB0, 9, 1], now + 0.1)           # (still quiet: the crossfader let go)
    for v in (1, 1, 127, 1):
        taught = learn_through(L, [0xB0, 9, v], now + 1)
    assert taught and L.bound("browse")["rel"] == "twos"
    L.next()
    assert L.action == "a.shift" and learn_through(L, [0x91, 4, 127], now + 2)
    L.next()
    assert L.action == "a.play"
    assert not learn_through(L, [0x91, 7, 0], now + 3)              # a note-off isn't a press
    assert learn_through(L, [0x91, 7, 127], now + 3)
    L.next()
    assert learn_through(L, [0xB1, 20, 127], now + 4)               # a.cue: a CC button
    L.next(2)                                                       # SKIP sync
    assert L.action == "a.load"
    L.next(-1)                                                      # BACK
    assert L.action == "a.sync"
    while L.action != "a.pitch":
        L.next()
    for v in (0, 30, 60, 90):
        taught = learn_through(L, [0xE1, 0, v], now + 5)
    assert taught and L.bound("a.pitch")["type"] == "pb"
    while L.action != "a.jog":
        L.next()
    assert not learn_through(L, [0x91, 30, 127], now + 6)           # (a jog's touch note: not the jog)
    for v in (65, 65, 63, 65):
        taught = learn_through(L, [0xB1, 31, v], now + 6)
    assert taught and L.bound("a.jog")["rel"] == "center"
    while L.action != "a.hot1":
        L.next()
    assert learn_through(L, [0x91, 40, 127], now + 7)
    L.next()
    learn_through(L, [0x91, 4, 127], now + 8)                       # SHIFT held ...
    assert learn_through(L, [0x91, 41, 127], now + 8)               # ... + a pad: a.hot2 is SHIFT + it
    assert L.bound("a.hot2")["shift"] is True and L.heard == "SHIFT + NOTE 41 CH 2"
    learn_through(L, [0x91, 4, 0], now + 9)
    while L.action != "b.play":
        L.next()
    assert learn_through(L, [0x91, 7, 127], now + 10)               # A's PLAY taught to B: moved (one job each)
    assert L.bound("b.play") and L.bound("a.play") is None
    L.next(len(decks.LEARN))
    assert L.action is None

    e = decks.Engine()
    loads, steps = [], []
    m = decks.Learned(e, L.binds, steps.append, loads.append)
    a, b = e.decks
    a.track = Track()
    m.message([0xB0, 8, 127])
    m.message([0xB0, 40, 127])
    assert e.xfade == 1.0
    m.message([0xB0, 9, 127])
    assert steps == [-1]
    m.message([0xE1, 0, 64])                                       # the tempo fader at the middle: no change
    assert abs(a.pitch) < 0.01
    m.message([0xB1, 31, 66])                                       # the jog, untouched, stopped: moves through
    assert a.pos > 0                                                # (66 on a 63 / 65 jog: 2 steps on)
    m.message([0x91, 40, 127])                                      # hot cue 1 set
    assert 0 in a.track.cues
    m.message([0x91, 41, 127])                                      # (pad 41 alone: nothing, it's SHIFT's)
    assert 1 not in a.track.cues
    m.message([0xB1, 20, 127])                                      # CUE (a CC): down then up
    assert a.cue_held
    m.message([0xB1, 20, 0])
    assert not a.cue_held


def test_midi_learn_on_the_decks():
    """LEARN through the Decks: a new controller's map learnt, saved beside the music, played; one control
    relearnt from the list, one cleared; the map forgotten"""
    folder = Path(tempfile.mkdtemp())
    D = decks.Decks.__new__(decks.Decks)
    D.engine, D.folder, D.maps, D.ports, D.inputs, D.learner = decks.Engine(), folder, {}, {}, ["Any DJ 1"], None
    D.hercules = decks.Hercules(D.engine)
    D.browse = D.load_selected = lambda *a: None
    D.note = lambda text: None
    D.command(["learn", "Any DJ 1", True], lambda m: None)
    assert D.wanted_ports() == {"Any DJ 1"}                         # opened while it's learnt
    D.learner.next(2)                                               # to A's SHIFT
    D.received("Any DJ 1", Message([0x90, 1, 127]))
    assert D.learner.action == "a.play" and "Any DJ 1" in D.maps    # learnt, and on to the next
    assert djlib.learned(folder)["Any DJ 1"][0]["action"] == "a.shift"   # saved at once
    D.learner.quiet = 0
    D.received("Any DJ 1", Message([0x90, 2, 127]))                 # PLAY
    D.command(["learn_done"], lambda m: None)
    st = D.learn_status()
    assert st["action"] is None and ["a.play", "A", "PLAY", "NOTE 2 CH 1"] in st["map"]
    a = D.engine.decks[0]
    a.track = Track()
    D.received("Any DJ 1", Message([0x90, 2, 127]))                 # the list showing: the map plays
    assert a.playing
    D.command(["learn", "Any DJ 1", False, "a.pfl"], lambda m: None)   # one control from the list
    assert D.learner.action == "a.pfl" and not D.learner.guided
    D.received("Any DJ 1", Message([0x90, 3, 127]))
    assert D.learner.action is None                                 # done: the list again
    D.received("Any DJ 1", Message([0x90, 3, 127]))
    assert a.pfl
    D.command(["learn_clear", "a.play"], lambda m: None)
    assert "a.play" not in {b["action"] for b in djlib.learned(folder)["Any DJ 1"]}
    D.command(["learn_end"], lambda m: None)
    assert D.learner is None
    D2 = decks.Decks.__new__(decks.Decks)                           # read back by a new run
    D2.engine, D2.folder, D2.maps = decks.Engine(), folder, {}
    D2.browse = D2.load_selected = lambda *a: None
    D2.load_maps()
    assert {b["action"] for b in D2.maps["Any DJ 1"].binds} == {"a.shift", "a.pfl"}
    import blemidi
    was, djlib.MUSIC = djlib.MUSIC, folder                          # the MIDI routes leave it to the decks
    try:
        assert blemidi.dj_learned("Any DJ 1 28:0") and not blemidi.dj_learned("SMK-37+VA:SMK-37+VA MIDI 1 20:0")
    finally:
        djlib.MUSIC = was
    D.command(["learn_list", "Any DJ 1"], lambda m: None)
    D.command(["learn_forget"], lambda m: None)
    assert djlib.learned(folder) == {} and D.maps == {}
    herc = "DJControl Inpulse 200 MK2:DJControl Inpulse 200 MK2 MIDI 1"
    D.received(herc, Message([0x91, 12, 127]))                      # the Hercules, no map: its own (PFL on A)
    assert D.engine.decks[0].pfl is False                           # (A's PFL was on: toggled off)
    assert decks.Decks.learnable("Midi Through:Midi Through Port-0") is False
    assert djlib.port_base("DJControl Inpulse 200 MK2:DJControl Inpulse 200 MK2 MIDI 1 24:0")         == "DJControl Inpulse 200 MK2:DJControl Inpulse 200 MK2 MIDI 1"


def test_decks_out():
    """DJ decks out: STUDIO (the default) where the Studio plays (no target: PipeWire's default, the DECKS channel
    of its mixer), HERCULES its master out (channels 1-2); its headphones the cue either way; changed while running"""
    made = []
    was_sinks, was_stream = decks.sinks, decks.Output.stream
    decks.sinks = lambda: ("alsa_output.usb-Guillemot_DJControl_Inpulse_200_Mk2", "bluez_output.jbl")
    decks.Output.stream = lambda self, node, label, ch, target, cmap: made.append((node, target, cmap)) or object()
    try:
        decks.Output()
        decks.Output("hercules")
        decks.sinks = lambda: (None, None)
        decks.Output("hercules")                                   # no Hercules: where the Studio plays
    finally:
        decks.sinks, decks.Output.stream = was_sinks, was_stream
    herc = "alsa_output.usb-Guillemot_DJControl_Inpulse_200_Mk2"
    assert made == [("fm1-decks", None, None), ("fm1-decks-cue", herc, "RL,RR"),
                    ("fm1-decks", herc, "FL,FR"), ("fm1-decks-cue", herc, "RL,RR"),
                    ("fm1-decks", None, None)]
    D = decks.Decks.__new__(decks.Decks)
    D.engine, D.out_to, D.hercules, D.maps = decks.Engine(), "studio", decks.Hercules(decks.Engine()), {}
    D.command(["output", "hercules"], lambda m: None)
    assert D.out_to == "hercules"
    D.command(["output", "loud"], lambda m: None)                   # (not a way out: left as it was)
    assert D.out_to == "hercules"


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
