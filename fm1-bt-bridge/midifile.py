"""MIDI files (.mid) played into an FM-1: the library's midi folder (from the SD card's fm1-library/midi, or
uploaded on the web page).

A Standard MIDI File's tracks are merged at the file's own tempo (and its tempo changes), and only channel
messages are sent: notes, controllers, program changes, pitch bend. Left out: SysEx (a file can't rewrite an
FM-1's patches or settings), the file's own clock and Start/Stop, and meta events. Stopped, or at its end, every
note it left held is let go and the sustain pedal released.

The player runs in the MIDI process (blemidi.py), each message sent at a fixed time from the start (not "sleep
the gap"), so the tempo doesn't drift with how long sending takes.
"""
import threading
import time
from pathlib import Path

MAX_EVENTS = 200000                            # (a big orchestral file is ~50 000)
MAX_BYTES = 4 * 1024 * 1024
NOTE_OFF, NOTE_ON, CONTROL = 0x80, 0x90, 0xB0


class MidiFileError(Exception):
    pass


def load(path):
    """-> (events [(seconds from the start, message bytes)], length in seconds)"""
    import mido
    path = Path(path)
    try:
        if path.stat().st_size > MAX_BYTES:
            raise MidiFileError("too big for the box (4 MB at most)")
        mid = mido.MidiFile(str(path), clip=True)
    except MidiFileError:
        raise
    except Exception as e:                     # (mido's reader raises all sorts on a damaged file)
        raise MidiFileError(str(e)[:80] or "not a MIDI file")
    if mid.type == 2:
        raise MidiFileError("a type 2 file (separate songs in one): not played")
    events, now = [], 0.0
    try:
        for msg in mid:                       # every track merged; msg.time: seconds since the one before
            now += msg.time
            if msg.is_meta:
                continue
            data = bytes(msg.bytes())
            if not data or data[0] >= 0xF0:   # SysEx, clock, Start/Stop: not sent
                continue
            events.append((now, data))
            if len(events) > MAX_EVENTS:
                raise MidiFileError("too many notes for the box")
    except MidiFileError:
        raise
    except Exception as e:
        raise MidiFileError(str(e)[:80] or "a damaged MIDI file")
    return events, now


_described = {}                                # path -> ((size, mtime), what describe said): read once


def describe(path):
    """what the library lists for a file: {"seconds", "notes", "channels"}; MidiFileError if it can't be played.
    Kept per file until it changes (the library is listed often, and a big file takes a while on a Zero W)"""
    path = Path(path)
    try:
        stat = path.stat()
    except OSError as e:
        raise MidiFileError(str(e))
    key, seen = (stat.st_size, stat.st_mtime), _described.get(str(path))
    if seen and seen[0] == key:
        if isinstance(seen[1], MidiFileError):
            raise seen[1]
        return dict(seen[1])
    try:
        events, length = load(path)
    except MidiFileError as e:
        _described[str(path)] = (key, e)
        raise
    notes = sum(1 for _, m in events if m[0] & 0xF0 == NOTE_ON and len(m) > 2 and m[2])
    out = {"seconds": round(length, 1), "notes": notes, "channels": sorted({(m[0] & 0x0F) + 1 for _, m in events})}
    _described[str(path)] = (key, out)
    return dict(out)


class Player:
    """One file at a time, on a thread of its own. send(message bytes) is called on that thread."""

    def __init__(self, send, on_start=None, clock=time.monotonic):
        self.send, self.on_start, self.clock = send, on_start, clock
        self.thread, self.stopping, self.now = None, threading.Event(), None

    def play(self, events, name, length, loop=False):
        self.stop()
        self.stopping = threading.Event()
        self.now = {"name": name, "length": round(length, 1), "loop": bool(loop), "started": self.clock()}
        self.thread = threading.Thread(target=self.run, args=(events, length, loop, self.stopping, self.now),
                                       daemon=True, name="fm1-midifile")
        self.thread.start()

    def stop(self):
        if self.thread:
            self.stopping.set()
            self.thread.join(2.0)
            self.thread = None
        self.now = None

    def playing(self):
        return self.now is not None

    def status(self):
        """{"name", "length", "loop", "pos"} while a file plays, else None"""
        now = self.now
        if not now:
            return None
        return dict({k: v for k, v in now.items() if k != "started"},
                    pos=round(min(now["length"], max(0.0, self.clock() - now["started"])), 1))

    def run(self, events, length, loop, stopping, now):
        if self.on_start:
            self.on_start()                   # (the MIDI process: a real-time thread, like the box clock)
        held, channels = set(), set()
        try:
            start = self.clock()
            now["started"] = start
            while not stopping.is_set():
                for at, message in events:
                    wait = start + at - self.clock()
                    if wait > 0 and stopping.wait(wait):
                        return
                    if stopping.is_set():
                        return
                    self.send(message)
                    kind, channel = message[0] & 0xF0, message[0] & 0x0F
                    channels.add(channel)
                    if kind == NOTE_ON and len(message) > 2 and message[2]:
                        held.add((channel, message[1]))
                    elif kind in (NOTE_OFF, NOTE_ON) and len(message) > 1:
                        held.discard((channel, message[1]))
                if not loop:
                    return
                start += max(length, 0.05)    # (an empty file looping: not a busy loop)
                now["started"] = start
        finally:
            for channel, note in sorted(held):    # nothing left sounding
                self.send(bytes([NOTE_OFF | channel, note, 0]))
            for channel in sorted(channels):
                self.send(bytes([CONTROL | channel, 64, 0]))      # the sustain pedal up
            if self.now is now:
                self.now = None
