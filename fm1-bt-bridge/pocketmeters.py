"""The meters on the Pocket's 1.44" colour LCD: the eleven of meters.py redrawn for 128x128 in the theme's colours
(pocketui's header and hint around each), from the same state as the OLED's (MeterScreens' step_ methods). Levels
go green, then yellow from -12 dBFS, red from -6 dBFS, as on a mixer's meters."""
import math

from PIL import Image

import meters
import pocketui as ui
import sloopstyle as st
from meters import (FLOOR, METERS, REEL_R, REELS, HUB_R, WHITE, bar_x, beat_position, chord_name, clock, db,
                    goniometer, note_name, scope_trace, spectrum_height, vu_angle)

TOP, BOTTOM = 20, ui.FOOT - 2                  # the meter's room between the header and the hint
WF_ROWS = BOTTOM - TOP                         # the Waterfall's history: a row a frame


def level_colour(t, level):
    """a level in dBFS: green, yellow from -12, red from -6"""
    return ui.REC if level > -6 else t.track[2] if level > -12 else t.track[1]


def big(img, xy, s, colour, size=3):
    """s in Terminus at size times 16 px (SLOOP's big values), its top left at xy"""
    st.text(img, xy, s, colour, size=size)


def centred(img, d, t, lines, y, colour=None):
    for i, line in enumerate(lines):
        line = ui.cut(line, 21)
        ui.text(d, ((ui.W - ui.width(line)) // 2, y + i * 13), line, colour or t.c[3])


class PocketMeters:
    """the meter screen on the LCD (part of the app: needs MeterScreens)"""

    def colour_meter(self, img, d, t):
        now = self.frame_now
        index = self.meter_index()
        style = METERS[index]
        rec = self.recorder.recording()
        ui.header(img, d, t, style, right="" if rec else f"{index + 1}/{len(METERS)}")
        if rec:                                # REC and the time where the count goes, as on HOME
            tag = "REC " + clock(self.recorder.seconds(now))
            w = ui.width(tag)
            d.rounded_rectangle((ui.W - 6 - w, 2, ui.W - 2, 15), 3, fill=ui.REC)
            ui.text(d, (ui.W - 4 - w, 3), tag, t.bg)
        ui.footer(d, t, ("press = stop" if rec else "press = REC") + "  home >")
        if style == "MIDI":
            self.colour_midi(img, d, t, now)
            return
        if style == "Beat":
            self.colour_beat(img, d, t, now)
            return
        problem = self.meter_problem()
        if problem:
            centred(img, d, t, [problem], 60)
            return
        dt, peak, rms, recent = self.meter_sound(now)
        getattr(self, "colour_" + style.lower())(img, d, t, now, dt, peak, rms, recent)

    def colour_bars(self, img, d, t, now, dt, peak, rms, recent):
        """L and R as LED segments (unlit ones faint), the peak hold a white line, the scale under them"""
        for (ch, y), level in zip(((0, 30), (1, 58)), self.step_bars(now, dt, peak)):
            ui.text(d, (1, y + 6), "LR"[ch], t.c[3])
            for x in range(12, 124, 4):
                seg = -48 + 48 * (x - 12) / 112
                d.rectangle((x, y, x + 2, y + 22), fill=level_colour(t, seg) if x < bar_x(level) else t.c[0])
            hold = self.m_hold[ch][0]
            if hold > -48:
                x = bar_x(hold)
                d.rectangle((x - 1, y - 2, x, y + 24), fill=t.hi)
            if hold > -0.2:
                ui.text(d, (64 - ui.width("CLIP") // 2, 3), "CLIP", ui.REC)
        for value in (-48, -36, -24, -12, -6, 0):
            x = bar_x(value)
            d.line((x, 86, x, 89), fill=t.c[2])
            label = str(value)
            ui.text(d, (min(127 - ui.width(label), max(0, x - ui.width(label) // 2)), 92), label, t.c[2])

    def colour_vu(self, img, d, t, now, dt, peak, rms, recent):
        """two VU dials, their needles from pivots under the screen; a red lamp when a channel nears 0 dBFS"""
        self.step_vu(now, dt, peak, rms)
        py, r = 120, 60                        # the pivots, the scale's radius (two dials side by side)
        for ch, cx in ((0, 31), (1, 96)):
            d.arc((cx - r, py - r, cx + r, py + r), 241, 299, fill=t.c[3])
            d.arc((cx - r + 2, py - r + 2, cx + r - 2, py + r - 2), 270 + int(math.degrees(vu_angle(1.0))), 299,
                  fill=ui.REC, width=2)
            for value in (-20, -10, -7, -5, -3, -2, -1, 0, 1, 2, 3):
                a = vu_angle(10 ** (value / 20))
                inner = r - 9 if value in (-20, -10, 0, 3) else r - 5
                d.line((cx + inner * math.sin(a), py - inner * math.cos(a), cx + r * math.sin(a),
                        py - r * math.cos(a)), fill=ui.REC if value > 0 else t.c[3])
            angle = vu_angle(self.m_vu[ch])
            d.line((cx + 20 * math.sin(angle), py - 20 * math.cos(angle),
                    cx + (r + 4) * math.sin(angle), py - (r + 4) * math.cos(angle)), fill=t.hi, width=2)
            ui.text(d, (cx - 3, TOP + 2), "LR"[ch], t.c[3])
            lamp = now - self.m_clip[ch] < 0.6
            d.ellipse((cx + 18, TOP + 4, cx + 25, TOP + 11), fill=ui.REC if lamp else t.c[0])
        d.rectangle((0, ui.FOOT - 14, ui.W, ui.FOOT - 1), fill=t.bg)     # the needles' feet out of sight
        d.line((0, ui.FOOT - 14, ui.W, ui.FOOT - 14), fill=t.c[1])
        ui.text(d, (64 - ui.width("VU") // 2, ui.FOOT - 13), "VU", t.c[2])

    def colour_spectrum(self, img, d, t, now, dt, peak, rms, recent):
        """16 bands, green at the bottom, yellow, red at the top; each band's cap a white line falling slower"""
        self.step_spectrum(dt, recent)
        room = BOTTOM - TOP - 2
        for i, level in enumerate(self.m_bands):
            h = round(spectrum_height(level) * room / 52)
            x = i * 8
            for y0, y1, colour in ((0, 0.6, t.track[1]), (0.6, 0.85, t.track[2]), (0.85, 1.0, ui.REC)):
                lo, hi = round(y0 * room), min(h, round(y1 * room))
                if hi > lo:
                    d.rectangle((x, BOTTOM - hi, x + 6, BOTTOM - lo), fill=colour)
            cap = round(spectrum_height(self.m_caps[i]) * room / 52)
            if cap > h + 1:
                d.line((x, BOTTOM - cap, x + 6, BOTTOM - cap), fill=t.hi)

    def colour_scope(self, img, d, t, now, dt, peak, rms, recent):
        """the wave, steady on a rising zero, over a faint grid"""
        mid, amp = (TOP + BOTTOM) // 2, (BOTTOM - TOP) // 2 - 2
        for y in (mid - amp // 2, mid + amp // 2):
            for x in range(0, ui.W, 4):
                d.point((x, y), fill=t.c[0])
        for x in range(0, ui.W, 2):
            d.point((x, mid), fill=t.c[1])
        trace = scope_trace(recent)
        if trace is not None and len(trace) > 1:
            d.line(list(enumerate((mid - trace * amp).tolist())), fill=t.track[0], width=1)

    def colour_tape(self, img, d, t, now, dt, peak, rms, recent):
        """the two reels winding while recording and turning while sound plays, the head's levels between"""
        packs = self.step_tape(dt, peak)
        ry, guide = 58, 92
        for i, (cx, pack) in enumerate(zip(REELS, packs)):
            a = self.m_reels[i]
            d.ellipse((cx - REEL_R, ry - REEL_R, cx + REEL_R, ry + REEL_R), outline=t.c[3])
            d.ellipse((cx - pack, ry - pack, cx + pack, ry + pack), fill=t.mid[3])                 # wound tape
            d.ellipse((cx - HUB_R, ry - HUB_R, cx + HUB_R, ry + HUB_R), fill=t.bg, outline=t.hi)
            for k in range(3):
                b = a + k * 2 * math.pi / 3
                d.line((cx + 1.5 * math.cos(b), ry + 1.5 * math.sin(b),
                        cx + HUB_R * math.cos(b), ry + HUB_R * math.sin(b)), fill=t.hi)
                h = b + math.pi / 3
                hx, hy = cx + 12 * math.cos(h), ry + 12 * math.sin(h)
                d.ellipse((hx - 2.5, hy - 2.5, hx + 2.5, hy + 2.5), fill=t.bg, outline=t.c[3])
            side = -1 if i == 0 else 1
            d.line((cx + side * pack * 0.7, ry + pack * 0.7, 5 if i == 0 else 122, guide), fill=t.mid[3])
        for x in (5, 122):
            d.ellipse((x - 2, guide - 4, x + 2, guide), outline=t.c[3])
        d.line((5, guide, 122, guide), fill=t.mid[3])
        d.rectangle((57, guide - 6, 70, guide), fill=t.hi)                   # the record head
        d.ellipse((80, guide - 4, 84, guide), fill=t.c[3])                   # capstan
        for ch, x in ((0, 57), (1, 66)):
            level = max(-48.0, min(0.0, db(peak[ch])))
            h = int(round(36 * (level + 48) / 48))
            if h:
                d.rectangle((x, guide - 10 - h, x + 4, guide - 10), fill=level_colour(t, level))

    def colour_tuner(self, img, d, t, now, dt, peak, rms, recent):
        """the note, big: green in tune (within 5 cents, boxed), yellow within 20, red further; its frequency,
        the cents, and a pointer over -50 .. +50"""
        tune = self.step_tuner(now, dt, peak, recent)
        scale_y = 100
        d.line((14, scale_y, 114, scale_y), fill=t.c[2])
        for c in (-50, -25, 0, 25, 50):
            x = 64 + c
            d.line((x, scale_y - (3 if c else 6), x, scale_y + (3 if c else 6)), fill=t.c[2])
        ui.text(d, (3, scale_y - 6), "b", t.c[2])
        ui.text(d, (117, scale_y - 6), "#", t.c[2])
        if not tune:
            big(img, (64 - 36, 34), "- -", t.c[1])
            return
        name, octave, cents, freq = tune[:4]
        colour = t.track[1] if abs(cents) < 5 else t.track[2] if abs(cents) < 20 else ui.REC
        note = f"{name}{octave}"
        w = len(note) * 24
        if abs(cents) < 5:
            d.rectangle((60 - w // 2, 28, 68 + w // 2, 80), outline=colour, width=2)
        big(img, (64 - w // 2, 31), note, colour)
        ui.text(d, (2, 84), f"{cents:+.0f}", t.c[4])
        hz = f"{freq:.1f} Hz"
        ui.text(d, (126 - ui.width(hz), 84), hz, t.c[4])
        x = 64 + max(-50, min(50, int(round(cents))))
        d.polygon(((x - 4, scale_y - 9), (x + 4, scale_y - 9), (x, scale_y - 2)), fill=colour)

    def colour_midi(self, img, d, t, now):
        """three octaves lighting the notes played, the chord and notes above, the 16 channels below"""
        notes, chans = self.step_midi(now)
        line = "  ".join(x for x in (chord_name(notes), " ".join(note_name(n) for n in notes[:4])) if x) \
            if notes else ("no MIDI" if not self.midi else "")
        ui.text(d, (2, TOP + 2), ui.cut(line, 21), t.hi)
        held, top, left = set(notes), 38, 1
        for i in range(21):                    # white keys
            note = self.m_base + 12 * (i // 7) + WHITE[i % 7]
            x = left + i * 6
            d.rectangle((x, top, x + 5, top + 40), fill=t.track[0] if note in held else t.hi, outline=t.bg)
        for i in range(21):                    # black keys
            if WHITE[i % 7] in (4, 11) or i == 20:
                continue
            note = self.m_base + 12 * (i // 7) + WHITE[i % 7] + 1
            x = left + i * 6 + 4
            d.rectangle((x, top, x + 3, top + 24), fill=t.track[3] if note in held else t.bg)
        ui.text(d, (left, top + 42), note_name(self.m_base), t.c[2])
        ui.text(d, (2, 96), "CH", t.c[2])
        for ch in range(16):
            x = 18 + ch * 6 + (ch // 4) * 3
            if chans & (1 << ch):
                d.rectangle((x, 96, x + 4, 107), fill=t.track[1])
            else:
                d.rectangle((x, 105, x + 4, 107), fill=t.c[1])

    def colour_waterfall(self, img, d, t, now, dt, peak, rms, recent):
        """the spectrum scrolling down, ~3 s of it: the newest row at the top, louder brighter (the theme's
        shades up to white)"""
        np = meters.numpy()
        if getattr(self, "m_wfl", None) is None:
            self.m_wfl = np.zeros((WF_ROWS, 64), dtype=np.float32)
        level = self.step_waterfall(recent)
        if level is not None:
            self.m_wfl = np.roll(self.m_wfl, 1, axis=0)
            self.m_wfl[0] = level
        stops = [t.bg, t.c[1], t.c[3], t.c[4], t.hi]
        palette = []
        for k in range(32):                    # 32 colours along the stops
            f = k / 31 * (len(stops) - 1)
            a, b = stops[int(f)], stops[min(len(stops) - 1, int(f) + 1)]
            palette += [round(x + (y - x) * (f - int(f))) for x, y in zip(a, b)]
        index = np.repeat((self.m_wfl * 31).astype(np.uint8), 2, axis=1)
        pic = Image.fromarray(index, "P")
        pic.putpalette(palette + [0] * (768 - len(palette)))
        img.paste(pic.convert("RGB"), (0, TOP))

    def colour_stereo(self, img, d, t, now, dt, peak, rms, recent):
        """the goniometer (mono: up the middle; wide: a cloud; out of phase: across), the correlation under it"""
        cx, cy, r = 64, 58, 34
        for k in range(0, r + 1, 3):
            d.point((cx - k, cy - k), fill=t.c[1])
            d.point((cx + k, cy - k), fill=t.c[1])
            d.point((cx - k, cy + k), fill=t.c[0])
            d.point((cx + k, cy + k), fill=t.c[0])
        ui.text(d, (cx - r - 2, cy - r - 4), "L", t.c[3])
        ui.text(d, (cx + r - 3, cy - r - 4), "R", t.c[3])
        if len(recent) >= 8:
            d.point([(cx + x, cy - y) for x, y in goniometer(recent, r)], fill=t.track[0])
            self.step_stereo(dt, recent)
        y = 102
        d.line((24, y, 104, y), fill=t.c[2])
        for x in (24, 64, 104):
            d.line((x, y - 2, x + 0, y + 2), fill=t.c[2])
        ui.text(d, (8, y - 6), "-1", t.c[2])
        ui.text(d, (108, y - 6), "+1", t.c[2])
        corr = max(-1.0, min(1.0, self.m_corr))
        x = 64 + int(round(40 * corr))
        colour = t.track[1] if corr > 0.3 else t.track[2] if corr > -0.1 else ui.REC
        d.polygon(((x - 4, y - 9), (x + 4, y - 9), (x, y - 3)), fill=colour)

    def colour_history(self, img, d, t, now, dt, peak, rms, recent):
        """the loudest peak of each 0.4 s over the last ~51 s, newest at the right, coloured by level"""
        self.step_history(now, peak)

        def y_of(level):
            return int(round(BOTTOM - (BOTTOM - TOP - 4) * (max(-48.0, min(0.0, level)) + 48) / 48))
        x0 = ui.W - len(self.m_hist)
        for i, level in enumerate(self.m_hist):
            if level > -48:
                d.line((x0 + i, y_of(level), x0 + i, BOTTOM), fill=level_colour(t, level))
        for level in (-12, -24, -36):
            y = y_of(level)
            for x in range(0, 108, 4):
                d.point((x, y), fill=t.c[2])
            label = str(level)
            d.rectangle((ui.W - ui.width(label) - 2, y - 12, ui.W - 1, y - 1), fill=t.bg)
            ui.text(d, (ui.W - ui.width(label), y - 12), label, t.c[2])

    def colour_beat(self, img, d, t, now):
        """the tempo, big (lit on each beat), where the clock comes from, and four beats lighting in time"""
        clock_in = getattr(self.midi, "clock", None) if self.midi else None
        if not clock_in:
            ui.text(d, (2, TOP + 4), "No clock coming in", t.hi)
            ui.draw_lines(d, t, ["Tap tempo on the home", "screen, or Settings >", "Playing > Clock: box"],
                          TOP + 26, t.c[3])
            return
        self.last_activity = now
        position = beat_position(clock_in, now)
        beat, flash = int(position) % 4, position % 1 < 0.15
        bpm = str(clock_in["bpm"])
        w = len(bpm) * 24
        if flash:
            d.rectangle((60 - w // 2, TOP + 6, 68 + w // 2, TOP + 56), fill=t.track[1])
        big(img, (64 - w // 2, TOP + 8), bpm, t.bg if flash else t.hi)
        ui.text(d, (2, TOP + 60), ("> " if clock_in.get("playing") else "") + "BPM", t.c[3])
        source = {"box": "box", "FM-1": "FM-1", "BT": "BT"}.get(clock_in.get("source"), "")
        ui.text(d, (126 - ui.width(source), TOP + 60), source, t.c[3])
        for i in range(4):
            x = 6 + i * 30
            top = TOP + 74 if i == 0 else TOP + 78
            if i == beat:
                d.rectangle((x, top, x + 25, BOTTOM - 2), fill=t.track[3] if i == 0 else t.track[1])
            else:
                d.rectangle((x, top, x + 25, BOTTOM - 2), outline=t.c[2])
