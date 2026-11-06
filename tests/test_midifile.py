"""Tests for MIDI file playback (midifile.py, and blemidi.py's play_file): reading a .mid, timing, stopping cleanly,
looping, and the file going to FM-1 A or B. No FM-1 needed (needs mido).

  python tests/test_midifile.py
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fm1-bt-bridge"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mido  # noqa: E402

import blemidi  # noqa: E402
import midifile  # noqa: E402
from test_midi import FakeUsb, make_bridge  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="fm1-midifile-"))


def write_song(path, bpm=240, beats=(0, 1, 2), channel=2, sysex=True):
    """a type 1 file: a tempo track, and a track of quarter notes (at 240 BPM: 0.25 s apart) with a program
    change and a SysEx first"""
    mid = mido.MidiFile(type=1, ticks_per_beat=96)
    head = mido.MidiTrack([mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0)])
    notes = mido.MidiTrack([mido.Message("program_change", channel=channel, program=5, time=0)])
    if sysex:
        notes.append(mido.Message("sysex", data=[0x43, 0x00, 0x09, 0x20], time=0))
    last = 0
    for beat in beats:
        notes.append(mido.Message("note_on", channel=channel, note=60 + beat, velocity=100, time=beat * 96 - last))
        notes.append(mido.Message("note_off", channel=channel, note=60 + beat, velocity=0, time=48))
        last = beat * 96 + 48
    mid.tracks += [head, notes]
    mid.save(str(path))
    return path


def test_load_and_describe():
    path = write_song(TMP / "song.mid")
    events, length = midifile.load(path)
    assert all(m[0] < 0xF0 for _, m in events)                    # no SysEx, no clock, no meta
    assert events[0][1] == bytes([0xC2, 5])
    ons = [(round(t, 3), m[1]) for t, m in events if m[0] == 0x92]
    assert ons == [(0.0, 60), (0.25, 61), (0.5, 62)], ons          # the file's tempo
    assert abs(length - 0.625) < 0.001
    assert midifile.describe(path) == {"seconds": 0.6, "notes": 3, "channels": [3]}
    assert midifile.describe(path) == {"seconds": 0.6, "notes": 3, "channels": [3]}   # (kept: read once)


def test_bad_files():
    bad = TMP / "bad.mid"
    bad.write_bytes(b"MThd nonsense")
    for path in (bad, TMP / "missing.mid"):
        try:
            midifile.describe(path)
            raise AssertionError(path)
        except midifile.MidiFileError:
            pass
    two = mido.MidiFile(type=2)
    two.tracks.append(mido.MidiTrack())
    two.save(str(TMP / "type2.mid"))
    try:
        midifile.load(TMP / "type2.mid")
        raise AssertionError("type 2 played")
    except midifile.MidiFileError as e:
        assert "type 2" in str(e)


def test_player_timing_and_end():
    sent = []
    player = midifile.Player(lambda m: sent.append((time.monotonic(), m)))
    events, length = midifile.load(write_song(TMP / "timed.mid"))
    start = time.monotonic()
    player.play(events, "timed.mid", length)
    assert player.status()["name"] == "timed.mid" and player.status()["length"] == 0.6
    time.sleep(0.85)
    assert not player.playing() and player.status() is None
    ons = [t - start for t, m in sent if m[0] == 0x92]
    assert len(ons) == 3 and all(abs(t - want) < 0.06 for t, want in zip(ons, (0.0, 0.25, 0.5))), ons
    assert sent[-1][1] == bytes([0xB2, 64, 0])                      # the sustain pedal up at the end


def test_stop_lets_go():
    """stopped mid-note: that note let go, nothing more sent"""
    sent = []
    player = midifile.Player(sent.append)
    events = [(0.0, bytes([0x90, 60, 100])), (5.0, bytes([0x80, 60, 0])), (5.0, bytes([0x90, 62, 100]))]
    player.play(events, "long.mid", 5.0)
    time.sleep(0.1)
    player.stop()
    assert sent == [bytes([0x90, 60, 100]), bytes([0x80, 60, 0]), bytes([0xB0, 64, 0])], sent
    assert player.status() is None


def test_loop():
    sent = []
    player = midifile.Player(sent.append)
    player.play([(0.0, bytes([0x90, 60, 100])), (0.05, bytes([0x80, 60, 0]))], "loop.mid", 0.1, loop=True)
    time.sleep(0.35)
    assert player.status()["loop"] is True
    player.stop()
    assert sum(1 for m in sent if m[0] == 0x90) >= 3, sent


def test_bridge_plays_into_fm1_b():
    """the MIDI process: a file into FM-1 B only, past the routes; nothing while an FM-1 is flashed; a file that
    can't be played said on the screen"""
    bridge = make_bridge()
    bridge.usb_b = FakeUsb()
    path = write_song(TMP / "b.mid", bpm=600, sysex=False)
    bridge.play_file(path, "FM-1 B")
    assert bridge.file_status()["dest"] == "FM-1 B"
    time.sleep(0.5)
    assert [m for m in bridge.usb_b.sent if m[0] == 0x92] and not bridge.usb.sent
    assert bridge.file_status() is None                            # played to its end
    bridge.paused = True
    before = len(bridge.usb.sent)
    bridge.play_file(path, "FM-1")
    time.sleep(0.4)
    assert len(bridge.usb.sent) == before
    bridge.paused = False
    bad = TMP / "bad2.mid"
    bad.write_bytes(b"not midi")
    count = bridge.ble_note[0]
    bridge.play_file(bad, "FM-1")
    assert bridge.ble_note[0] == count + 1 and "MIDI file" in bridge.ble_note[1]
    assert bridge.file_status() is None
    bridge.play_file(path, "nowhere")                              # (anything else: FM-1 A)
    assert bridge.file_dest == "FM-1"
    bridge.stop_file()
    assert blemidi.MidiProcess.stop_file                           # (the app's side has it too)


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
