#!/usr/bin/env python3
"""The Studio's DJ decks: two decks playing tracks from ~/fm1-library/Studio DJ Music or a USB drive (djlib.py's
scan: BPM, key, beatgrid, hot cues), played from a Hercules DJControl Inpulse 200 MK2 (or the DECKS screen).

Each deck: load (decoded whole into memory), play / pause, CUE (a CDJ's: paused, it sets the cue and plays while held;
playing, it goes back to the cue and stops), the tempo fader (+-8 %), the jog wheel (its top scratches while touched
in vinyl mode, its edge nudges the tempo), 4 hot cues (the track's Serato ones when it has them; SHIFT + pad clears
one), loops (4 beats on LOOP IN, LOOP OUT leaves it or goes back in, SHIFT halves or doubles), loop rolls on the pads
(1, 2, 4 or 8 beats while held, then on as if it had played through), SYNC (the other deck's tempo, and its beat
when both have a grid), gain, LOW and HIGH EQ, a filter (left low-pass, right high-pass, off in the middle), the
volume fader, PFL to the headphones, the crossfader.

The sound: the Hercules has its own sound card, 4 channels: the master on its first pair, the headphones on the
second. Its MASTER and HEADPHONES knobs work in its own hardware. Without it, the master goes to the Studio's speaker.

Runs as a process of its own (DeckProcess, like the sampler's), the engine rendering BLOCK frames with numpy: the
tempo by reading the track faster or slower (no key lock yet: a faster track sounds higher), the EQ and filter by
a gain on each frequency of a short spectrum, block by block (overlapped: no clicks)."""
import json
import math
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

import djlib

RATE, BLOCK = 44100, 512
FFT = 2 * BLOCK                               # the EQ's spectrum: 1024 points, half overlapped
PITCH_RANGE = 0.08                            # the tempo fader: +-8 %
SAMPLES_PER_TICK = 1.8 * RATE / 248           # a jog tick while scratching (a turn: 1.8 s, a 33 rpm record)
BEND_PER_TICK = 0.012                         # a tick of the jog's edge: the tempo 1.2 % off, easing back
HERCULES = "DJControl Inpulse 200"
CUE_COLORS = ("#cc0000", "#cc8800", "#3399ff", "#33cc33")   # a hot cue set here, by pad (Serato's keep their own)
MEMORY = ".studio-dj-memory.json"             # beside the music: each track's cues as set here, and the session
OVERVIEW = 220                                # a track's overview: this many columns (the DECKS screen's)


def np():
    import numpy
    return numpy


class Track:
    def __init__(self, path, entry=None, rel=None):
        self.path, entry = Path(path), entry or {}
        self.rel = rel or self.path.name          # its name in the folder (the memory's key)
        audio, rate = djlib.decode(self.path)
        if audio.shape[1] == 1:
            audio = np().repeat(audio, 2, axis=1)
        self.audio, self.rate = audio[:, :2].copy(), rate
        self.title = entry.get("title") or self.path.stem
        self.artist = entry.get("artist") or ""
        self.bpm = entry.get("bpm")
        self.key = entry.get("key")
        self.first_beat = entry.get("first_beat") or 0.0
        if self.bpm:
            self.first_beat += self.grid_fix()
        self.cues = {c["index"]: c["ms"] / 1000.0 * rate for c in entry.get("cues") or [] if c["index"] < 4}
        self.cue_colors = {c["index"]: c.get("color") for c in entry.get("cues") or [] if c["index"] < 4}
        n = np()                                 # its overview: the loudest of OVERVIEW stretches, 0..1
        mono = n.abs(self.audio[:, 0].astype(n.int32) + self.audio[:, 1])
        edges = n.linspace(0, len(mono), OVERVIEW + 1).astype(int)[:-1]
        peaks = n.maximum.reduceat(mono, edges) if len(mono) > OVERVIEW else n.zeros(OVERVIEW)
        top = max(1, int(peaks.max()))
        self.overview = [round(float(v) / top, 2) for v in peaks]

    def grid_fix(self, seconds=90.0, window=0.08):
        """seconds to move the beat grid so its lines sit on this track's kicks as decoded here (Serato's grid, or
        the scan's, can sit some ms off them: 20 ms between two tracks is a flam when they're synced): the kick
        onsets' offset from the grid lines over the first `seconds`, the strongest within +-`window`"""
        n = np()
        try:
            x, sr = djlib._mono(self.audio[:int(seconds * self.rate)], self.rate)
            _flux, low = djlib._onsets(x, sr)
        except (ValueError, MemoryError):
            return 0.0
        if len(low) < 100 or low.max() <= 0:
            return 0.0
        beat = 60.0 / self.bpm
        times = n.arange(len(low)) * 128 / sr + 512 / sr
        rel = ((times - self.first_beat) / beat + 0.5) % 1.0 - 0.5
        hist, edges = n.histogram(rel * beat, bins=64, range=(-window, window), weights=(low / low.max()) ** 2)
        if hist.max() <= 0:
            return 0.0
        k = int(n.argmax(hist))
        return float((edges[k] + edges[k + 1]) / 2)

    @property
    def frames(self):
        return len(self.audio)

    def beat_frames(self):
        """a beat, in the track's own frames"""
        return 60.0 / self.bpm * self.rate if self.bpm else self.rate / 2


class Tone:
    """a deck's EQ (LOW below ~250 Hz, HIGH above ~2.5 kHz: -inf .. +6 dB, flat in the middle) and filter (left:
    low-pass from 20 kHz down to 150 Hz; right: high-pass from 20 Hz up to 6 kHz), as a gain on each frequency of a
    1024-point spectrum, half-overlapped with a sqrt-Hann window (constant overlap-add: no seams)"""

    def __init__(self):
        n = np()
        self.win = n.sqrt(n.hanning(FFT + 1)[:FFT]).astype(n.float32)
        self.freqs = n.fft.rfftfreq(FFT, 1 / RATE)
        self.tail = n.zeros((BLOCK, 2), n.float32)
        self.prev = n.zeros((BLOCK, 2), n.float32)
        self.low, self.high, self.filter = 0.5, 0.5, 0.5
        self.curve, self.made = None, None

    @staticmethod
    def knob_gain(v):
        """an EQ knob 0..1: 0 kills, 0.5 flat, 1 +6 dB"""
        return (v / 0.5) ** 2 if v < 0.5 else 1.0 + (v - 0.5) * 2 * (10 ** (6 / 20) - 1)

    def gains(self):
        n, f = np(), self.freqs
        key = (round(self.low, 3), round(self.high, 3), round(self.filter, 3))
        if key == self.made:
            return self.curve
        lo, hi = self.knob_gain(self.low), self.knob_gain(self.high)
        w_lo = 1 / (1 + (f / 250.0) ** 4)        # how much each frequency is LOW's, or HIGH's
        w_hi = 1 / (1 + (2500.0 / n.maximum(f, 1)) ** 4)
        g = 1 + w_lo * (lo - 1) + w_hi * (hi - 1)
        x = self.filter - 0.5
        if x < -0.02:                            # low-pass: 20 kHz at the middle down to 150 Hz at the left
            fc = 20000 * (150 / 20000) ** (-x / 0.5)
            g = g / n.sqrt(1 + (f / fc) ** 4)
        elif x > 0.02:                           # high-pass: 20 Hz up to 6 kHz at the right
            fc = 20 * (6000 / 20) ** (x / 0.5)
            g = g / n.sqrt(1 + (fc / n.maximum(f, 1)) ** 4)
        self.curve, self.made = g.astype(n.float32), key
        return self.curve

    def flat(self):
        return abs(self.low - 0.5) < 0.01 and abs(self.high - 0.5) < 0.01 and abs(self.filter - 0.5) < 0.02

    def process(self, block):
        """block: [BLOCK, 2] float32 -> the same, through the curve (BLOCK frames late, always: the latency stays
        the same whether the curve is flat or not)"""
        n = np()
        frame = n.concatenate([self.prev, block]) * self.win[:, None]
        self.prev = block
        spec = n.fft.rfft(frame, axis=0) * self.gains()[:, None]
        out = n.fft.irfft(spec, n=FFT, axis=0).astype(n.float32) * self.win[:, None]
        result = self.tail + out[:BLOCK]
        self.tail = out[BLOCK:]
        return result


class Deck:
    def __init__(self, name):
        self.name = name
        self.track, self.loading, self.error = None, None, None
        self.pos = 0.0                           # in the track's frames
        self.playing = False
        self.pitch = 0.0                         # -1 .. 1 of PITCH_RANGE
        self.bend = 0.0                          # the jog edge's nudge, easing back to 0
        self.vinyl, self.touched, self.scratch_ticks = False, False, 0   # (VINYL off at start: the jog's top
                                                                         # moves through the track; on: scratch)
        self.cue, self.cue_held, self.hot_held, self.playing_before_hot = 0.0, False, None, False
        self.loop = None                         # (start, end) frames while looping
        self.loop_beats, self.last_loop = 4.0, None
        self.roll = None                         # (slip position, beats) while a roll pad is held
        self.gain, self.volume, self.pfl = 0.5, 0.0, False
        self.tone = Tone()
        self.shift = False
        self.pad_mode = "hotcue"
        self.synced = False                      # SYNC on: this deck follows the other's tempo (and took its beat)
        self.fader = 0.0                         # where the tempo fader is (-1 .. 1): the pitch when not synced
        self.lock_fix = 0.0                      # synced and both playing: a hair faster or slower, beats locked
        self.lock_offset = 0.0                   # where its beat sits from the other's, in beats (a nudge kept)

    # ---- tempo
    def speed(self):
        """frames of the track per output frame"""
        if not self.track:
            return 0.0
        return (1.0 + self.pitch * PITCH_RANGE + self.bend + self.lock_fix) * self.track.rate / RATE

    def bpm_now(self):
        return self.track.bpm * (1.0 + self.pitch * PITCH_RANGE) if self.track and self.track.bpm else None

    def beat_pos(self, pos=None):
        """the position in beats from the track's first beat"""
        t = self.track
        return ((self.pos if pos is None else pos) - t.first_beat * t.rate) / t.beat_frames()

    def snap(self, pos):
        """the nearest beat to pos (a grid: the track's first beat and BPM)"""
        t = self.track
        if not t or not t.bpm:
            return pos
        b = round(self.beat_pos(pos))
        return t.first_beat * t.rate + b * t.beat_frames()

    # ---- transport
    def load(self, track):
        self.track, self.pos, self.playing, self.loop, self.roll = track, 0.0, False, None, None
        self.lock_offset = 0.0
        self.cue = track.cues.get(0, track.first_beat * track.rate) if track.cues else 0.0
        self.pos = self.cue

    def play_pause(self, other=None):
        if self.track and (self.cue_held or self.hot_held is not None):
            self.cue_held, self.hot_held = False, None   # PLAY while CUE (or a hot cue) is held: it plays on
            self.playing = True                          # when that's let go, as on a CDJ
            return
        if self.track:
            self.playing = not self.playing
            if self.playing and self.synced and other is not None and other.playing and other.track                     and other.track.bpm and self.track.bpm:       # synced: it starts on the other's beat
                self.pos += self.phase_error(other) * self.track.beat_frames()

    def cue_press(self, down):
        if not self.track:
            return
        if down:
            if self.playing:                     # playing: back to the cue, stopped
                self.playing, self.pos = False, self.cue
            else:                                # stopped: the cue here (on a beat when close), playing while held
                self.cue = self.snap(self.pos) if abs(self.snap(self.pos) - self.pos) < self.track.rate * 0.05 \
                    else self.pos
                self.pos, self.playing, self.cue_held = self.cue, True, True
        elif self.cue_held:                      # let go: back to the cue
            self.cue_held, self.playing, self.pos = False, False, self.cue

    def hotcue(self, i, down, clear=False):
        t = self.track
        if not t or not down:
            if not down and self.hot_held == i and not self.playing_before_hot:
                self.playing, self.pos, self.hot_held = False, t.cues.get(i, self.pos), None
            return
        if clear:
            t.cues.pop(i, None)
            t.cue_colors.pop(i, None)
            return
        if i in t.cues:                          # there: from it (stopped: plays while held, as CUE does)
            self.playing_before_hot = self.playing
            self.pos, self.playing, self.hot_held = t.cues[i], True, i
        else:                                    # not yet: set here
            t.cues[i] = self.pos

    def loop_in(self):
        """a 4-beat loop from the nearest beat (LOOP IN), or off if one's playing"""
        if not self.track:
            return
        if self.loop:
            self.last_loop, self.loop = self.loop, None
            return
        start = self.snap(self.pos)
        self.loop = (start, start + self.loop_beats * self.track.beat_frames())
        self.last_loop = self.loop

    def loop_out(self):
        """LOOP OUT: out of the loop, or back into the last one"""
        if self.loop:
            self.loop = None
        elif self.last_loop:
            self.loop = self.last_loop
            self.pos = self.loop[0]

    def loop_size(self, factor):
        if not self.track:
            return
        self.loop_beats = min(32.0, max(1 / 8, self.loop_beats * factor))
        if self.loop:
            self.loop = (self.loop[0], self.loop[0] + self.loop_beats * self.track.beat_frames())
            self.last_loop = self.loop

    def roll_pad(self, beats, down):
        """a loop roll: `beats` from the nearest beat while held; let go, on from where it would have been"""
        if not self.track:
            return
        if down:
            start = self.snap(self.pos) if self.snap(self.pos) <= self.pos else self.pos
            self.roll = (self.pos, beats)
            self.loop = (start, start + beats * self.track.beat_frames())
        elif self.roll:
            self.pos, self.roll, self.loop = self.roll[0], None, None

    def toggle_sync(self, other):
        """SYNC: on, this deck takes the other's tempo and beat and keeps following its tempo; off, back to its own
        tempo fader. (Both on: whichever was synced first leads.)"""
        if self.synced:
            self.synced, self.pitch, self.lock_fix = False, self.fader, 0.0
            return
        self.synced, self.lock_offset = True, 0.0
        self.sync_to(other)

    def target_bpm(self, other):
        """the other deck's tempo as this one should take it: it, its double or its half, whichever is nearest
        this track's own (a 70 and a 140 BPM track are the same beat; tags often say 70 for 140 BPM dubstep)"""
        theirs = other.bpm_now()
        return min((theirs * k for k in (0.5, 1.0, 2.0)), key=lambda b: abs(math.log(b / self.track.bpm)))

    def phase_error(self, other):
        """how far this deck's beat is from the other's, in this deck's beats (-0.5 .. 0.5; + : this one behind)"""
        ratio = self.target_bpm(other) / other.bpm_now()
        return ((other.beat_pos() * ratio) % 1.0 - self.beat_pos() % 1.0 + 0.5) % 1.0 - 0.5

    def follow(self, other):
        """(each block, while synced) the other deck's tempo, and its beat: while both play, a little faster or
        slower (at most 1 %) until the beats meet, so they don't drift apart (no grid: the tempo alone)"""
        self.lock_fix = 0.0
        if self.synced and self.track and other.track and self.track.bpm and other.track.bpm:
            want = self.target_bpm(other) / self.track.bpm - 1.0
            self.pitch = max(-1.0, min(1.0, want / PITCH_RANGE))
            if self.playing and other.playing and (self.touched or self.bend):
                self.lock_offset = self.phase_error(other)      # the hand moves it: kept where it's left
            elif self.playing and other.playing:
                err = (self.phase_error(other) - self.lock_offset + 0.5) % 1.0 - 0.5
                self.lock_fix = max(-0.01, min(0.01, err * 0.08))

    def sync_to(self, other):
        """the other deck's tempo, and its beat when both have a beat grid"""
        if not (self.track and other.track and self.track.bpm and other.track.bpm):
            return
        target = self.target_bpm(other)
        want = target / self.track.bpm - 1.0
        self.pitch = max(-1.0, min(1.0, want / PITCH_RANGE))
        if other.playing or other.pos:           # its beat: the other's phase in this deck's beats (a double or
            ratio = target / other.bpm_now()      # half tempo: two of the other's beats a beat, or half of one)
            phase = (other.beat_pos() * ratio) % 1.0
            mine = self.beat_pos()
            self.pos += ((phase - mine % 1.0 + 0.5) % 1.0 - 0.5) * self.track.beat_frames()

    # ---- jog
    def jog_top(self, ticks):
        if self.vinyl and self.touched:
            self.scratch_ticks += ticks
        else:
            self.jog_edge(ticks)

    def jog_edge(self, ticks):
        if self.playing:
            self.bend = max(-0.5, min(0.5, self.bend + ticks * BEND_PER_TICK))
        elif self.track:                         # stopped: the jog moves through the track (not past its ends)
            self.pos = max(0.0, min(self.track.frames - 1.0,
                                    self.pos + ticks * SAMPLES_PER_TICK * self.track.rate / RATE))

    # ---- sound
    def render(self, n):
        """-> (pre-fader [n, 2] float32: what PFL hears, the same for the master before the volume fader)"""
        nm = np()
        t = self.track
        silent = nm.zeros((n, 2), nm.float32)
        if t is None:
            return self.tone.process(silent)
        if self.vinyl and self.touched:          # scratching: the record follows the hand (no hand: it stands)
            step = self.scratch_ticks * SAMPLES_PER_TICK * t.rate / RATE / n
            self.scratch_ticks = 0
            positions = self.pos + step * nm.arange(n)
        elif self.playing:
            positions = self.pos + self.speed() * nm.arange(n)
        else:
            return self.tone.process(silent)
        if self.roll:                            # the slip position keeps going, as if it had played through
            self.roll = (self.roll[0] + self.speed() * n, self.roll[1])
        if self.loop:
            ls, le = self.loop
            length = le - ls
            over = positions >= le
            if over.any():
                positions = nm.where(over, ls + (positions - ls) % length, positions)
        self.bend *= 0.9                         # the nudge eases back
        if abs(self.bend) < 1e-4:
            self.bend = 0.0
        last = positions[-1] + (positions[-1] - positions[-2] if n > 1 else 0)
        self.pos = float(last)
        if self.pos >= t.frames - 1:             # the end: stopped there
            self.pos, self.playing = float(t.frames - 1), False
        if self.pos < 0:
            self.pos = 0.0
        i = nm.clip(positions, 0, t.frames - 2)
        i0 = i.astype(nm.int64)
        frac = (i - i0).astype(nm.float32)[:, None]
        a = t.audio[i0].astype(nm.float32)
        b = t.audio[i0 + 1].astype(nm.float32)
        out = (a + (b - a) * frac) / 32768.0
        gain = (self.gain / 0.5) ** 1.5           # the gain knob: about -inf .. +9 dB, unity in the middle
        return self.tone.process(out * gain)


HEADROOM = 0.7                                # -3 dB: two loud tracks together still fit


def limit(x, knee=0.9):
    """the signal untouched below `knee`, its peaks above it bent smoothly towards 1 (never past it): a limiter on
    the very top only (a soft clip on everything crunches loud dance tracks)"""
    nm = np()
    a = nm.abs(x)
    over = a > knee
    if not over.any():
        return x
    bent = knee + (1 - knee) * nm.tanh((a - knee) / (1 - knee))
    return nm.where(over, nm.sign(x) * bent, x).astype(nm.float32)


class Engine:
    def __init__(self):
        self.decks = [Deck("A"), Deck("B")]
        self.xfade = 0.5
        self.leader = 0                          # both synced: the deck the other follows (whose fader moved last)
        self.lock = threading.Lock()
        self.peak, self.limited = 0.0, 0          # the master's recent peak, blocks the limiter touched

    def pitch_fader(self, d, v):
        """deck d's tempo fader at v (0 .. 1)"""
        d.fader = (0.5 - v) * 2                  # up is slower, as on a CDJ and in Serato (checked on the MK2)
        other = self.decks[1 - self.decks.index(d)]
        if d.synced and other.synced:            # both synced: this deck leads now, the other follows it
            self.leader, d.pitch = self.decks.index(d), d.fader
        elif d.synced and other.track and d.track and other.track.bpm:
            d.pitch = d.fader                    # synced to an unsynced deck: that one taken along
            want = other.target_bpm(d) / other.track.bpm - 1.0
            other.pitch = other.fader = max(-1.0, min(1.0, want / PITCH_RANGE))
        else:
            d.pitch = d.fader

    def render(self, n=BLOCK):
        """-> (master [n, 2], headphones [n, 2]) float32"""
        nm = np()
        with self.lock:
            da, db = self.decks
            if da.synced and db.synced:          # both: the leader's tempo, the other one following it
                lead = self.decks[self.leader]
                self.decks[1 - self.leader].follow(lead)
                lead.lock_fix = 0.0
            else:
                da.follow(db)
                db.follow(da)
            a, b = (d.render(n) for d in self.decks)
            ga = math.cos(self.xfade * math.pi / 2)     # constant power
            gb = math.sin(self.xfade * math.pi / 2)
            da, db = self.decks
            master = a * (da.volume * ga) + b * (db.volume * gb)
            phones = nm.zeros((n, 2), nm.float32)
            for d, x in ((da, a), (db, b)):
                if d.pfl:
                    phones += x
        master, phones = master * HEADROOM, phones * HEADROOM
        self.peak = max(self.peak * 0.995, float(nm.abs(master).max()) if len(master) else 0.0)
        self.limited += int((nm.abs(master) > 0.9).any())
        return limit(master), limit(phones)


# ---------------------------------------------------------------- the Hercules

class Hercules:
    """the Inpulse 200 MK2's MIDI (Hercules' layout, as Mixxx maps it): channel 1 the browser and crossfader,
    2 and 3 decks A and B, 4 the browser with SHIFT, 5 and 6 the decks with SHIFT, 7 and 8 their pads; faders and
    knobs 14-bit (CC n, then CC n+32), the jog's top CC 10 and edge CC 9 (1 / 127: a tick each way), its touch
    note 8. Its lights: the same note sent back, 127 on, 0 off"""

    def __init__(self, engine, on_browse=lambda step: None, on_load=lambda deck: None, on_push=lambda: None):
        self.engine, self.on_browse, self.on_load, self.on_push = engine, on_browse, on_load, on_push
        self.msb = {}
        self.count = 0                           # messages taken (the log's: is it hearing the controller?)
        self.inp = self.out = None
        self.lit = {}

    def hello(self, mido):
        """its output just opened: asked where every fader and knob is"""
        if self.out:
            self.out.send(mido.Message.from_bytes([0xB0, 0x7F, 0x7F]))

    def value14(self, ch, cc, value):
        """a 14-bit control's 0..1 (its coarse half when the fine one hasn't come)"""
        if cc < 32:
            self.msb[(ch, cc)] = value
            return value / 127.0
        coarse = self.msb.get((ch, cc - 32), 0)
        return ((coarse << 7) | value) / 16383.0

    def message(self, msg):
        b = msg.bytes() if hasattr(msg, "bytes") else msg
        self.count += 1
        if len(b) < 3:
            return
        kind, ch, num, val = b[0] & 0xF0, b[0] & 0x0F, b[1], b[2]
        e = self.engine
        with e.lock:
            if kind == 0xB0:
                self.control(ch, num, val)
            elif kind in (0x90, 0x80):
                self.button(ch, num, kind == 0x90 and val > 0)
        self.lights()

    def control(self, ch, cc, val):
        e = self.engine
        ticks = val if val < 64 else val - 128
        if ch == 0:
            if cc in (0, 32):
                e.xfade = self.value14(ch, cc, val)
            elif cc == 1:
                self.on_browse(ticks)
            return
        if ch == 3 and cc == 1:                  # SHIFT + browser: ten at a time
            self.on_browse(ticks * 10)
            return
        if ch in (1, 2, 4, 5):
            d = e.decks[0 if ch in (1, 4) else 1]
            if cc == 10:
                d.jog_top(ticks * (4 if ch in (4, 5) else 1))     # SHIFT + jog: faster through the track
            elif cc == 9:
                d.jog_edge(ticks)
            elif ch in (1, 2):
                v = self.value14(ch, cc, val)
                base = cc if cc < 32 else cc - 32
                if base == 0:
                    d.volume = v
                elif base == 1:
                    d.tone.filter = v
                elif base == 2:
                    d.tone.low = v
                elif base == 4:
                    d.tone.high = v
                elif base == 5:
                    d.gain = v
                elif base == 8:
                    e.pitch_fader(d, v)

    def button(self, ch, note, down):
        e = self.engine
        if ch == 0:
            if note == 0 and down:
                self.on_push()
            return
        if ch in (1, 2):
            d, other = e.decks[ch - 1], e.decks[2 - ch]
            if note == 4:
                d.shift = down
            elif note == 3 and down:
                d.vinyl = not d.vinyl
            elif note == 5 and down:
                d.toggle_sync(other)
            elif note == 6:
                d.cue_press(down)
            elif note == 7 and down:
                d.play_pause(other)
            elif note == 8:
                d.touched = down
            elif note == 9 and down:
                d.loop_in()
            elif note == 10 and down:
                d.loop_out()
            elif note == 12 and down:
                d.pfl = not d.pfl
            elif note == 13 and down:
                self.on_load(ch - 1)
            elif 15 <= note <= 18 and down:
                d.pad_mode = ("hotcue", "roll", "fx", "sampler")[note - 15]
        elif ch in (4, 5):                        # with SHIFT
            d = e.decks[ch - 4]
            if note == 6 and down and d.track:     # back to the start
                d.pos, d.cue = 0.0, 0.0
            elif note == 7 and down and d.track:   # stutter: from the cue, playing
                d.pos, d.playing = d.cue, True
            elif note == 9 and down:
                d.loop_size(0.5)
            elif note == 10 and down:
                d.loop_size(2.0)
            elif note == 8:
                d.touched = down
        elif ch in (6, 7):                        # the pads
            d = e.decks[ch - 6]
            bank, pad = note // 16, note % 8
            shifted = note % 16 >= 8
            if pad > 3:
                return
            if bank == 0:
                d.hotcue(pad, down, clear=shifted)
            elif bank == 1:
                d.roll_pad((1, 2, 4, 8)[pad], down)

    def lights(self):
        """the buttons and pads lit as the decks are"""
        if not self.out:
            return
        import mido
        want = {}
        for i, d in enumerate(self.engine.decks):
            st, pads = 0x91 + i, 0x96 + i
            want[(st, 7)] = d.playing
            want[(st, 6)] = bool(d.track) and abs(d.pos - d.cue) < 1 and not d.playing
            want[(st, 12)] = d.pfl
            want[(st, 3)] = d.vinyl
            want[(st, 9)] = bool(d.loop)
            want[(st, 5)] = d.synced
            for k in range(4):
                want[(pads, k)] = bool(d.track and k in d.track.cues)
        for (st, note), on in want.items():
            if self.lit.get((st, note)) != on:
                self.out.send(mido.Message.from_bytes([st, note, 127 if on else 0]))
                self.lit[(st, note)] = on


# ---------------------------------------------------------------- any controller: MIDI learn

LEARN_DECK = [("shift", "SHIFT", "button"), ("play", "PLAY", "button"), ("cue", "CUE", "button"),
              ("sync", "SYNC", "button"), ("load", "LOAD", "button"), ("pfl", "PFL (HEADPHONES)", "button"),
              ("volume", "VOLUME FADER", "fader"), ("pitch", "TEMPO FADER", "fader"), ("gain", "GAIN", "fader"),
              ("high", "HIGH EQ", "fader"), ("low", "LOW EQ", "fader"), ("filter", "FILTER", "fader"),
              ("jog", "JOG WHEEL", "encoder"), ("touch", "JOG TOUCH", "button"), ("vinyl", "VINYL", "button"),
              ("loop_in", "LOOP IN", "button"), ("loop_out", "LOOP OUT", "button"),
              ("loop_half", "LOOP HALF", "button"), ("loop_double", "LOOP DOUBLE", "button"),
              ("hot1", "HOT CUE 1", "button"), ("hot2", "HOT CUE 2", "button"), ("hot3", "HOT CUE 3", "button"),
              ("hot4", "HOT CUE 4", "button")]
LEARN = ([("xfade", "", "CROSSFADER", "fader"), ("browse", "", "BROWSE KNOB", "encoder")]
         + [(f"{x}.{a}", x.upper(), label, kind) for x in "ab" for a, label, kind in LEARN_DECK])   # the guided order
KIND = {a: kind for a, _deck, _label, kind in LEARN}
HINT = {"button": "PRESS IT", "fader": "MOVE IT END TO END", "encoder": "TURN IT"}
LIT = ("play", "cue", "sync", "pfl", "vinyl", "loop_in", "hot1", "hot2", "hot3", "hot4")   # lit as on the Hercules
QUIET = 0.6                                   # after a control's learnt: what it still sends (let go) isn't the next


def describe(b):
    """a binding as the screen shows it: "NOTE 7 CH 2", "CC 13+45 CH 1", "SHIFT + ..." """
    if b["type"] == "pb":
        what = "PITCH BEND"
    elif b["type"] == "note":
        what = f"NOTE {b['num']}"
    else:
        what = f"CC {b['num']}" + (f"+{b['fine']}" if b.get("fine") is not None else "")
    return ("SHIFT + " if b.get("shift") else "") + f"{what} CH {b['ch'] + 1}"


class Learned:
    """a controller played from a map learned on the DECKS screen: its buttons, faders, knobs and jog wheels, as
    notes, CCs (7-bit or 14-bit, a knob's relative steps either way they come) or pitch bend, on the decks' controls.
    A learnt SHIFT gives each control a second job (a control learnt with SHIFT held); SHIFT + a hot cue clears it.
    Its lights: a button's own note sent back, 127 on, 0 off (what many controllers do; not every one)"""

    def __init__(self, engine, binds, on_browse=lambda step: None, on_load=lambda deck: None):
        self.engine, self.on_browse, self.on_load = engine, on_browse, on_load
        self.out, self.shift, self.msb, self.lit = None, False, {}, {}
        self.set(binds)

    def set(self, binds):
        self.binds, self.index = binds, {}
        for b in binds:
            self.index[(b["type"], b["ch"], b["num"], bool(b.get("shift")))] = (b, False)
            if b.get("fine") is not None:
                self.index[("cc", b["ch"], b["fine"], bool(b.get("shift")))] = (b, True)

    def find(self, kind, ch, num):
        """(binding, its fine half?) for a message: the SHIFT layer's first while SHIFT is held"""
        return (self.shift and self.index.get((kind, ch, num, True))) or self.index.get((kind, ch, num, False))

    def message(self, b):
        if len(b) < 3:
            return
        kind, ch, num, val = b[0] & 0xF0, b[0] & 0x0F, b[1], b[2]
        if kind in (0x90, 0x80):
            hit = self.find("note", ch, num)
            if hit:
                self.act(hit[0], down=kind == 0x90 and val > 0)
        elif kind == 0xE0:
            hit = self.find("pb", ch, 0)
            if hit:
                self.act(hit[0], value=((val << 7) | num) / 16383.0)
        elif kind == 0xB0:
            hit = self.find("cc", ch, num)
            if not hit:
                return
            bind, fine = hit
            how = KIND.get(bind["action"])
            if how == "button":
                self.act(bind, down=val >= 64)
            elif how == "encoder":
                self.act(bind, ticks=val - 64 if bind.get("rel") == "center" else (val if val < 64 else val - 128))
            elif fine:
                self.act(bind, value=((self.msb.get((ch, bind["num"]), 0) << 7) | val) / 16383.0)
            else:
                self.msb[(ch, num)] = val
                self.act(bind, value=val / 127.0)

    def act(self, bind, down=False, value=0.0, ticks=0):
        e = self.engine
        name, d, other, k = bind["action"], None, None, None
        if "." in name:
            k = "ab".index(name[0])
            d, other, name = e.decks[k], e.decks[1 - k], name[2:]
        if name == "xfade":
            e.xfade = value
        elif name == "browse":
            self.on_browse(ticks)
        elif d is None:
            return
        elif name == "shift":
            self.shift = d.shift = down
        elif name in ("volume", "gain"):
            setattr(d, name, value)
        elif name in ("low", "high", "filter"):
            setattr(d.tone, name, value)
        elif name == "pitch":
            e.pitch_fader(d, value)
        elif name == "jog":                      # touched: the Hercules's top (scratch in VINYL), else its edge
            d.jog_top(ticks) if d.touched else d.jog_edge(ticks)
        elif name == "touch":
            d.touched = down
        elif name == "cue":
            d.cue_press(down)
        elif name.startswith("hot"):
            d.hotcue(int(name[3]) - 1, down, clear=self.shift)
        elif not down:
            return
        elif name == "play":
            d.play_pause(other)
        elif name == "sync":
            d.toggle_sync(other)
        elif name == "load":
            self.on_load(k)
        elif name == "pfl":
            d.pfl = not d.pfl
        elif name == "vinyl":
            d.vinyl = not d.vinyl
        elif name == "loop_in":
            d.loop_in()
        elif name == "loop_out":
            d.loop_out()
        elif name == "loop_half":
            d.loop_size(0.5)
        elif name == "loop_double":
            d.loop_size(2.0)

    def lights(self):
        if not self.out:
            return
        import mido
        for b in self.binds:
            name = b["action"]
            if b["type"] != "note" or "." not in name or name[2:] not in LIT or b.get("shift"):
                continue
            d, what = self.engine.decks["ab".index(name[0])], name[2:]
            on = (d.playing if what == "play" else
                  bool(d.track) and abs(d.pos - d.cue) < 1 and not d.playing if what == "cue" else
                  d.synced if what == "sync" else d.pfl if what == "pfl" else d.vinyl if what == "vinyl" else
                  bool(d.loop) if what == "loop_in" else bool(d.track and int(what[3]) - 1 in d.track.cues))
            if self.lit.get(name) != on:
                try:
                    self.out.send(mido.Message.from_bytes([0x90 | b["ch"], b["num"], 127 if on else 0]))
                except Exception:
                    pass
                self.lit[name] = on


class Learner:
    """learning a controller's map: guided (every control in LEARN's order, SKIP the ones it hasn't, BACK) or one
    control. A button: its first press (a note, or a CC that comes up from 0). A fader or knob: a CC (or pitch
    bend) that moved through a few values, with its fine half if CC n+32 came too. A jog or endless knob: a CC
    that sent a few steps, read as 1 / 127 or as 63 / 65 by what it sent"""

    def __init__(self, port, binds, guided, start=0):
        self.port, self.binds, self.guided = port, [dict(b) for b in binds], guided
        self.step = start
        self.heard, self.seen, self.quiet, self.shift = None, {}, 0.0, False
        self.heard_what = None                    # the control the last one learnt went on ("A PLAY")

    @property
    def action(self):
        return LEARN[self.step][0] if self.step < len(LEARN) else None

    def bound(self, action):
        return next((b for b in self.binds if b["action"] == action), None)

    def hear(self, b, now):
        """a message from the controller: -> True when it taught the step a control"""
        if len(b) < 3 or self.action is None:
            return False
        kind, ch, num, val = b[0] & 0xF0, b[0] & 0x0F, b[1], b[2]
        shift = self.bound(self.action.split(".")[0] + ".shift") if "." in self.action else None
        if shift and self.action[2:] != "shift" and shift["type"] == "note" and kind in (0x90, 0x80) \
                and (ch, num) == (shift["ch"], shift["num"]):      # its SHIFT held: what's learnt is SHIFT + it
            self.shift = kind == 0x90 and val > 0
            return False
        if now < self.quiet:
            return False
        how = KIND[self.action]
        got = None
        if how == "button":
            if kind == 0x90 and val > 0:
                got = {"type": "note", "ch": ch, "num": num}
            elif kind == 0xB0 and val >= 64:
                got = {"type": "cc", "ch": ch, "num": num}
        elif kind == 0xE0 and how == "fader":
            n = self.seen.setdefault(("pb", ch, 0), [])
            n.append(val)
            if len(n) >= 4 and len(set(n)) >= 3:
                got = {"type": "pb", "ch": ch, "num": 0}
        elif kind == 0xB0:
            if how == "fader" and num >= 32 and ("cc", ch, num - 32) in self.seen:
                self.seen[("cc", ch, num - 32)].append(None)          # its fine half: noted with the coarse one
                self.seen.setdefault(("fine", ch, num - 32), True)
                return False
            n = self.seen.setdefault(("cc", ch, num), [])
            n.append(val)
            vals = [v for v in n if v is not None]
            if how == "fader" and len(vals) >= 4 and len(set(vals)) >= 3:
                got = {"type": "cc", "ch": ch, "num": num,
                       "fine": num + 32 if ("fine", ch, num) in self.seen else None}
            elif how == "encoder" and len(vals) >= 4:
                got = {"type": "cc", "ch": ch, "num": num,
                       "rel": "center" if all(48 <= v <= 80 for v in vals) else "twos"}
        if not got:
            return False
        got = dict(got, action=self.action, shift=self.shift)
        same = (got["type"], got["ch"], got["num"], got["shift"])
        self.binds = [x for x in self.binds if x["action"] != self.action
                      and (x["type"], x["ch"], x["num"], bool(x.get("shift"))) != same]   # one job a control
        self.binds.append({k: v for k, v in got.items() if v is not None and v is not False})
        self.heard, self.seen, self.quiet = describe(got), {}, now + QUIET
        self.heard_what = " ".join(x for x in LEARN[self.step][1:3] if x)
        return True

    def next(self, step=1):
        """on (or back, -1) a step; what was last learnt stays said"""
        self.step = max(0, min(len(LEARN), self.step + step))
        self.seen = {}

    def status(self):
        a = self.action
        _id, deck, label, kind = LEARN[self.step] if a else (None, "", "", "button")
        b = self.bound(a) if a else None
        return {"port": self.port, "guided": self.guided, "step": self.step, "steps": len(LEARN), "action": a,
                "deck": deck, "label": label, "hint": HINT[kind], "heard": self.heard, "heard_what": self.heard_what,
                "now": b and describe(b), "shift": self.shift}


# ---------------------------------------------------------------- sound out

def sinks():
    """(the Hercules's sound card, a Bluetooth speaker): their PipeWire node names, or None"""
    import json
    try:
        objects = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=10).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None, None
    herc = bt = None
    for o in objects:
        p = (o.get("info") or {}).get("props") or {}
        name = str(p.get("node.name", ""))
        if p.get("media.class") == "Audio/Sink" and "Inpulse_200" in name:
            herc = name
        elif p.get("media.class") == "Audio/Sink" and name.startswith("bluez_output."):
            bt = bt or name
    return herc, bt


class Output:
    """the master: "studio" (Settings > Audio > DJ decks out, the default) where the Studio plays, as its apps do
    (the speaker or the jack, the DECKS channel of its MIXER: its level, CUE, recorded); "hercules" the Hercules's
    master out (its channels 1-2: its own speakers), else where the Studio plays. The headphones: the Hercules's
    headphone out (its channels 3-4). Two streams, each written a block at a time (the writes pace the engine: real
    time)"""

    def __init__(self, to="studio"):
        self.herc, self.bt = sinks()
        self.to = to
        self.streams = []
        if to == "hercules" and self.herc:
            self.master = self.stream("fm1-decks", "DECKS", 2, self.herc, "FL,FR")
        else:                                    # (no target: PipeWire's default, where the Studio plays, and
            self.master = self.stream("fm1-decks", "DECKS", 2, None, None)   # along when that changes)
        self.phones = self.stream("fm1-decks-cue", "DECKS CUE", 2, self.herc, "RL,RR") if self.herc else None

    def stream(self, node, label, ch, target, channel_map):
        cmd = ["pw-cat", "--playback", "--raw", "--rate", str(RATE), "--channels", str(ch), "--format", "s16",
               "--latency", "1024", "-P", f"{{ node.name = {node} node.description = \"{label}\" }}"]
        if target:
            cmd += ["--target", target]
        if channel_map:
            cmd += ["--channel-map", channel_map]
        proc = subprocess.Popen(cmd + ["-"], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            import fcntl
            fcntl.fcntl(proc.stdin.fileno(), 1031, 8192)            # F_SETPIPE_SZ: a short pipe, short delay
        except OSError:
            pass
        self.streams.append(proc)
        return proc

    def write(self, master, phones):
        n = np()
        for proc, x in ((self.master, master), (self.phones, phones)):
            if proc is not None:
                proc.stdin.write((n.clip(x, -1, 1) * 32767).astype(n.int16).tobytes())

    def close(self):
        for proc in self.streams:
            try:
                proc.stdin.close()
                proc.wait(3)
            except (OSError, subprocess.TimeoutExpired):
                proc.kill()


# ---------------------------------------------------------------- running it

class Decks:
    """the engine, the Hercules, the browser and the sound, together"""

    def __init__(self, folder=djlib.MUSIC):
        self.engine = Engine()
        self.folder = folder                     # the Studio's music: its memory kept here, whatever's browsed
        self.sources = [{"name": "STUDIO", "folder": folder, "uuid": None}]   # and each USB drive plugged in
        self.source = 0                          # the one browsed
        self.tried = {}                          # USB filesystems a mount failed on (djlib.usb_music)
        self.listings = {}                       # {UUID: a USB drive's tracks}: walked once, till it's scanned
        self.waiting = []                        # [(deck, state)]: the last session's drive tracks, till it's in
        self.say = lambda obj: None              # (serve: a message to the Companion)
        self.library = []                        # [(key, entry)] sorted by title: key, the memory's (key_of)
        self.cursor = 0
        self.loads = queue.Queue()
        self.hercules = Hercules(self.engine, self.browse, self.load_selected, lambda: None)
        self.maps = {}                           # {port name: Learned}: controllers with a learnt map
        self.ports = {}                          # {port name: (input, output or None)}: the controllers open
        self.inputs = []                         # every MIDI input there is (LEARN's list)
        self.learner = None                      # Learner while LEARN is on
        self.out_to = "studio"                   # the master's way out (Output): "studio" or "hercules"
        self.midi_lock = threading.Lock()
        self.stop = threading.Event()
        self.memory = self.read_memory()         # {"tracks": {rel: {"cues", "colors", "cue"}}, "session": {...}}
        self.saved = None
        self.on_loaded = lambda deck, track: None
        self.scanning = None                     # "12/37" while the folder is being scanned
        self.refresh()

    def refresh(self):
        """the browsed source's tracks: the Studio's as scanned; a USB drive's all of them, scanned or not"""
        src = self.browsed()
        if not src["uuid"]:
            found = djlib.load_cache(src["folder"])
        else:
            if src["uuid"] not in self.listings:
                self.listings[src["uuid"]] = djlib.listing(src["folder"], self.cache_of(src))
            found = self.listings[src["uuid"]]
        self.library = sorted(((self.key_of(src, rel), e) for rel, e in found.items()),
                              key=lambda kv: (kv[1].get("title") or kv[0]).lower())

    # ---- where the music is: the Studio's folder, USB drives

    @staticmethod
    def key_of(src, rel):
        """a track's key (its memory's, the library's): its name in the Studio's folder; on a USB drive, the
        drive's filesystem UUID with it ("usb:1234-ABCD/House/track.mp3": the same drive, the same cues)"""
        return f"usb:{src['uuid']}/{rel}" if src["uuid"] else rel

    def path_of(self, key):
        """a track's file from its key, or None (its drive not plugged in)"""
        if not key.startswith("usb:"):
            return self.folder / key
        uuid, rel = key[4:].split("/", 1)
        for src in self.sources:
            if src["uuid"] == uuid:
                return src["folder"] / rel
        return None

    def entry_of(self, key):
        """(key, entry) for a track in any source plugged in, or None"""
        path = self.path_of(key)
        if path is None or not path.is_file():
            return None
        if not key.startswith("usb:"):
            entry = djlib.load_cache(self.folder).get(key)
            return (key, entry) if entry else None
        src = next(s for s in self.sources if s["uuid"] == key[4:].split("/", 1)[0])
        rel = str(path.relative_to(src["folder"]))
        return key, djlib.load_cache(src["folder"], self.cache_of(src)).get(rel) or {"title": path.stem, "artist": ""}

    def cache_of(self, src):
        """a source's scan cache: the Studio's beside its music, a USB drive's in it too (.usb/<UUID>.json: the drive
        is mounted read-only)"""
        return self.folder / ".usb" / f"{src['uuid']}.json" if src["uuid"] else self.folder / djlib.CACHE

    def browsed(self):
        """the source browsed (the Studio's when the list has just shrunk under it: read from other threads)"""
        sources, k = self.sources, self.source
        return sources[k] if k < len(sources) else sources[0]

    def pick_source(self, k):
        """source k browsed (k past the end: back to the first)"""
        self.source = k % len(self.sources)
        self.cursor = 0
        self.refresh()
        self.say(self.library_message())

    def watch_drives(self, once=False):
        """USB drives as they come and go, every 3 s: one plugged in, mounted and browsed; the one browsed
        pulled out, back to the Studio's (a track loaded from it plays on: it's in memory)"""
        while True:
            try:
                drives = djlib.usb_music(self.tried)
            except Exception:                    # (lsblk / udisks misbehaving: tried again next time)
                drives = [s for s in self.sources if s["uuid"]]
            for path, ok in list(self.tried.items()):
                if ok is False:
                    self.note("a USB drive couldn't be mounted (run install.sh again)")
                    self.tried[path] = None      # (said once)
            browsed = self.browsed()
            old = {s["uuid"] for s in self.sources if s["uuid"]}
            new = [d for d in drives if d["uuid"] not in old]
            if new or len(drives) != len(old):
                keep = {d["uuid"] for d in drives} - {d["uuid"] for d in new}    # (plugged in again: walked again)
                self.listings = {u: v for u, v in self.listings.items() if u in keep}
                sources = self.sources[:1] + drives
                self.source = sources.index(browsed) if browsed in sources else 0   # (the index first, then the
                self.sources = sources                                              # list: never past its end)
                if new:
                    self.pick_source(self.sources.index(new[-1]))
                    self.note(f"USB drive {new[-1]['name']}: {len(self.library)} tracks")
                elif browsed not in self.sources:
                    self.pick_source(0)
                    self.note(f"USB drive {browsed['name']} gone: the Studio's music")
                self.load_waiting()
            if once or self.stop.wait(3.0):
                return

    def load_waiting(self):
        """the last session's tracks on a USB drive, loaded once it's plugged in (on a deck still empty)"""
        for item in list(self.waiting):
            i, state = item
            d = self.engine.decks[i]
            if d.track or d.loading:
                self.waiting.remove(item)        # (something else loaded there since: left alone)
                continue
            found = self.entry_of(state["rel"])
            if found:
                self.waiting.remove(item)
                self.loads.put((i, found, state))

    # ---- what's kept: each track's cues as set here, and the session (the decks' tracks, where, how)

    def read_memory(self):
        import json
        try:
            mem = json.loads((self.folder / MEMORY).read_text())
            return {"tracks": dict(mem.get("tracks") or {}), "session": dict(mem.get("session") or {})}
        except (OSError, ValueError, AttributeError):
            return {"tracks": {}, "session": {}}

    def snapshot(self):
        """(under the engine's lock) the memory as it is now"""
        tracks = dict(self.memory["tracks"])
        decks = []
        for d in self.engine.decks:
            t = d.track
            if t is None:
                decks.append(None)
                continue
            tracks[t.rel] = {"cues": {str(k): round(v / t.rate, 3) for k, v in t.cues.items()},
                             "colors": {str(k): c for k, c in t.cue_colors.items() if c},
                             "cue": round(d.cue / t.rate, 3)}
            decks.append({"rel": t.rel, "pos": round(d.pos / t.rate, 2), "fader": round(d.fader, 4),
                          "synced": d.synced, "pfl": d.pfl, "pad_mode": d.pad_mode})
        return {"tracks": tracks, "session": {"decks": decks, "cursor": self.cursor}}

    def save_memory(self, force=False):
        import json
        with self.engine.lock:
            mem = self.snapshot()
        text = json.dumps(mem, indent=1, sort_keys=True)
        if text == self.saved and not force:
            return
        self.memory = mem
        try:
            tmp = self.folder / (MEMORY + ".tmp")
            tmp.write_text(text)
            tmp.replace(self.folder / MEMORY)
            self.saved = text
        except OSError:
            pass

    def keeper(self):
        """the memory written a few seconds after anything in it changed"""
        while not self.stop.wait(3.0):
            self.save_memory()

    def remembered(self, track):
        """a track's cues as last set here, over its tags' (Serato's)"""
        mem = self.memory["tracks"].get(track.rel)
        if not mem:
            return None
        track.cues = {int(k): float(v) * track.rate for k, v in (mem.get("cues") or {}).items() if int(k) < 4}
        track.cue_colors = {int(k): c for k, c in (mem.get("colors") or {}).items() if int(k) < 4}
        return mem.get("cue")

    def restore(self):
        """the last session: each deck's track loaded again, paused where it was, as it was set"""
        session = self.memory.get("session") or {}
        self.cursor = max(0, min(len(self.library) - 1, int(session.get("cursor") or 0))) if self.library else 0
        for i, state in enumerate((session.get("decks") or [])[:2]):
            if not (state and state.get("rel")):
                continue
            found = self.entry_of(state["rel"])
            if found:
                self.loads.put((i, found, state))
            elif state["rel"].startswith("usb:"):     # its drive not mounted yet: loaded when it is
                self.waiting.append((i, state))

    def browse(self, step):
        if self.library:
            self.cursor = max(0, min(len(self.library) - 1, self.cursor + step))

    def load_selected(self, deck):
        if self.library:
            self.loads.put((deck, self.library[self.cursor]))

    def note(self, text):
        print(text, flush=True)

    def loader(self):
        while not self.stop.is_set():
            try:
                item = self.loads.get(timeout=0.5)
            except queue.Empty:
                continue
            deck, (rel, entry), state = item if len(item) == 3 else (*item, None)
            d = self.engine.decks[deck]
            d.loading, d.error = rel, None
            try:
                path = self.path_of(rel)
                if path is None:
                    raise OSError("its USB drive isn't plugged in")
                track = Track(path, entry, rel)
                cue = self.remembered(track)
                with self.engine.lock:
                    d.load(track)
                    if cue is not None:          # its cue as set here last time
                        d.cue = d.pos = min(float(cue) * track.rate, track.frames - 1)
                    if state:                    # the last session: where it was, as it was set (paused)
                        d.pos = min(float(state.get("pos") or 0) * track.rate, track.frames - 1)
                        d.fader = d.pitch = float(state.get("fader") or 0.0)
                        d.synced = bool(state.get("synced"))
                        d.pfl = bool(state.get("pfl"))
                        d.pad_mode = state.get("pad_mode") or "hotcue"
                self.on_loaded(deck, track)
            except Exception as e:               # a file that won't decode: said, not crashed on
                d.error = str(e)[:60]
            d.loading = None
            self.lights()

    # ---- controllers: the Hercules (its map built in) and any with a learnt map, opened as they come and go

    def load_maps(self):
        for name, binds in djlib.learned(self.folder).items():
            if isinstance(binds, list):
                self.maps[name] = Learned(self.engine, binds, self.browse, self.load_selected)

    def save_maps(self):
        data = {name: m.binds for name, m in self.maps.items()}
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.folder / (djlib.CONTROLLERS + ".tmp")
            tmp.write_text(json.dumps(data, indent=1))
            tmp.replace(self.folder / djlib.CONTROLLERS)
        except OSError as e:
            self.note(f"the map wasn't saved: {e}"[:60])

    @staticmethod
    def learnable(name):
        low = name.lower()
        return not any(s in low for s in ("midi through", "rtmidi", "fm1-", "pipewire"))

    def wanted_ports(self):
        """the controllers to have open: the Hercules, those with a map, the one being learnt"""
        return {n for n in self.inputs if HERCULES in n or n in self.maps
                or (self.learner and n == self.learner.port)}

    def received(self, name, msg):
        b = msg.bytes()
        if len(b) < 3:
            return
        e = self.engine
        if self.learner and self.learner.port == name and self.learner.action is not None:
            with e.lock:
                if self.learner.hear(b, time.monotonic()):
                    self.learnt()
            return
        if name in self.maps:
            with e.lock:
                self.maps[name].message(b)
        elif HERCULES in name:
            self.hercules.message(b)             # (it takes the engine's lock itself)
        self.lights()

    def learnt(self):
        """a control learnt: kept (saved at once), and the guided run on to the next"""
        lr = self.learner
        if HERCULES in lr.port:                  # the Hercules given a map: its built-in one (and lights) off
            self.hercules.out = None
        m = self.maps.get(lr.port)
        if m:
            m.set(lr.binds)
        else:
            self.maps[lr.port] = Learned(self.engine, lr.binds, self.browse, self.load_selected)
            self.wire(lr.port)
        self.save_maps()
        if lr.guided:
            lr.next()
            if lr.action is None:                # all done: the list, to check or change one
                lr.guided = False
        else:
            lr.step = len(LEARN)                 # one control: done, the list again

    def wire(self, name):
        """a learnt map given the port's output for its lights"""
        if name in self.maps and name in self.ports:
            self.maps[name].out = self.ports[name][1]

    def poll_ports(self, mido):
        try:
            names = mido.get_input_names()
            outs = mido.get_output_names()
        except Exception:
            return
        with self.midi_lock:
            self.inputs = sorted({djlib.port_base(n) for n in names if self.learnable(n)})
            full = {djlib.port_base(n): n for n in names}
            outs = {djlib.port_base(n): n for n in outs}
            want = self.wanted_ports()
            for name in [n for n in self.ports if n not in want]:
                inp, out = self.ports.pop(name)
                for port in (inp, out):
                    try:
                        port and port.close()
                    except Exception:
                        pass
            for name in want - set(self.ports):
                try:
                    inp = mido.open_input(full[name], callback=lambda msg, name=name: self.received(name, msg))
                except Exception:
                    continue
                try:
                    out = mido.open_output(outs[name]) if name in outs else None
                except Exception:
                    out = None
                self.ports[name] = (inp, out)
                if HERCULES in name and name not in self.maps:
                    self.hercules.out = out
                    self.hercules.hello(mido)
                self.wire(name)

    def watch_ports(self):
        import mido
        first = True
        while not self.stop.is_set():
            self.poll_ports(mido)
            if first and not self.ports:
                self.note("no DJ controller found: the decks play from the screen (LEARN: any controller)")
            first = False
            self.stop.wait(2)

    def lights(self):
        self.hercules.lights()
        for m in self.maps.values():
            m.lights()

    def run(self):
        self.load_maps()
        threading.Thread(target=self.watch_ports, daemon=True).start()   # (no MIDI at all: the screen plays)
        threading.Thread(target=self.loader, daemon=True).start()
        threading.Thread(target=self.keeper, daemon=True).start()
        self.restore()
        threading.Thread(target=self.watch_drives, daemon=True).start()   # (the sound never waits on a mount)
        out = Output(self.out_to)
        try:
            while not self.stop.is_set():
                if out.to != self.out_to:        # DJ decks out changed: the streams made again
                    out.close()
                    out = Output(self.out_to)
                master, phones = self.engine.render(BLOCK)
                out.write(master, phones)        # the write waits for room: real time
        finally:
            out.close()

    def status(self):
        """what the screen shows"""
        rows = []
        for d in self.engine.decks:
            t = d.track
            rows.append({"name": d.name, "title": t.title if t else None, "artist": t.artist if t else "",
                         "bpm": round(d.bpm_now(), 1) if d.bpm_now() else None, "key": t.key if t else None,
                         "pos": d.pos / t.rate if t else 0.0, "len": t.frames / t.rate if t else 0.0,
                         "playing": d.playing, "pitch": round(d.pitch * PITCH_RANGE * 100, 2), "loop": bool(d.loop),
                         "synced": d.synced, "camelot": djlib.camelot(t.key) if t and t.key else None,
                         "cues": sorted([k, round(v / t.frames, 4), t.cue_colors.get(k) or CUE_COLORS[k]]
                                        for k, v in t.cues.items()) if t else [],
                         "loop_at": [round(v / t.frames, 4) for v in d.loop] if t and d.loop else None,
                         "pfl": d.pfl, "volume": d.volume, "loading": d.loading, "error": d.error})
        sel = self.library[self.cursor] if self.library else None
        return {"decks": rows, "xfade": self.engine.xfade, "cursor": self.cursor, "count": len(self.library),
                "scanning": self.scanning, "source": self.browsed()["name"],
                "usb": bool(self.browsed()["uuid"]), "sources": len(self.sources),
                "selected": sel and {"title": sel[1].get("title"), "bpm": sel[1].get("bpm"),
                                     "key": sel[1].get("key"), "camelot": sel[1].get("camelot")},
                "ports": [[n, n in self.maps, HERCULES in n] for n in self.inputs],
                "learn": self.learn_status()}

    def learn_status(self):
        lr = self.learner
        if not lr:
            return None
        out = lr.status()
        if lr.action is None:                    # the list: every control and what it's on
            bound = {b["action"]: describe(b) for b in lr.binds}
            out["map"] = [[a, deck, label, bound.get(a)] for a, deck, label, _kind in LEARN]
        return out

    def learn_command(self, name, args):
        """LEARN's messages from the screen"""
        lr = self.learner
        if name == "learn":                      # [port, guided?, action]: learning starts (or one control)
            port, guided = args[0], bool(args[1]) if len(args) > 1 else True
            binds = self.maps[port].binds if port in self.maps else []
            step = next((i for i, s in enumerate(LEARN) if s[0] == args[2]), 0) if len(args) > 2 else 0
            self.learner = Learner(port, binds, guided, step if args[2:] or guided else len(LEARN))
        elif name == "learn_list" and args:      # a controller's map, to look at
            self.learner = Learner(args[0], self.maps[args[0]].binds if args[0] in self.maps else [], False,
                                   len(LEARN))
        elif not lr:
            return
        elif name == "learn_skip":
            lr.next()
            if lr.action is None:
                lr.guided = False
        elif name == "learn_back":
            lr.next(-1)
        elif name == "learn_done":               # the guided run (or one control) left: the list
            lr.guided, lr.step = False, len(LEARN)
        elif name == "learn_clear" and args:     # a control taken off the map
            lr.binds = [b for b in lr.binds if b["action"] != args[0]]
            if lr.port in self.maps:
                self.maps[lr.port].set(lr.binds)
                self.save_maps()
        elif name == "learn_forget":             # the whole map gone (the Hercules: its own map again)
            self.maps.pop(lr.port, None)
            lr.binds = []
            self.save_maps()
            if lr.port in self.ports and HERCULES in lr.port:
                self.hercules.out = self.ports[lr.port][1]
        elif name == "learn_end":
            self.learner = None


    # ---- the Companion's side talks to this one through stdin / stdout, a JSON message a line (DeckProcess)

    def scan(self, say):
        def progress(i, n, name):
            self.scanning = f"{i + 1}/{n}"
        try:
            src = self.browsed()
            djlib.scan(src["folder"], progress=progress, cache_file=self.cache_of(src))
            self.listings.pop(src["uuid"], None)    # (its BPM and key: in the list again)
        except OSError as e:
            say({"error": f"scan: {e}"[:60]})
        self.scanning = None
        self.refresh()
        say(self.library_message())

    def library_message(self):
        return {"library": [[rel, e.get("title") or rel, e.get("artist") or "", e.get("bpm"), e.get("key"),
                             e.get("camelot")] for rel, e in self.library]}

    def command(self, cmd, say):
        """one message from the screen: [name, args...]"""
        name, args = cmd[0], cmd[1:]
        e = self.engine
        with e.lock:
            d = e.decks[args[0]] if args and isinstance(args[0], int) and name not in ("select", "browse") \
                else None
            if name == "play" and d:
                d.play_pause(e.decks[1 - args[0]])
            elif name == "cue" and d:
                d.cue_press(bool(args[1]))
            elif name == "sync" and d:
                d.toggle_sync(e.decks[1 - args[0]])
            elif name == "pfl" and d:
                d.pfl = not d.pfl
            elif name == "gotocue" and d and d.track and int(args[1]) in d.track.cues:   # a cue's tag tapped
                d.pos = d.track.cues[int(args[1])]
            elif name == "clearcue" and d and d.track:        # a cue's tag held: gone
                d.hotcue(int(args[1]), True, clear=True)
            elif name == "seek" and d and d.track:          # a tap on the overview: there
                d.pos = max(0.0, min(1.0, float(args[1]))) * (d.track.frames - 1)
            elif name == "select" and self.library:
                self.cursor = max(0, min(len(self.library) - 1, int(args[0])))
            elif name == "browse":
                self.browse(int(args[0]))
        if name == "output" and args and args[0] in ("studio", "hercules"):   # Settings > Audio > DJ decks out
            self.out_to = args[0]
        elif name.startswith("learn"):
            with e.lock:
                self.learn_command(name, args)
        elif name == "load":
            self.load_selected(int(args[0]))
        elif name == "source" and not self.scanning:     # the next source: the Studio's, each USB drive
            self.pick_source(self.source + 1)
        elif name == "scan" and not self.scanning:
            self.scanning = "starting"
            threading.Thread(target=self.scan, args=(say,), daemon=True).start()
        self.lights()


def serve():
    """run for the Companion: commands in on stdin, the status (5 a second), the library and each loaded
    track's overview out on stdout"""
    import json
    import sys
    decks = Decks()
    lock = threading.Lock()

    def say(obj):
        with lock:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()
    decks.say = say
    decks.note = lambda text: say({"note": text})
    decks.on_loaded = lambda deck, track: say({"overview": [deck, track.overview]})
    say(decks.library_message())

    def status():
        while not decks.stop.is_set():
            try:
                say({"status": decks.status()})
            except Exception as e:               # (one bad reading never stops the screen's updates)
                say({"error": f"status: {e}"[:80]})
            time.sleep(0.2)
    threading.Thread(target=status, daemon=True).start()
    threading.Thread(target=decks.run, daemon=True).start()
    for line in sys.stdin:                       # (stdin closed: the Companion is gone)
        try:
            cmd = json.loads(line)
        except ValueError:
            continue
        if cmd == ["quit"]:
            break
        try:
            decks.command(cmd, say)
        except Exception as e:                   # (one bad message never stops the music)
            say({"error": str(e)[:80]})
    decks.save_memory()                          # (the last word: the session as it ends)
    decks.stop.set()
    time.sleep(0.3)


class DeckProcess:
    """the Companion's side: decks.py --serve started as a program of its own (dies with the Companion), its
    messages read on a thread: the latest status, the library, each deck's overview"""

    def __init__(self, on_change=lambda: None):
        self.proc, self.on_change = None, on_change
        self.status, self.library, self.overviews, self.note = None, [], {0: [], 1: []}, None
        self.library_n = self.note_n = 0          # counted as they come: the screen sees a new one, even the same

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        import ctypes
        import signal
        import sys
        if self.running():
            return
        self.status, self.overviews, self.note = None, {0: [], 1: []}, None   # (nothing left from a last run)
        libc = ctypes.CDLL(None)
        self.proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True, bufsize=1, preexec_fn=lambda: libc.prctl(1, signal.SIGTERM))
        threading.Thread(target=self.read, args=(self.proc,), daemon=True).start()

    def read(self, proc):
        import json
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if "status" in msg:
                self.status = msg["status"]
            elif "library" in msg:
                self.library = msg["library"]
                self.library_n += 1
            elif "overview" in msg:
                self.overviews[msg["overview"][0]] = msg["overview"][1]
            elif "note" in msg or "error" in msg:
                self.note = msg.get("note") or msg.get("error")
                self.note_n += 1
            self.on_change()

    def send(self, *cmd):
        import json
        if self.running():
            try:
                self.proc.stdin.write(json.dumps(list(cmd)) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def stop(self):
        if self.running():
            self.send("quit")
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
        self.proc, self.status = None, None


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["scan"]:
        djlib.main(["scan"])
    elif sys.argv[1:2] == ["--serve"]:
        serve()
    else:
        decks = Decks()
        print(f"{len(decks.library)} tracks; the Hercules: browse, LOAD A / B, play")

        def show():
            last = None
            while True:
                s = decks.status()
                line = " | ".join(f"{r['name']}: {(r['title'] or '-')[:24]} {r['bpm'] or ''} "
                                  f"{'PLAY' if r['playing'] else 'stop'} {r['pos']:6.1f}s" for r in s["decks"])
                sel = s["selected"]
                line += f" || {s['cursor'] + 1}/{s['count']} {(sel or {}).get('title', '')[:30]}"
                e = decks.engine
                line += " || " + " ".join(f"{d.name}: gain {d.gain:.2f} vol {d.volume:.2f} lo {d.tone.low:.2f} "
                                          f"hi {d.tone.high:.2f} filt {d.tone.filter:.2f}" for d in e.decks)
                line += f" xf {e.xfade:.2f} peak {e.peak:.2f} limited {e.limited}"
                line += " || " + " ".join(f"{d.name}: fader {d.fader:+.2f} pitch {d.pitch:+.2f} sync {int(d.synced)}"
                                          for d in e.decks)
                line += f" msgs {decks.hercules.count}"
                if line != last:
                    print(line, flush=True)
                    last = line
                time.sleep(0.5)
        threading.Thread(target=show, daemon=True).start()
        decks.run()
