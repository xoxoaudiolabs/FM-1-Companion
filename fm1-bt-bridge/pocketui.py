"""The Pocket's screens on a colour LCD (lcd.py), with the Studio's feel: SLOOP's colours (sloopstyle.Theme,
following FM-1 A as the Studio does) and its Terminus font, 12 px for the text and 16 px bold for titles. Drawn at
128x128 for the 1.44" LCD (21 characters a line, six rows to a list) or 120x120 for the 1.3" LCD, which shows
them at twice the size on its 240x240 (19 characters, five rows): use_size() picks one (GEOMETRY). The keys and joystick work these screens as they do the OLED's; what each screen
shows comes from the same methods the OLED's screens use.

PocketScreens (a part of the app, as LibraryScreens and MidiScreens are) draws HOME, Settings, the Bluetooth
scans, the library's lists, its confirm, job and player screens, and the MIDI routes, their options, presets and
channels: six rows to a list where the OLED has three; the sample editor, the screen saver and the splash at
start-up. The meters are pocketmeters.py's. The OLED's own drawings stay as they are, for the OLED HAT.
"""
import json
import re
import time

from PIL import Image, ImageDraw

import library
import sloopstyle as st

REC = st.rgb(226, 64, 48)                       # REC, as the Studio's STOP REC button
ROW_H, TOP = 15, 22                             # a list's rows under the header
GEOMETRY = {                                    # each size's layout: the screen, rows to a list, where the hint goes,
    128: {"W": 128, "ROWS": 6, "FOOT": 112, "CHARS": 21, "HOME": (23, 52, 81), "WAVE": (32, 96), "FIELD": 15},
    120: {"W": 120, "ROWS": 5, "FOOT": 104, "CHARS": 19, "HOME": (23, 50, 77), "WAVE": (32, 88), "FIELD": 14},
}                                               # characters a line, HOME's rows, the editor's waveform and field strip
W = H = 128
ROWS, FOOT, CHARS, HOME_ROWS, FIELD_STEP = 6, 112, 21, (23, 52, 81), 15
SCREENS = ("status", "settings", "scan", "pick", "confirm", "job", "player", "matrix", "route", "presets",
           "chanmap", "meter", "editor")        # drawn here (the meters: pocketmeters); any other: the OLED's
                                                # picture in the theme's colours (band)
WAVE_TOP, WAVE_BOTTOM = 32, 96                  # the sample editor's waveform (its times under it)


def use_size(size):
    """draw at size (128 or 120) from now on: every screen here and in pocketmeters reads these"""
    global W, H, ROWS, FOOT, CHARS, HOME_ROWS, FIELD_STEP, WAVE_TOP, WAVE_BOTTOM
    g = GEOMETRY.get(size, GEOMETRY[128])
    W = H = g["W"]
    ROWS, FOOT, CHARS, HOME_ROWS, FIELD_STEP = g["ROWS"], g["FOOT"], g["CHARS"], g["HOME"], g["FIELD"]
    WAVE_TOP, WAVE_BOTTOM = g["WAVE"]


def small():
    return st.font(size=12)


def text(d, xy, s, colour, big=False):
    d.text(xy, st.plain(s), font=st.font() if big else small(), fill=colour)


def width(s, big=False):
    return len(st.plain(s)) * (8 if big else 6)


def cut(s, chars):
    s = st.plain(s)
    return s if len(s) <= chars else s[:max(1, chars - 1)] + "~"


def wrap(s, chars=18, most=3):
    lines, line = [], ""
    for word in s.split():
        trial = (line + " " + word).strip()
        if len(trial) <= chars or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    return (lines + [line])[:most]


def battery(d, x, y, b, t):
    """the PiSugar's charge: a battery 11 x 7 (a bolt in it while plugged in), its fill the track green, or the REC
    red at 15% and below"""
    low = b["percent"] <= 15 and not b["plugged"]
    d.rectangle((x, y, x + 9, y + 6), outline=t.c[3])
    d.rectangle((x + 10, y + 2, x + 10, y + 4), fill=t.c[3])
    if b["plugged"]:
        d.polygon([(x + 5, y + 1), (x + 2, y + 4), (x + 5, y + 4), (x + 4, y + 6), (x + 8, y + 2), (x + 5, y + 2)],
                  fill=t.track[2])
    elif b["percent"]:
        d.rectangle((x + 2, y + 2, x + 2 + round(5 * b["percent"] / 100), y + 4), fill=REC if low else t.track[1])


def header(img, d, t, title, home=None, sub="", right=""):
    """the title in 16 px bold (small when it's too long; then sub, small), right (a count, small) at the right or,
    on HOME, LIVE (a green tag) / idle / the REC clock and the battery; a rule"""
    room = W - 6 - width(right)
    if width(title, big=True) <= room:
        text(d, (2, 1), title, t.hi, big=True)
    else:
        text(d, (2, 3), cut(title, room // 6), t.hi)
    if sub:
        text(d, (4 + width(title, big=True), 3), sub, t.c[3])
    if right:
        text(d, (W - 2 - width(right), 3), right, t.c[2])
    if home:
        right = W - 2
        b = home["battery"]
        if b and not home["rec"]:                 # (the REC clock is wider: no room for both)
            pct = f"{b['percent']}"
            right -= width(pct)
            text(d, (right, 3), pct, t.c[3])
            right -= 14
            battery(d, right, 5, b, t)
            right -= 4
        tag = home["rec"] or ("LIVE" if home["live"] else "idle")
        w = width(tag)
        if home["rec"]:
            d.rounded_rectangle((right - w - 4, 2, right, 15), 3, fill=REC)
            text(d, (right - w - 2, 3), tag, t.bg)
        elif home["live"]:
            d.rounded_rectangle((right - w - 4, 2, right, 15), 3, fill=t.track[1])
            text(d, (right - w - 2, 3), tag, t.bg)
        else:
            text(d, (right - w - 2, 3), tag, t.c[2])
    d.line((0, 18, W, 18), fill=t.c[0], width=2)


def footer(d, t, hint):
    """the hint under the rule: its parts (the OLED's hints space them apart) at the left and the right, "x = y"
    as "x=y" where a line's characters aren't enough"""
    d.line((0, FOOT, W, FOOT), fill=t.c[0], width=1)
    parts = [p.strip() for p in re.split(r"\s{2,}", st.plain(hint)) if p.strip()]
    if sum(map(len, parts)) + 2 * (len(parts) - 1) > CHARS:
        parts = [p.replace(" = ", "=") for p in parts]
    if len(parts) == 2 and len(parts[0]) + len(parts[1]) + 1 <= CHARS:
        text(d, (2, FOOT + 3), parts[0], t.c[2])
        text(d, (W - 2 - width(parts[1]), FOOT + 3), parts[1], t.c[2])
    else:
        text(d, (2, FOOT + 3), cut(" ".join(parts), CHARS), t.c[2])


def row(img, d, t, y, k, letter, name, value, fill, lit):
    """a source row as on the Studio's HOME: a letter tile in track colour k, the name, the value in its colour, a
    bar (fill: 0..1 of it bright; lit: all of it bright)"""
    d.rectangle((2, y, 21, y + 25), fill=t.dim[k])
    text(d, (8, y + 5), letter, t.track[k], big=True)
    text(d, (26, y + 1), cut(name, CHARS - 4), t.hi)
    text(d, (26, y + 13), cut(value, CHARS - 4), t.track[k] if lit or fill else t.mid[k])
    d.rectangle((26, y + 24, W - 3, y + 25), fill=t.dim[k])
    end = 26 + round((W - 29) * (1 if lit else fill))
    if end > 26:
        d.rectangle((26, y + 24, end, y + 25), fill=t.track[k])


def draw_home(home, t, img=None):
    """HOME from App.home(): FM-1 A in (A, blue), the speaker out (>, orange: its bar the volume), MIDI (M, yellow:
    lit while it plays), then VOL and the clock or the way to settings"""
    img = img or Image.new("RGB", (W, H), t.bg)
    d = ImageDraw.Draw(img)
    header(img, d, t, "FM-1", home, sub="> BT" if W == 128 else "")   # (no room for it beside LIVE at 120)
    vol = home["volume"]
    a, out, midi = HOME_ROWS
    row(img, d, t, a, 0, "A", "FM-1 A" + (" + B" if home["b"] else ""), home["fm1"], 0, home["live"])
    row(img, d, t, out, 3, ">", "SPEAKER", home["out"], (vol or 0) / 100 if home["sink"] else 0, False)
    row(img, d, t, midi, 2, "M", "MIDI", home["midi"], 0, home["traffic"])
    d.line((0, FOOT, W, FOOT), fill=t.c[0], width=1)
    text(d, (2, FOOT + 3), f"VOL {vol}%" if vol is not None else "VOL --", t.c[3])
    hint = cut(home["hint"], CHARS - 10 if W == 128 else CHARS - 8)   # (beside VOL: 11 characters either way)
    text(d, (W - 2 - width(hint), FOOT + 3), hint, t.c[2])
    return img


def draw_list(img, d, t, title, rows, cursor, hint, editing=False):
    """a list of (label, value) rows, ROWS to a page, scrolling with the cursor: its row lit (the theme's second
    shade, a blue edge); a value being changed marked with +-, in yellow"""
    header(img, d, t, title, right=f"{cursor + 1}/{len(rows)}" if rows else "")
    top = min(max(0, cursor - 2), max(0, len(rows) - ROWS))
    for i, (label, value) in enumerate(rows[top:top + ROWS]):
        y, selected = TOP + i * ROW_H, top + i == cursor
        if selected:
            d.rectangle((0, y - 1, W - 1, y + 12), fill=t.c[1])
            d.rectangle((0, y - 1, 1, y + 12), fill=t.track[0])
        value = st.plain(value or "")
        if selected and editing and value:
            value = "+-" + value
        value = cut(value, CHARS - 2 - min(len(st.plain(label)), CHARS - 8))   # (a long name keeps 13 or 11)
        text(d, (5, y), cut(label, (W - 10 - width(value)) // 6), t.hi if selected else t.c[3])
        text(d, (W - 3 - width(value), y), value,
             t.track[2] if selected and editing else t.hi if selected else t.c[4])
    if len(rows) > ROWS:                          # where the page is in the list
        span = FOOT - TOP - 4
        y0 = TOP - 1 + span * top // len(rows)
        d.line((W - 1, y0, W - 1, y0 + max(4, span * ROWS // len(rows))), fill=t.c[2])
    footer(d, t, hint)


def draw_lines(d, t, lines, y=TOP + 2, colour=None):
    for i, line in enumerate(lines):
        text(d, (2, y + i * 13), cut(line, CHARS), colour or t.hi)


def progress(d, t, y, part, colour):
    d.rectangle((2, y, W - 3, y + 9), outline=t.c[2])
    if part:
        d.rectangle((4, y + 2, 4 + round((W - 9) * min(1.0, part)), y + 7), fill=colour)


def draw_box(img, t, lines, bar=None):
    """a box over the screen (a message, or the volume with its bar 0..1), in the theme's colours"""
    d = ImageDraw.Draw(img)
    h = 10 + 13 * len(lines) + (16 if bar is not None else 0)
    top = (H - h) // 2
    d.rectangle((4, top, W - 5, top + h), fill=t.bg, outline=t.c[3], width=2)
    for i, line in enumerate(lines):
        line = cut(line, CHARS - 3)
        text(d, ((W - width(line)) // 2, top + 5 + 13 * i), line, t.hi)
    if bar is not None:
        y = top + h - 15
        d.rectangle((12, y, W - 13, y + 8), outline=t.c[2])
        if bar:
            d.rectangle((14, y + 2, 14 + round((W - 29) * bar), y + 6), fill=t.track[3])
    return img


def draw_splash(t, size=128):
    """the LCD at start-up, as soon as it's open (the rest takes a while on a Zero W)"""
    use_size(size)
    up = (128 - H) // 2                           # (the 120 one a little higher)
    img = Image.new("RGB", (W, H), t.bg)
    d = ImageDraw.Draw(img)
    st.text(img, (W // 2 - 32, 34 - up), "FM-1", t.hi, size=2)
    text(d, ((W - width("Companion")) // 2, 70 - up), "Companion", t.c[4])
    d.line((24, 88 - up, W - 24, 88 - up), fill=t.c[1])
    text(d, ((W - width("Starting...")) // 2, 94 - up), "Starting...", t.c[2])
    return img


def band(mono, t):
    """a screen not drawn here yet: the OLED's 128x64 picture in the middle, its lit pixels in the theme's
    brightest shade on its background"""
    img = Image.new("RGB", (W, H), t.bg)
    img.paste(Image.new("RGB", mono.size, t.c[4]), (0, (H - mono.height) // 2), mono.convert("1"))
    return img


class PocketScreens:
    """the app's screens on the LCD (needs the app's state and the OLED screens' methods)"""

    def pocket_theme(self, now):
        """the LCD's colours: FM-1 A's (library.read_theme saves them when the FM-1 is found), or a palette fixed
        in the settings ("desk_theme", as on the Studio); looked at every 2 s"""
        if now >= getattr(self, "theme_check", 0.0):
            self.theme_check = now + 2
            pick = self.theme_pick()
            try:
                key = pick if pick != "follow" else library.THEME.read_text()
            except OSError:
                key = None
            if key != getattr(self, "theme_seen", 0):
                self.theme_seen = key
                try:
                    self.theme = (st.Theme(pick) if pick != "follow" else
                                  st.theme_load(json.loads(key)) if key else st.Theme("XOXO"))
                except (ValueError, TypeError):
                    self.theme = st.Theme("XOXO")
        return self.theme

    def theme_pick(self):
        """the theme in the settings: "follow" (FM-1 A's) or one of st.POCKET; one of SLOOP's five, which the
        list had before the XOXO look, is XOXO now (they're still shown by following FM-1 A)"""
        pick = self.state.get("desk_theme", "follow")
        return pick if pick == "follow" or pick in st.POCKET else "XOXO"

    def colour_frame(self, now):
        """this screen in colour, with the volume (HOME), busy and message boxes over it"""
        use_size(getattr(self.display, "size", 128))
        t = self.pocket_theme(now)
        if self.screen == "pick" and self.pick.get("theme"):    # choosing a theme: the one under the cursor
            t = self.theme_named(self.pick["items"][self.pick["cursor"]][2])
        img = Image.new("RGB", (W, H), t.bg)
        d = ImageDraw.Draw(img)
        self.frame_now = now                     # (the meters move with the clock)
        getattr(self, "colour_" + self.screen)(img, d, t)
        if self.screen == "status" and now < self.volume_shown and self.volume is not None:
            draw_box(img, t, [f"Volume {self.volume}%"], self.volume / 100)
        if self.busy:
            draw_box(img, t, wrap(self.busy + "." * (int(now * 2) % 4)))
        elif self.message and now < self.message_until:
            draw_box(img, t, wrap(self.message))
        return img

    def colour_status(self, img, d, t):
        draw_home(self.home(), t, img)

    def colour_settings(self, img, d, t):
        rows = [(name, value) for _, name, value in self.settings_rows()]
        draw_list(img, d, t, self.settings_title(), rows, self.setting, self.settings_hint(), bool(self.editing))

    def colour_scan(self, img, d, t):
        midi, rows = self.scan_kind == "midi", self.scan_rows()
        title = "BT MIDI keys" if midi else "BT audio out"
        if rows:
            draw_list(img, d, t, title, [(r["name"], r.get("tag") or "") for r in rows], self.cursor,
                      self.scan_hint(rows))
            return
        header(img, d, t, title)
        if self.scan_running():
            text(d, (2, TOP + 2), "Searching...", t.hi)
            draw_lines(d, t, ["Turn the keyboard on", "(its Bluetooth on)"] if midi else
                       ["Put headphones in", "pairing mode now"], TOP + 22, t.c[3])
            footer(d, t, "< back")
        else:
            text(d, (2, TOP + 2), "None found", t.hi)
            footer(d, t, "K1 scan again   < back")

    def colour_pick(self, img, d, t):
        p = self.pick
        if p.get("theme"):
            self.colour_themes(img, d, t)
            return
        draw_list(img, d, t, p["title"], [i[:2] for i in p["items"]], p["cursor"], "press = choose  < back")

    # ---- Settings > Theme (on the LCD only: the OLED has one colour)

    def theme_named(self, name):
        """a theme by its name in Settings, "follow" being FM-1 A's (as library.read_theme last saved it)"""
        if name != "follow":
            return st.Theme(name)
        try:
            return st.theme_load(json.loads(library.THEME.read_text()))
        except (OSError, ValueError, TypeError):
            return st.Theme("XOXO")

    def theme_label(self):
        pick = self.theme_pick()
        return "FM-1 A" if pick == "follow" else pick

    def open_theme_pick(self):
        """FOLLOW FM-1 A, then XOXO and the Studio's eight, each with a swatch; the screen shows the one
        under the cursor; press uses it"""
        items = [("FM-1 A", "", "follow")] + [(name, "", name) for name in st.POCKET]
        self.open_pick("Theme", items, self.pick_theme, "", back="settings")
        pick = self.theme_pick()
        self.pick.update(theme=True, cursor=next((i for i, item in enumerate(items) if item[2] == pick), 0))

    def pick_theme(self, name):
        self.state["desk_theme"] = name
        self.save_settings()
        self.theme_check = 0.0                   # (pocket_theme looks again now)
        self.screen, self.pick = "settings", None
        self.say("Theme: " + self.theme_label(), 1.5)

    def colour_themes(self, img, d, t):
        p = self.pick
        pick = self.theme_pick()
        draw_list(img, d, t, "Theme", [(label + (" *" if name == pick else ""), "") for label, _, name in p["items"]],
                  p["cursor"], "press = use  < back")
        top = min(max(0, p["cursor"] - 2), max(0, len(p["items"]) - ROWS))
        for i, (_, _, name) in enumerate(p["items"][top:top + ROWS]):
            y, theme = TOP + i * ROW_H, self.theme_named(name)
            d.rectangle((W - 47, y, W - 4, y + 11), fill=theme.bg, outline=theme.c[2])
            for k in range(4):                   # its four track colours
                d.rectangle((W - 44 + k * 10, y + 3, W - 37 + k * 10, y + 8), fill=theme.track[k])

    def colour_confirm(self, img, d, t):
        c = self.confirm
        header(img, d, t, c["title"])
        lines = [w for line in c["lines"] for w in wrap(line, CHARS, 2)][:6]
        draw_lines(d, t, lines)
        d.rectangle((0, FOOT, W - 1, H - 1), fill=REC)
        text(d, (2, FOOT + 3), "HOLD press 2s", t.hi)
        text(d, (W - 2 - width("< back"), FOOT + 3), "< back", t.hi)

    def colour_job(self, img, d, t):
        s = self.library_state() or {}
        header(img, d, t, self.job_title)
        state = s.get("state")
        if state == "running" or state is None:
            percent = s.get("percent")
            draw_lines(d, t, wrap(s.get("step") or "Starting", CHARS, 2))
            if percent is not None:
                label = f"{int(percent)}%"
                text(d, ((W - width(label, big=True)) // 2, TOP + 32), label, t.c[4], big=True)
                progress(d, t, TOP + 54, percent / 100, t.track[1])
            if s.get("job") == "flash":
                footer(d, t, "Don't unplug the FM-1")
                d.line((0, FOOT, W, FOOT), fill=REC, width=2)
        else:
            done = state == "done"
            text(d, (2, TOP + 2), "Done" if done else "Failed", t.track[1] if done else REC, big=True)
            draw_lines(d, t, wrap(s.get("message") or "", CHARS, (FOOT - TOP - 24) // 13), TOP + 24, t.c[4])
            footer(d, t, "press = OK")

    def colour_player(self, img, d, t):
        from libui import short_date
        from meters import clock
        header(img, d, t, "Playing")
        draw_lines(d, t, wrap(short_date(self.player_name or ""), CHARS, 2))
        now, length = self.player.seconds(), self.player.length
        label = f"{clock(now)} / {clock(length)}"
        text(d, ((W - width(label, big=True)) // 2, TOP + 34), label, t.c[4], big=True)
        progress(d, t, TOP + 58, now / length if length else 0, t.track[0])
        footer(d, t, "press = stop")

    def colour_matrix(self, img, d, t):
        """the routes: sources down, destinations across; a route on: a green cell; the cursor: a white frame"""
        from midiui import SHORT_DESTS, SHORT_NAMES, SOURCE_NAMES
        sources, dests = self.matrix_lists()
        self.mx = [min(self.mx[0], len(sources) - 1), min(self.mx[1], len(dests) - 1)]
        header(img, d, t, "Routes")
        left = 50
        pitch = (W - left - 2) // max(1, len(dests))
        for col, dest in enumerate(dests):
            label = cut(SHORT_DESTS.get(dest, dest), pitch // 6)
            text(d, (left + col * pitch + (pitch - width(label)) // 2, TOP), label, t.c[3])
        routes = self.routes()
        step = min(16, (FOOT - TOP - 18) // max(1, len(sources)))
        for r, source in enumerate(sources):
            y = TOP + 16 + r * step
            name = SOURCE_NAMES.get(source, source) if len(st.plain(SOURCE_NAMES.get(source, source))) <= 8 else \
                SHORT_NAMES.get(source, source)
            text(d, (2, y), cut(name, 8), t.hi if r == self.mx[0] else t.c[3])
            for col, dest in enumerate(dests):
                x0, x1 = left + col * pitch + 3, left + (col + 1) * pitch - 3
                if source == dest:
                    d.line((x0 + 3, y + 6, x1 - 3, y + 6), fill=t.c[1])
                elif routes[f"{source}>{dest}"]["on"]:
                    d.rectangle((x0, y + 2, x1, y + 10), fill=t.track[1])
                else:
                    d.rectangle((x0, y + 2, x1, y + 10), outline=t.c[1])
                if [r, col] == self.mx:
                    d.rectangle((x0 - 2, y, x1 + 2, y + 12), outline=t.hi)
        footer(d, t, "press = options  < back")

    def colour_route(self, img, d, t):
        rows = [(label, value) for _, label, value in self.route_rows()]
        hint = "up/down = value  < done" if self.route_edit else "press = change  < back"
        draw_list(img, d, t, self.route_title(), rows, self.route_row, hint, bool(self.route_edit))

    def colour_presets(self, img, d, t):
        from midiui import PRESETS
        if self.preset_menu is not None:
            draw_list(img, d, t, f"Preset {PRESETS[self.preset_row]}", [(a, "") for a in self.preset_actions()],
                      self.preset_menu, "press = do it  < back")
            return
        presets, rows = self.presets(), []
        for slot in PRESETS:
            saved = presets.get(slot)
            when = time.strftime("%m-%d %H:%M", time.localtime(saved["saved"])) if saved else "empty"
            rows.append(((saved or {}).get("name") or f"Preset {slot}", when))
        draw_list(img, d, t, "Presets", rows, self.preset_row, "press = load/save")

    def colour_chanmap(self, img, d, t):
        table = self.route()["channels"]
        rows = [(f"Ch {i + 1}  >", "off" if out is None else str(out + 1)) for i, out in enumerate(table)]
        hint = "up/down = value  < done" if self.chan_edit else "press = change  < back"
        draw_list(img, d, t, "Channels", rows, self.chan_row, hint, self.chan_edit)

    def colour_editor(self, img, d, t):
        """the sample editor: the field being changed, which of the eight it is, the take's waveform (the selection
        bright, the rest faint, the fades as ramps), the markers (the one moving yellow, flagged), the field's value
        between the selection's times (on Save: the name it'll be saved as)"""
        import library as lib
        from sampleui import FIELDS
        ed = self.ed
        if ed["loading"] or ed["error"]:
            header(img, d, t, "Sample editor")
            lines = ["Loading the take..."] if ed["loading"] else ["Can't open it:"] + wrap(ed["error"], CHARS, 4)
            draw_lines(d, t, lines)
            footer(d, t, "< back")
            return
        field, label = FIELDS[ed["field"]]
        length = ed["end"] - ed["start"]
        tag = f"{length:.1f}s"
        long = length > lib.SLOT_SECONDS          # longer than a SLOOP slot holds: the tag in red
        value = self.editor_value(field)
        header(img, d, t, label)
        w = width(tag)
        if long:
            d.rounded_rectangle((W - 6 - w, 2, W - 2, 15), 3, fill=REC)
            text(d, (W - 4 - w, 3), tag, t.bg)
        else:
            text(d, (W - 2 - w, 3), tag, t.c[2])
        for k in range(len(FIELDS)):              # where this field is among the eight
            x = 4 + k * FIELD_STEP
            d.rectangle((x, 23, x + 11, 26), fill=t.track[2] if k == ed["field"] else t.c[1])
        mid, half = (WAVE_TOP + WAVE_BOTTOM) // 2, (WAVE_BOTTOM - WAVE_TOP) // 2 - 4
        sx = round(ed["start"] / ed["seconds"] * (W - 1))
        ex = round(ed["end"] / ed["seconds"] * (W - 1))
        wave = ed["wave"]                         # (128 columns: on the 120 screen, 120 of them)
        for i in range(W):
            lo, hi = wave[i * len(wave) // W]
            inside = sx <= i <= ex
            d.line((i, mid - round(hi * half), i, mid - round(lo * half)), fill=t.track[0] if inside else t.c[1])
        per = (W - 1) / ed["seconds"]             # pixels a second
        if ed["fade_in"]:
            d.line((sx, mid + half, min(ex, sx + round(ed["fade_in"] * per)), mid - half), fill=t.track[2])
        if ed["fade_out"]:
            d.line((max(sx, ex - round(ed["fade_out"] * per)), mid - half, ex, mid + half), fill=t.track[2])
        for x, active in ((sx, field == "start"), (ex, field == "end")):
            d.line((x, WAVE_TOP - 2, x, WAVE_BOTTOM + 2), fill=t.track[2] if active else t.hi)
            if active:
                d.polygon([(x - 4, WAVE_TOP - 2), (x + 4, WAVE_TOP - 2), (x, WAVE_TOP + 3)], fill=t.track[2])
        if field == "save":                       # the name it'll be saved as
            text(d, (2, WAVE_BOTTOM + 3), cut(value, CHARS), t.hi)
            footer(d, t, "press = save  < back")
        else:
            text(d, (2, WAVE_BOTTOM + 3), f"{ed['start']:.2f}", t.c[2])
            end = f"{ed['end']:.2f}"
            text(d, (W - 2 - width(end), WAVE_BOTTOM + 3), end, t.c[2])
            value = cut(value, CHARS - 10)        # the field's value between the times
            text(d, ((W - width(value)) // 2, WAVE_BOTTOM + 3), value, t.track[2])
            footer(d, t, ("playing" if self.player.playing() else "press = play") + "  <> field")

    def colour_saver(self, now):
        """after OFF_AFTER without a key: FM-1 LIVE (or idle), small, moving every 20 s, on black"""
        use_size(getattr(self.display, "size", 128))
        img = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(img)
        line = "FM-1 " + ("LIVE" if self.live() else "idle")
        if self.midi and self.midi.peer:
            line += " +MIDI"
        if self.recorder.recording():
            line += " REC"
        w = width(line)
        step = int(now // 20)
        text(d, ((step * 37) % (W - w), (step * 23) % (H - 12)), line, self.pocket_theme(now).c[3])
        return img
