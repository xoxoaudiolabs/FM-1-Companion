"""The Studio's FM-1 ON STUDIO section (MORE > FM-1 ON STUDIO): SLOOP and X0X running on the Studio (PLAY SLOOP,
PLAY X0X: deskui.start_app), and FM-1 CONTROLS: a picture of the FM-1 (its knobs, buttons and 27 keys) to map a MIDI
controller onto, for playing the apps with it as FM-1 A plays them (fm1map.py, run in the MIDI process): tap a
control on the picture, then move yours. A mapped control is lit; tapped, the screen says what it's on (CLEAR takes
it off). Mixed into deskui.DeskUI."""
import json

import fm1map
import sloopstyle as st

W, H, HDR_H = 480, 320, 34
# the picture, laid out as the FM-1 is: MASTER and SELECT, PRESETS and ALGORITHM on the left with OCT- / OCT+ under
# them, the screen, KNOB 1-4 on the right over the buttons (two rows of six), the keys along the bottom
KNOB_AT = {"master": (40, 56), "knob:0": (100, 56), "knob:2": (40, 104), "knob:1": (100, 104),
           "knob:3": (282, 56), "knob:4": (330, 56), "knob:5": (378, 56), "knob:6": (426, 56)}
KNOB_LABEL = {"master": "MASTER", "knob:0": "SELECT", "knob:2": "PRESET", "knob:1": "ALGO",
              "knob:3": "KNOB1", "knob:4": "KNOB2", "knob:5": "KNOB3", "knob:6": "KNOB4"}
SCREEN = (132, 42, 250, 158)
KEYS_X, WHITE_W = 8, 29


def button_box(k):
    """the FM-1's button k (fm1map.BUTTONS order) on the picture"""
    if k >= 12:                                   # OCT- / OCT+, under the left knobs
        x = 12 + (k - 12) * 60
        return (x, 138, x + 52, 158)
    x, y = 258 + (k % 6) * 36, 90 + (k // 6) * 26
    return (x, y, x + 33, y + 22)


def key_box(k):
    """key k (0 = F, chromatic): the sharps a row of their own over the others, as on the FM-1"""
    whites = sum(1 for j in range(k) if not fm1map.black(j))
    if fm1map.black(k):
        x = KEYS_X + whites * WHITE_W
        return (x - 10, 166, x + 10, 222)
    x = KEYS_X + whites * WHITE_W
    return (x + 1, 228, x + WHITE_W - 2, 312)


class DeskFM1:
    def fm1_init(self):
        self.fm1_pick = None                      # the control tapped on the picture
        self.fm1_said = 0                         # the map's count last said (fm1map.Mapper.count)

    def fm1_status(self):
        return getattr(self.app.midi, "fm1map", None) or {}

    def fm1_send(self, *args):
        if hasattr(self.app.midi, "fm1map_command"):
            self.app.midi.fm1map_command(*args)

    def fm1_view(self):
        return (json.dumps(self.fm1_status(), sort_keys=True), self.fm1_pick, tuple(sorted(self.app_procs)))

    # ---- the section: the apps, the controls

    def draw_fm1(self, img, d, now):
        import deskui
        t = self.theme
        self.button(img, d, (4, 4, 84, HDR_H - 4), "< MORE", lambda: self.open_tab("MORE"), key="fm1-back")
        st.text(img, (96, 9), "FM-1 ON STUDIO", t.hi)
        d.line((0, HDR_H - 1, W, HDR_H - 1), fill=t.c[0], width=2)
        mapped = len(self.fm1_status().get("map") or {})
        tiles = [(f"PLAY {name}", ("studio_app", key), "ON" if key in self.app_procs else
                  "OFF" if program.exists() else "NOT INSTALLED") for key, (name, program) in deskui.APPS.items()]
        tiles.append(("FM-1 CONTROLS", ("fm1map", None), f"{mapped} MAPPED" if mapped else "MAP A CONTROLLER"))
        top, bottom = HDR_H + 8, H - 44 - 30
        th = (bottom - top) // len(tiles)
        for i, (label, what, value) in enumerate(tiles):
            box = (8, top + i * th + 3, W - 8, top + (i + 1) * th - 3)
            hot = self.lit(("more", label))
            d.rectangle(box, fill=t.hi if hot else t.grey[0])
            st.text(img, (box[0] + 14, (box[1] + box[3]) // 2 - 8), label, t.bg if hot else t.c[4], 1)
            st.text(img, (box[2] - 14 - st.text_size(value)[0], (box[1] + box[3]) // 2 - 8), value,
                    t.bg if hot else t.hi if value == "ON" else t.c[3])
            self.widget(box, "tap", lambda what=what: self.open_fm1(what), ("more", label))
        self.centre(img, (0, bottom, W, bottom + 28), "PLAYED FROM FM-1 A (REMOTE: OUT 16) OR A MAPPED CONTROLLER",
                    t.c[2])

    def open_fm1(self, what):
        import deskui
        kind, key = what
        if kind == "fm1map":
            self.fm1_pick = None
            self.open_tab("FM1MAP")
        elif not deskui.APPS[key][1].exists():
            self.app.say(f"{deskui.APPS[key][0]} isn't built: see its README", 3)
        else:
            self.start_app(key)

    # ---- FM-1 CONTROLS: the picture

    def draw_fm1map(self, img, d, now):
        t = self.theme
        s = self.fm1_status()
        mapped, learning = s.get("map") or {}, s.get("learning")
        if s.get("count", 0) != self.fm1_said:          # one just learnt: said
            if self.fm1_said and s.get("heard"):
                self.app.say(s["heard"], 3)
            self.fm1_said = s.get("count", 0)
        self.button(img, d, (4, 4, 84, HDR_H - 4), "< BACK", self.fm1map_back, key="fm1map-back")
        st.text(img, (94, 9), "TAP A CONTROL, MOVE YOURS", t.hi)
        d.rectangle((W - 140, 6, W - 4, HDR_H - 6), outline=(255, 112, 92), width=2)
        self.centre(img, (W - 140, 6, W - 4, HDR_H - 6), "HOLD: CLEAR ALL", (255, 112, 92))
        self.widget((W - 140, 0, W - 4, HDR_H + 4), "hold", self.fm1map_forget, "fm1map-forget")
        d.rectangle((2, 38, W - 3, H - 3), fill=t.grey[0])              # the FM-1's body

        def look(control):
            """(fill, text) for a control: being learnt, mapped, or not"""
            if control == learning:
                return t.hi, t.bg
            if control == self.fm1_pick:
                return t.track[3], t.bg
            if control in mapped:
                return t.track[1], t.bg
            return t.grey[1], t.c[3]
        for control, (x, y) in KNOB_AT.items():
            fill, _ = look(control)
            d.ellipse((x - 12, y - 12, x + 12, y + 12), fill=fill, outline=t.c[1])
            d.line((x, y - 12, x, y - 5), fill=t.bg, width=2)
            label = KNOB_LABEL[control]
            st.text(img, (x - st.text_size(label)[0] // 2, y + 13), label, t.c[3])
            self.widget((x - 26, y - 16, x + 26, y + 30), "tap", lambda c=control: self.fm1_tap(c), ("fm1", control))
        for k, label in enumerate(fm1map.BUTTONS):
            control, box = f"btn:{k}", button_box(k)
            fill, ink = look(control)
            d.rectangle(box, fill=fill)
            self.centre(img, box, label if k != 10 else "PLAY", ink)
            self.widget(box, "tap", lambda c=control: self.fm1_tap(c), ("fm1", control))
        for k in [k for k in range(fm1map.KEYS) if not fm1map.black(k)] + \
                 [k for k in range(fm1map.KEYS) if fm1map.black(k)]:
            control, box = f"key:{k}", key_box(k)
            fill, _ = look(control)
            d.rectangle(box, fill=fill, outline=t.c[1])
            self.widget(box, "tap", lambda c=control: self.fm1_tap(c), ("fm1", control))
        self.draw_fm1_screen(img, d, s, mapped, learning)

    def draw_fm1_screen(self, img, d, s, mapped, learning):
        """the FM-1's screen on the picture: what to do, or the tapped control and what it's on"""
        t = self.theme
        d.rectangle(SCREEN, fill=t.bg, outline=t.c[1])
        x0, x1, y = SCREEN[0] + 4, SCREEN[2] - 4, SCREEN[1] + 6
        room = (x1 - x0) // 8

        def line(text, colour):
            nonlocal y
            for part in wrap(text, room):
                if y + 16 > SCREEN[3] - 22:
                    return
                st.text(img, (x0, y), part, colour)
                y += 16
        pick = self.fm1_pick
        if not pick:
            line("TAP A KNOB, KEY OR BUTTON", t.c[4])
            line(f"{len(mapped)} MAPPED", t.c[2])
            return
        line(fm1map.name(pick), t.hi)
        if learning == pick:
            line("NOW MOVE YOURS", t.c[4])
        elif pick in mapped:
            line(mapped[pick], t.c[3])
            box = (SCREEN[0] + 4, SCREEN[3] - 22, SCREEN[2] - 4, SCREEN[3] - 4)
            self.button(img, d, box, "CLEAR", lambda c=pick: self.fm1_clear(c), key="fm1map-clear")
        else:
            line("NOT MAPPED: TAP IT AGAIN", t.c[3])

    def fm1_tap(self, control):
        """a control on the picture: learnt (tapped while it's being learnt: not)"""
        learning = self.fm1_status().get("learning")
        if learning == control:
            self.fm1_send("learn", None)
            return
        if self.fm1_pick == control or control not in (self.fm1_status().get("map") or {}):
            self.fm1_send("learn", control)
        else:
            self.fm1_send("learn", None)          # a mapped one: what it's on first (tap again: learn it anew)
        self.fm1_pick = control

    def fm1_clear(self, control):
        self.fm1_send("clear", control)

    def fm1map_forget(self):
        self.fm1_send("forget")
        self.fm1_pick = None
        self.app.say("FM-1 controls forgotten", 2)

    def fm1map_back(self):
        self.fm1_send("learn", None)
        self.fm1_pick = None
        self.open_tab("FM1")


def wrap(text, room):
    """text in lines of room characters, broken at spaces"""
    out, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > room:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
        while len(cur) > room:
            out.append(cur[:room])
            cur = cur[room:]
    return out + ([cur] if cur else [])
