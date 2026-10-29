"""The FM-1's panel played from any MIDI controller, for SLOOP and X0X on the Studio: a control of yours (a pad, a key,
a button, a knob, a fader) learnt onto one of the FM-1's (tap it on the Studio's picture of the FM-1, then move
yours), then sent as FM-1 A's REMOTE OUT sends it (SLOOP Remote Out's panel.c), so the apps take it as FM-1 A's:

  the 14 buttons   CC 102 + k on channel 16, 127 down, 0 up (FX SEL ENV LFO EDIT GLO HOME SAVE ARP SEQ PLAY REC OCT- OCT+)
  the 7 knobs      CC 85 + k, 64 + the steps turned (SELECT ALGORITHM PRESETS KNOB 1-4): FM-1 A's own are CC 116 + k,
                   accelerated by the apps as the FM-1 does; these the apps (our forks) take as exact steps
  MASTER           CC 123, where it is (0 .. 127)
  the 27 keys      notes 36 + k (F up to G, chromatic), 100 / off

A button or a key takes a button of yours (a note, or a CC that comes up from 0). A knob takes a knob or fader of
yours: one that sends where it is (each of its values a step of the FM-1's: its 128 come a few ms apart, which the
apps' knob acceleration would have read as a fast spin, so they're sent as exact steps) or an endless one that sends
steps (1 / 127, or 63 / 65). MASTER takes one that sends where it is. The maps are kept by controller (its MIDI port's name) in
~/fm1-library/.studio-fm1-controls.json. Used by the MIDI process (blemidi.py): while an app runs, a mapped control
goes to it alone; with none running, the controller plays as it always does."""
import json
import os
import re
import threading
from pathlib import Path

LIBRARY = Path(os.environ.get("FM1_LIBRARY", Path.home() / "fm1-library"))
FILE = ".studio-fm1-controls.json"
CH = 15                                        # channel 16: FM-1 A's REMOTE OUT, as the apps read it (deskui.APP_CH)
TAP = 0.08                                     # a button that never says it's let go: let go this long after
EXACT_CC = 85                                  # the knobs' exact steps (sloop-remote-out, x0x-companion-studio)
BUTTONS = ("FX", "SEL", "ENV", "LFO", "EDIT", "GLO", "HOME", "SAVE", "ARP", "SEQ", "PLAY", "REC", "OCT-", "OCT+")
KNOBS = ("SELECT", "ALGORITHM", "PRESETS", "KNOB 1", "KNOB 2", "KNOB 3", "KNOB 4")
NOTES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
KEYS = 27                                      # F .. G, two octaves and a bit


def controls():
    """every control of the FM-1's: "btn:k", "knob:k", "master", "key:k" """
    return ([f"btn:{k}" for k in range(len(BUTTONS))] + [f"knob:{k}" for k in range(len(KNOBS))] + ["master"]
            + [f"key:{k}" for k in range(KEYS)])


def name(control):
    """a control's name as the FM-1 has it: "PLAY", "KNOB 2", "MASTER", "KEY F#3" """
    kind, _, k = control.partition(":")
    if kind == "btn":
        return BUTTONS[int(k)]
    if kind == "knob":
        return KNOBS[int(k)]
    if kind == "master":
        return "MASTER"
    note = 53 + int(k)                         # the lowest key F3 (seq.c: the 27 keys are notes 53 .. 79)
    return f"KEY {NOTES[note % 12]}{note // 12 - 1}"


def black(k):
    """key k is one of the raised (sharp) keys"""
    return (5 + k) % 12 in (1, 3, 6, 8, 10)


def port_base(port):
    """a MIDI port's name without ALSA's client:port numbers on its end (they can change from boot to boot)"""
    return re.sub(r"\s+\d+:\d+$", "", port)


def endless(vals):
    """a knob's first few values: an endless one's steps (the same one or two again and again, or small steps
    either way: 1 / 127, 63 / 65) rather than where it is (a knob or fader turned goes one way, a value each)"""
    if len(set(vals)) <= 2:
        return True
    if all(1 <= v <= 20 for v in vals) or all(108 <= v <= 127 for v in vals):
        return True                            # steps one way, bigger as it speeds up (an MPK mini IV's relative
                                               # knobs: 1, 2, 3, 5 ... looked like a knob going up from 1)
    ups = all(b > a for a, b in zip(vals, vals[1:]))
    downs = all(b < a for a, b in zip(vals, vals[1:]))
    return not (ups or downs) and all(v <= 15 or v >= 113 or 48 <= v <= 80 for v in vals)


def describe(b):
    what = "PITCH BEND" if b["type"] == "pb" else f"{'NOTE' if b['type'] == 'note' else 'CC'} {b['num']}"
    return f"{b['port'].split(':')[0]}: {what} CH {b['ch'] + 1}"


class Mapper:
    def __init__(self, folder=None):
        self.path = (folder or LIBRARY) / FILE
        self.lock = threading.Lock()
        self.maps = self.read()                # {port: [{"control", "type", "ch", "num", "how"}]}
        self.learning = None                   # the FM-1 control a control of yours is being learnt onto
        self.heard, self.count = None, 0       # the last learnt (said on the screen); learnt so far (a new one)
        self.seen = {}                         # while learning: the messages so far, by (port, type, ch, num)
        self.last = {}                         # a knob of yours that sends where it is: where it was
        self.master = {}                       # MASTER from an endless knob: where it's got to
        self.lets_go = set()                   # CC buttons of yours seen letting go (sending below 64)
        self.later = []                        # (play: a tap's let go, sent TAP seconds on)

    def read(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        return {p: [b for b in v if isinstance(b, dict) and b.get("control") in controls()]
                for p, v in data.items() if isinstance(v, list)} if isinstance(data, dict) else {}

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(FILE + ".tmp")
            tmp.write_text(json.dumps(self.maps, indent=1))
            tmp.replace(self.path)
        except OSError:
            pass

    # ---- the screen's

    def learn(self, control):
        """learning control (None: not)"""
        with self.lock:
            self.learning = control if control in controls() else None
            self.seen = {}

    def clear(self, control):
        """control taken off every controller's map"""
        with self.lock:
            for port in list(self.maps):
                self.maps[port] = [b for b in self.maps[port] if b["control"] != control]
                if not self.maps[port]:
                    del self.maps[port]
            self.save()

    def forget(self):
        with self.lock:
            self.maps, self.learning = {}, None
            self.save()

    def status(self):
        with self.lock:
            mapped = {}
            for port, binds in self.maps.items():
                for b in binds:
                    mapped.setdefault(b["control"], describe(dict(b, port=port)))
            return {"learning": self.learning, "heard": self.heard, "count": self.count, "map": mapped}

    # ---- the MIDI process's

    def handle(self, port, message, running, send):
        """a message from a controller (port: its MIDI port's name): -> True when it was taken (learning one, or a
        mapped control while an app runs: send gets what FM-1 A would have sent)"""
        if len(message) < 3 or message[0] >= 0xF0:
            return False
        port = port_base(port or "USB")
        with self.lock:
            if self.learning:
                self.hear(port, message)
                return True                    # (learning: what's played goes nowhere else)
            if not running:
                return False
            kind, ch, num, val = message[0] & 0xF0, message[0] & 0x0F, message[1], message[2]
            typ = "note" if kind in (0x80, 0x90) else "cc" if kind == 0xB0 else "pb" if kind == 0xE0 else None
            b = next((b for b in self.maps.get(port, ()) if (b["type"], b["ch"]) == (typ, ch)
                      and (typ == "pb" or b["num"] == num)), None)
            if not b:
                return False
            self.later = []
            out, later = self.play(port, b, kind, num, val), self.later
        for m in out:
            send(m)
        if later:                              # a tap's let go, a moment on (X0X reads its buttons now and then)
            threading.Timer(TAP, lambda: [send(m) for m in later]).start()
        return True

    def play(self, port, b, kind, num, val):
        """a mapped control of yours -> what FM-1 A sends for its control"""
        control, how = b["control"], b.get("how", "button")
        target, _, k = control.partition(":")
        if how == "button":
            down = kind == 0x90 and val > 0 if b["type"] == "note" else val >= 64
            press = [[0xB0 | CH, 102 + int(k), 127]] if target == "btn" else [[0x90 | CH, 36 + int(k), 100]]
            let_go = [[0xB0 | CH, 102 + int(k), 0]] if target == "btn" else [[0x80 | CH, 36 + int(k), 0]]
            if b["type"] == "cc":
                key = (port, b["ch"], b["num"])
                if not down:
                    self.lets_go.add(key)
                elif key not in self.lets_go:      # a button that only ever sends 127 (an MPK mini IV's PLAY,
                    self.later = let_go            # REC ...): a tap, let go of TAP seconds on
                    return press
            return press if down else let_go
        if b["type"] == "pb":
            val = ((val << 7) | num) >> 7
        if how in ("twos", "center"):
            steps = val - 64 if how == "center" else (val if val < 64 else val - 128)
        else:                                  # where it is: the steps since last time
            key = (port, b["type"], b["ch"], b["num"])
            before, self.last[key] = self.last.get(key), val
            steps = 0 if before is None else val - before
            if before == val and val in (0, 127):  # an endless knob at its end, sent again as it turns on:
                steps = 1 if val else -1           # a step on (the FM-1's knobs have no ends)
        if target == "master":
            if how == "absolute":
                return [[0xB0 | CH, 123, val]]
            pos = max(0, min(127, self.master.get(port, 100) + steps))
            self.master[port] = pos
            return [[0xB0 | CH, 123, pos]]
        if not steps:
            return []
        return [[0xB0 | CH, EXACT_CC + int(k), 64 + max(-63, min(63, steps))]]

    def hear(self, port, message):
        """learning: a control of yours that fits the FM-1's control being learnt"""
        kind, ch, num, val = message[0] & 0xF0, message[0] & 0x0F, message[1], message[2]
        target = self.learning.split(":")[0]
        got = None
        if target in ("btn", "key"):
            if kind == 0x90 and val > 0:
                got = {"type": "note", "ch": ch, "num": num, "how": "button"}
            elif kind == 0xB0 and val >= 64 and self.seen.get((port, "cc", ch, num), [0])[-1] < 64:
                got = {"type": "cc", "ch": ch, "num": num, "how": "button"}
            elif kind == 0xB0:
                self.seen.setdefault((port, "cc", ch, num), []).append(val)
        elif kind in (0xB0, 0xE0):
            typ = "cc" if kind == 0xB0 else "pb"
            vals = self.seen.setdefault((port, typ, ch, num if typ == "cc" else 0), [])
            vals.append(val)
            if len(vals) >= 4:
                if typ == "cc" and endless(vals):
                    how = "center" if all(48 <= v <= 80 for v in vals) else "twos"
                elif len(set(vals)) >= 3:                     # where it is
                    how = "absolute"
                else:
                    return
                got = {"type": typ, "ch": ch, "num": num if typ == "cc" else 0, "how": how}
        if not got:
            return
        got["control"] = self.learning
        binds = self.maps.setdefault(port, [])
        binds[:] = [b for b in binds if b["control"] != self.learning
                    and not ((b["type"], b["ch"], b["num"]) == (got["type"], got["ch"], got["num"]))]  # one job each
        binds.append(got)
        self.heard = f"{name(self.learning)} = {describe(dict(got, port=port))}"
        self.count += 1
        self.learning, self.seen = None, {}
        self.save()
