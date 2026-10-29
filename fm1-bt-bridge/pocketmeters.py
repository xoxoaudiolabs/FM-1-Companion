"""The meters on the Pocket's colour LCD: the eleven of meters.py redrawn in the theme's colours (pocketui's header
and hint around each), from the same state as the OLED's (MeterScreens' step_ methods). Levels go green, then
yellow from -12 dBFS, red from -6 dBFS, as on a mixer's meters. Laid out for 128x128 (the 1.44" LCD); at 120
(the 1.3" LCD, pocketui.use_size) X(), Y() and S() move the same drawings onto the smaller screen."""
import math

from PIL import Image

import meters
import pocketui as ui
import sloopstyle as st
from meters import (FLOOR, METERS, REEL_R, REELS, HUB_R, WHITE, bar_x, beat_position, chord_name, clock, db,
                    goniometer, note_name, scope_trace, spectrum_height, vu_angle)

TOP = 20                                       # the meter's room: from under the header to bottom() above the hint


def bottom():
    return ui.FOOT - 2


def X(v):
    """an x laid out for 128 wide, on this screen"""
    return v if ui.W == 128 else round(v * ui.W / 128)


def Y(v):
    """a y in the meter's room laid out for 128 high (20 .. 110), on this screen"""
    return v if ui.W == 128 else TOP + round((v - TOP) * (bottom() - TOP) / (110 - TOP))


def S(v):
    """a length laid out for 128, on this screen"""
    return v if ui.W == 128 else v * ui.W / 128


def level_colour(t, level):
    """a level in dBFS: green, yellow from -12, red from -6"""
    return ui.REC if level > -6 else t.track[2] if level > -12 else t.track[1]


def big(img, xy, s, colour, size=3):
    """s in Terminus at size times 16 px (SLOOP's big values), its top left at xy"""
    st.text(img, xy, s, colour, size=size)


def centred(img, d, t, lines, y, colour=None):
    for i, line in enumerate(lines):
        line = ui.cut(line, ui.CHARS)
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
            centred(img, d, t, [problem], Y(60))
            return
        dt, peak, rms, recent = self.meter_sound(now)
        getattr(self, "colour_" + style.lower())(img, d, t, now, dt, peak, rms, recent)

    def colour_bars(self, img, d, t, now, dt, peak, rms, recent):
        """L and R as LED segments (unlit ones faint), the peak hold a white line, the scale under them"""
        for (ch, y), level in zip(((0, Y(30)), (1, Y(58))), self.step_bars(now, dt, peak)):
            ui.text(d, (1, y + 6), "LR"[ch], t.c[3])
            for x in range(12, 124, 4):
                seg = -48 + 48 * (x - 12) / 112
                d.rectangle((X(x), y, X(x) + 2, y + 22), fill=level_colour(t, seg) if x < bar_x(level) else t.c[0])
            hold = self.m_hold[ch][0]
            if hold > -48:
                x = X(bar_x(hold))
                d.rectangle((x - 1, y - 2, x, y + 24), fill=t.hi)
            if hold > -0.2:
                ui.text(d, (ui.W // 2 - ui.width("CLIP") // 2, 3), "CLIP", ui.REC)
        for value in (-48, -36, -24, -12, -6, 0):
            x = X(bar_x(value))
            d.line((x, Y(86), x, Y(86) + 3), fill=t.c[2])
            label = str(value)
            ui.text(d, (min(ui.W - 1 - ui.width(label), max(0, x - ui.width(label) // 2)), Y(86) + 6), label,
                    t.c[2])

    def colour_vu(self, img, d, t, now, dt, peak, rms, recent):
        """two VU dials, their needles from pivots under the screen; a red lamp when a channel nears 0 dBFS"""
        self.step_vu(now, dt, peak, rms)
        py, r = ui.FOOT + 8, S(60)             # the pivots, the scale's radius (two dials side by side)
        for ch, cx in ((0, X(31)), (1, X(96))):
            d.arc((cx - r, py - r, cx + r, py + r), 241, 299, fill=t.c[3])
            d.arc((cx - r + 2, py - r + 2, cx + r - 2, py + r - 2), 270 + int(math.degrees(vu_angle(1.0))), 299,
                  fill=ui.REC, width=2)
            for value in (-20, -10, -7, -5, -3, -2, -1, 0, 1, 2, 3):
                a = vu_angle(10 ** (value / 20))
                inner = r - 9 if value in (-20, -10, 0, 3) else r - 5
                d.line((cx + inner * math.sin(a), py - inner * math.cos(a), cx + r * math.sin(a),
                        py - r * math.cos(a)), fill=ui.REC if value > 0 else t.c[3])
            angle = vu_angle(self.m_vu[ch])
            d.line((cx + S(20) * math.sin(angle), py - S(20) * math.cos(angle),
                    cx + (r + 4) * math.sin(angle), py - (r + 4) * math.cos(angle)), fill=t.hi, width=2)
            ui.text(d, (cx - 3, TOP + 2), "LR"[ch], t.c[3])
            lamp = now - self.m_clip[ch] < 0.6
            d.ellipse((cx + 18, TOP + 4, cx + 25, TOP + 11), fill=ui.REC if lamp else t.c[0])
        d.rectangle((0, ui.FOOT - 14, ui.W, ui.FOOT - 1), fill=t.bg)     # the needles' feet out of sight
        d.line((0, ui.FOOT - 14, ui.W, ui.FOOT - 14), fill=t.c[1])
        ui.text(d, (ui.W // 2 - ui.width("VU") // 2, ui.FOOT - 13), "VU", t.c[2])

    def colour_spectrum(self, img, d, t, now, dt, peak, rms, recent):
        """16 bands, green at the bottom, yellow, red at the top; each band's cap a white line falling slower"""
        self.step_spectrum(dt, recent)
        base = bottom()
        room = base - TOP - 2
        pitch = ui.W // 16                     # a band's column: 8 px (7 on the 120 screen), a gap of 1
        for i, level in enumerate(self.m_bands):
            h = round(spectrum_height(level) * room / 52)
            x = i * pitch
            for y0, y1, colour in ((0, 0.6, t.track[1]), (0.6, 0.85, t.track[2]), (0.85, 1.0, ui.REC)):
                lo, hi = round(y0 * room), min(h, round(y1 * room))
                if hi > lo:
                    d.rectangle((x, base - hi, x + pitch - 2, base - lo), fill=colour)
            cap = round(spectrum_height(self.m_caps[i]) * room / 52)
            if cap > h + 1:
                d.line((x, base - cap, x + pitch - 2, base - cap), fill=t.hi)

    def colour_scope(self, img, d, t, now, dt, peak, rms, recent):
        """the wave, steady on a rising zero, over a faint grid"""
        mid, amp = (TOP + bottom()) // 2, (bottom() - TOP) // 2 - 2
        for y in (mid - amp // 2, mid + amp // 2):
            for x in range(0, ui.W, 4):
                d.point((x, y), fill=t.c[0])
        for x in range(0, ui.W, 2):
            d.point((x, mid), fill=t.c[1])
        trace = scope_trace(recent)
        if trace is not None and len(trace) > 1:
            d.line(list(enumerate((mid - trace[:ui.W] * amp).tolist())), fill=t.track[0], width=1)

    def colour_tape(self, img, d, t, now, dt, peak, rms, recent):
        """the two reels winding while recording and turning while sound plays, the head's levels between"""
        packs = self.step_tape(dt, peak)
        ry, guide = Y(58), Y(92)
        reel, hub = S(REEL_R), S(HUB_R)
        for i, (cx, pack) in enumerate(zip(REELS, packs)):
            cx, pack = X(cx), S(pack)
            a = self.m_reels[i]
            d.ellipse((cx - reel, ry - reel, cx + reel, ry + reel), outline=t.c[3])
            d.ellipse((cx - pack, ry - pack, cx + pack, ry + pack), fill=t.mid[3])                 # wound tape
            d.ellipse((cx - hub, ry - hub, cx + hub, ry + hub), fill=t.bg, outline=t.hi)
            for k in range(3):
                b = a + k * 2 * math.pi / 3
                d.line((cx + 1.5 * math.cos(b), ry + 1.5 * math.sin(b),
                        cx + hub * math.cos(b), ry + hub * math.sin(b)), fill=t.hi)
                h = b + math.pi / 3
                hx, hy = cx + S(12) * math.cos(h), ry + S(12) * math.sin(h)
                d.ellipse((hx - 2.5, hy - 2.5, hx + 2.5, hy + 2.5), fill=t.bg, outline=t.c[3])
            side = -1 if i == 0 else 1
            d.line((cx + side * pack * 0.7, ry + pack * 0.7, X(5) if i == 0 else X(122), guide), fill=t.mid[3])
        for x in (X(5), X(122)):
            d.ellipse((x - 2, guide - 4, x + 2, guide), outline=t.c[3])
        d.line((X(5), guide, X(122), guide), fill=t.mid[3])
        d.rectangle((X(57), guide - 6, X(70), guide), fill=t.hi)             # the record head
        d.ellipse((X(80), guide - 4, X(80) + 4, guide), fill=t.c[3])         # capstan
        for ch, x in ((0, X(57)), (1, X(66))):
            level = max(-48.0, min(0.0, db(peak[ch])))
            h = int(round(36 * (level + 48) / 48))
            if h:
                d.rectangle((x, guide - 10 - h, x + 4, guide - 10), fill=level_colour(t, level))

    def colour_tuner(self, img, d, t, now, dt, peak, rms, recent):
        """the note, big: green in tune (within 5 cents, boxed), yellow within 20, red further; its frequency,
        the cents, and a pointer over -50 .. +50"""
        tune = self.step_tuner(now, dt, peak, recent)
        scale_y, mid = Y(100), ui.W // 2
        d.line((X(14), scale_y, X(114), scale_y), fill=t.c[2])
        for c in (-50, -25, 0, 25, 50):
            x = X(64 + c)
            d.line((x, scale_y - (3 if c else 6), x, scale_y + (3 if c else 6)), fill=t.c[2])
        ui.text(d, (3, scale_y - 6), "b", t.c[2])
        ui.text(d, (X(117), scale_y - 6), "#", t.c[2])
        if not tune:
            big(img, (mid - 36, Y(34)), "- -", t.c[1])
            return
        name, octave, cents, freq = tune[:4]
        colour = t.track[1] if abs(cents) < 5 else t.track[2] if abs(cents) < 20 else ui.REC
        note = f"{name}{octave}"
        w = len(note) * 24
        if abs(cents) < 5:
            d.rectangle((mid - 4 - w // 2, Y(28), mid + 4 + w // 2, Y(28) + 52), outline=colour, width=2)
        big(img, (mid - w // 2, Y(28) + 3), note, colour)
        ui.text(d, (2, Y(84)), f"{cents:+.0f}", t.c[4])
        hz = f"{freq:.1f} Hz"
        ui.text(d, (ui.W - 2 - ui.width(hz), Y(84)), hz, t.c[4])
        x = X(64 + max(-50, min(50, int(round(cents)))))
        if ui.W == 128:
            d.polygon(((x - 4, scale_y - 9), (x + 4, scale_y - 9), (x, scale_y - 2)), fill=colour)
        else:                                  # (under the scale, pointing up: the frequency is close above it)
            d.polygon(((x - 4, scale_y + 9), (x + 4, scale_y + 9), (x, scale_y + 2)), fill=colour)

    def colour_midi(self, img, d, t, now):
        """three octaves lighting the notes played, the chord and notes above, the 16 channels below"""
        notes, chans = self.step_midi(now)
        line = "  ".join(x for x in (chord_name(notes), " ".join(note_name(n) for n in notes[:4])) if x) \
            if notes else ("no MIDI" if not self.midi else "")
        ui.text(d, (2, TOP + 2), ui.cut(line, ui.CHARS), t.hi)
        key = 6 if ui.W == 128 else ui.W // 21    # a white key's width: 21 across (5 px on the 120 screen)
        tall = 40 if ui.W == 128 else 34          # (shorter there: the octave's name and the channels under it)
        held, top, left = set(notes), Y(38), (ui.W - 21 * key) // 2 or 1
        for i in range(21):                    # white keys
            note = self.m_base + 12 * (i // 7) + WHITE[i % 7]
            x = left + i * key
            d.rectangle((x, top, x + key - 1, top + tall), fill=t.track[0] if note in held else t.hi, outline=t.bg)
        for i in range(21):                    # black keys
            if WHITE[i % 7] in (4, 11) or i == 20:
                continue
            note = self.m_base + 12 * (i // 7) + WHITE[i % 7] + 1
            x = left + i * key + key - 2
            d.rectangle((x, top, x + key - 3, top + 24), fill=t.track[3] if note in held else t.bg)
        ui.text(d, (left, top + tall + 2), note_name(self.m_base), t.c[2])
        chans_y = Y(96)
        ui.text(d, (2, chans_y), "CH", t.c[2])
        for ch in range(16):
            x = X(18 + ch * 6 + (ch // 4) * 3)
            if chans & (1 << ch):
                d.rectangle((x, chans_y, x + 4, chans_y + 11), fill=t.track[1])
            else:
                d.rectangle((x, chans_y + 9, x + 4, chans_y + 11), fill=t.c[1])

    def colour_waterfall(self, img, d, t, now, dt, peak, rms, recent):
        """the spectrum scrolling down, ~3 s of it: the newest row at the top, louder brighter (the theme's
        shades up to white)"""
        np = meters.numpy()
        rows = bottom() - TOP                  # the history: a row a frame
        if getattr(self, "m_wfl", None) is None or self.m_wfl.shape[0] != rows:
            self.m_wfl = np.zeros((rows, 64), dtype=np.float32)
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
        if ui.W != 128:                        # (the 64 bands at 2 px fill 128: on the 120 screen, squeezed)
            pic = pic.resize((ui.W, rows), Image.NEAREST)
        img.paste(pic.convert("RGB"), (0, TOP))

    def colour_stereo(self, img, d, t, now, dt, peak, rms, recent):
        """the goniometer (mono: up the middle; wide: a cloud; out of phase: across), the correlation under it"""
        cx, cy, r = ui.W // 2, Y(58), round(S(34))
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
        y = Y(102)
        d.line((X(24), y, X(104), y), fill=t.c[2])
        for x in (X(24), cx, X(104)):
            d.line((x, y - 2, x + 0, y + 2), fill=t.c[2])
        ui.text(d, (X(8), y - 6), "-1", t.c[2])
        ui.text(d, (X(108), y - 6), "+1", t.c[2])
        corr = max(-1.0, min(1.0, self.m_corr))
        x = cx + int(round(S(40) * corr))
        colour = t.track[1] if corr > 0.3 else t.track[2] if corr > -0.1 else ui.REC
        d.polygon(((x - 4, y - 9), (x + 4, y - 9), (x, y - 3)), fill=colour)

    def colour_history(self, img, d, t, now, dt, peak, rms, recent):
        """the loudest peak of each 0.4 s over the last ~51 s, newest at the right, coloured by level"""
        self.step_history(now, peak)

        base = bottom()

        def y_of(level):
            return int(round(base - (base - TOP - 4) * (max(-48.0, min(0.0, level)) + 48) / 48))
        x0 = ui.W - len(self.m_hist)
        for i, level in enumerate(self.m_hist):
            if level > -48:
                d.line((x0 + i, y_of(level), x0 + i, base), fill=level_colour(t, level))
        for level in (-12, -24, -36):
            y = y_of(level)
            for x in range(0, X(108), 4):
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
        w, mid, base = len(bpm) * 24, ui.W // 2, bottom()
        if flash:
            d.rectangle((mid - 4 - w // 2, TOP + 6, mid + 4 + w // 2, TOP + 56), fill=t.track[1])
        big(img, (mid - w // 2, TOP + 8), bpm, t.bg if flash else t.hi)
        ui.text(d, (2, Y(TOP + 60)), ("> " if clock_in.get("playing") else "") + "BPM", t.c[3])
        source = {"box": "box", "FM-1": "FM-1", "BT": "BT"}.get(clock_in.get("source"), "")
        ui.text(d, (ui.W - 2 - ui.width(source), Y(TOP + 60)), source, t.c[3])
        for i in range(4):
            x, wide = X(6 + i * 30), round(S(25))
            top = Y(TOP + 74) if i == 0 else Y(TOP + 78)
            if i == beat:
                d.rectangle((x, top, x + wide, base - 2), fill=t.track[3] if i == 0 else t.track[1])
            else:
                d.rectangle((x, top, x + wide, base - 2), outline=t.c[2])
