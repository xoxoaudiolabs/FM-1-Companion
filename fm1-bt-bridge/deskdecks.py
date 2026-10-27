"""The Studio's DECKS screen: two DJ decks (decks.py, run as a program of its own: DeckProcess) by touch, and what
the Hercules DJControl Inpulse 200 MK2 plays on them shown. Mixed into deskui.DeskUI; opened from MORE > DJ DECKS.

Each deck: its track (title, artist), its BPM as it plays, its key (and Camelot), the time left, the tempo, SYNC /
LOOP; its overview (the whole track, where it's at, a loop, its hot cues: a line in the cue's colour with its pad's
number, tap the number to go there, hold it to delete the cue; drag along it to go there; tap it for it full
screen, tap again to come back); CUE (held), PLAY, SYNC, PFL. Between them, the crossfader. Underneath, the music: the Studio DJ Music folder, or a USB drive (plugged
in: shown; the button at the top goes between them): title, BPM, Camelot key, the one the browser knob is on lit
(tap a row for it); LOAD A, LOAD B; SCAN reads the new tracks (their BPM and key; a drive's are listed before).
 < HOME back to the Companion with the decks playing on; OFF (held) stops them."""

import sloopstyle as st

W, H, HDR_H = 480, 320, 34
DECK_W = 240
ROWS, ROW_H, LIST_TOP = 4, 20, 196
SCRUB = 8                                       # a finger moved this far along an overview: a drag, not a tap


def clock(seconds):
    s = max(0, int(round(seconds)))
    return f"{s // 60}:{s % 60:02}"


def fit(text, width):
    """text cut to fit width pixels (8 px a character)"""
    room = max(1, width // 8)
    return text if len(text) <= room else text[:room - 1] + "~"


class DeskDecks:
    def decks_init(self):
        self.decks_proc = None                  # decks.DeckProcess, once DJ DECKS has been opened
        self.decks_top = 0                      # the list's first row shown
        self.decks_full = None                  # the deck whose overview fills the screen
        self.decks_down = None                  # (deck, x where the finger came down, dragging)
        self.decks_noted = 0                    # the count of the decks' last note said (DeckProcess.note_n)

    def open_decks(self):
        """MORE > DJ DECKS: the decks started (once) and their screen shown"""
        import decks
        if self.decks_proc is None:
            self.decks_proc = decks.DeckProcess(on_change=self.decks_changed)
        self.decks_proc.start()
        self.tab = "DECKS"
        self.decks_full = None                  # (the deck screen, not a waveform left full screen last time)
        self.shown = None

    def decks_changed(self):
        if self.tab == "DECKS":                 # (another screen: nothing to redraw)
            self.app.post("decks")

    def decks_off(self):
        if self.decks_proc:
            self.decks_proc.stop()
        self.decks_full = None
        self.open_tab("MORE")

    def decks_view(self):
        p = self.decks_proc
        if not p:
            return ()
        s = p.status or {}
        rows = tuple((d.get("title"), d.get("bpm"), round(d.get("pos", 0) * 2) / 2, d.get("playing"),
                      d.get("synced"), d.get("loop"), d.get("pfl"), d.get("pitch"), tuple(d.get("cues") or ()),
                      d.get("loading"), d.get("error")) for d in s.get("decks", []))
        return (rows, round(s.get("xfade", 0.5), 2), s.get("cursor"), s.get("scanning"), p.library_n,
                s.get("source"), s.get("sources"), p.note_n,
                self.decks_top, p.running(), len(p.overviews[0]), len(p.overviews[1]), p.note, self.decks_full)

    def draw_decks(self, img, d, now):
        t, p = self.theme, self.decks_proc
        s = (p and p.status) or {}
        if self.decks_full is not None and p and p.running():
            self.draw_deck_full(img, d, self.decks_full, (s.get("decks") or [{}, {}])[self.decks_full],
                                p.overviews.get(self.decks_full) or [])
            return
        self.button(img, d, (4, 4, 84, HDR_H - 4), "< HOME", lambda: self.open_tab("HOME"), key="decks-home")
        source = s.get("source") or "STUDIO"
        label = f"USB: {source}" if s.get("usb") else "STUDIO MUSIC"
        self.button(img, d, (90, 4, 294, HDR_H - 4), fit(label, 176) + (" >" if (s.get("sources") or 1) > 1 else ""),
                    lambda: p and p.send("source"), on=bool(s.get("usb")), key="decks-source")
        if p and p.note and p.note_n != self.decks_noted:   # a USB drive in or out, no Hercules
            self.decks_noted = p.note_n
            self.app.say(p.note, 3)
        scanning = s.get("scanning")
        self.button(img, d, (300, 4, 386, HDR_H - 4), f"SCAN {scanning}" if scanning else "SCAN",
                    lambda: p and p.send("scan"), on=bool(scanning), key="decks-scan")
        d.rectangle((392, 6, 476, HDR_H - 6), outline=(255, 112, 92), width=2)
        self.centre(img, (392, 6, 476, HDR_H - 6), "HOLD OFF", (255, 112, 92))
        self.widget((392, 0, 476, HDR_H + 4), "hold", self.decks_off, "decks-off")
        d.line((0, HDR_H - 1, W, HDR_H - 1), fill=t.c[0], width=2)
        if not p or not p.running():
            self.centre(img, (0, HDR_H, W, H), "the decks aren't running: MORE > DJ DECKS", t.c[3])
            return
        decks = s.get("decks") or [{}, {}]
        for i, deck in enumerate(decks[:2]):
            self.draw_deck(img, d, i, deck, p.overviews.get(i) or [])
        x = int(s.get("xfade", 0.5) * (W - 40)) + 20         # the crossfader
        d.line((20, 190, W - 20, 190), fill=t.c[0], width=2)
        d.rectangle((x - 10, 186, x + 10, 194), fill=t.hi)
        self.draw_deck_list(img, d, s, p)

    def draw_deck(self, img, d, i, deck, overview):
        t, p = self.theme, self.decks_proc
        x0 = i * DECK_W
        colour = t.track[i]
        if i:
            d.line((x0, HDR_H, x0, 182), fill=t.c[0], width=2)
        st.text(img, (x0 + 6, HDR_H + 4), "AB"[i], colour)
        title = deck.get("title") or ("loading..." if deck.get("loading") else deck.get("error") or "-")
        st.text(img, (x0 + 22, HDR_H + 4), fit(title, DECK_W - 28), t.hi)
        st.text(img, (x0 + 22, HDR_H + 20), fit(deck.get("artist") or "", DECK_W - 28), t.c[2])
        bpm = deck.get("bpm")
        st.text(img, (x0 + 6, HDR_H + 38), f"{bpm:.1f}" if bpm else "---.-", colour, 2)
        st.text(img, (x0 + 94, HDR_H + 38), "BPM", t.c[2])
        key = " ".join(k for k in (deck.get("camelot"), deck.get("key")) if k)
        st.text(img, (x0 + 94, HDR_H + 54), key, t.c[3])
        pitch = deck.get("pitch") or 0.0
        st.text(img, (x0 + 170, HDR_H + 38), f"{pitch:+.1f}%", t.c[3])
        left = (deck.get("len") or 0) - (deck.get("pos") or 0)
        st.text(img, (x0 + 170, HDR_H + 54), f"-{clock(left)}", t.hi)
        badges = [n for n, on in (("SYNC", deck.get("synced")), ("LOOP", deck.get("loop"))) if on]
        st.text(img, (x0 + 6, HDR_H + 72), " ".join(badges), colour)
        # the overview: the whole track, where it's at, its cues and loop; drag along it to go there, tap it for
        # it full screen
        ox, oy, ow, oh = x0 + 6, HDR_H + 90, DECK_W - 12, 26
        self.draw_overview(img, d, i, deck, overview, (ox, oy, ow, oh), tags=True)
        self.widget((ox, oy - 4, ox + ow, oy + oh + 4), "drag",
                    lambda phase, x, y, i=i, ox=ox, ow=ow: self.overview_touch(i, phase, x, ox, ow),
                    ("deck-seek", i))
        # the buttons: CUE (held), PLAY, SYNC, PFL
        by, bw = HDR_H + 122, (DECK_W - 12) // 4
        keys = (("CUE", None), ("PLAY", deck.get("playing")), ("SYNC", deck.get("synced")), ("PFL", deck.get("pfl")))
        for k, (label, on) in enumerate(keys):
            box = (x0 + 6 + k * bw, by, x0 + 6 + (k + 1) * bw - 4, by + 24)
            if label == "CUE":
                d.rectangle(box, fill=t.grey[0])
                self.centre(img, box, "CUE", colour)
                self.widget(box, "gate", lambda down, i=i: p.send("cue", i, down), ("deck-cue", i))
            else:
                cmd = label.lower()
                self.button(img, d, box, label, lambda i=i, cmd=cmd: p.send(cmd, i), color=colour, on=bool(on),
                            key=("deck", label, i))

    def draw_overview(self, img, d, i, deck, overview, box, tags):
        """deck i's overview in box (x, y, width, height): the whole track, the part played in its colour, where it's
        at, its loop and hot cues; tags: each cue's pad number is tapped to go there, held to delete the cue"""
        t, p = self.theme, self.decks_proc
        colour = t.track[i]
        ox, oy, ow, oh = box
        d.rectangle((ox, oy, ox + ow, oy + oh), fill=t.grey[0])
        length = deck.get("len") or 0
        at = max(0.0, min(1.0, (deck.get("pos") or 0) / length)) if length else 0
        n = len(overview)
        for k, v in enumerate(overview):        # a column each, as wide as the box makes it
            h = max(1, int(v * (oh - 2) / 2))
            xa, xb = ox + int(k * ow / n), ox + int((k + 1) * ow / n) - 1
            d.rectangle((xa, oy + oh // 2 - h, max(xa, xb), oy + oh // 2 + h), fill=colour if k / n < at else t.c[2])
        loop = deck.get("loop_at")
        if loop:
            d.rectangle((ox + int(loop[0] * ow), oy, ox + int(loop[1] * ow), oy + 3), fill=t.hi)
        for cue in deck.get("cues") or []:     # hot cues: a line in the cue's colour, its pad's number on top
            k, at_c, colour_c = cue if isinstance(cue, (list, tuple)) else (None, cue, None)
            rgb = tuple(int(colour_c[j:j + 2], 16) for j in (1, 3, 5)) if colour_c else t.hi
            cx = ox + int(at_c * ow)
            d.line((cx, oy, cx, oy + oh), fill=rgb, width=2)
            if k is not None:
                d.rectangle((cx, oy, cx + 9, oy + 13), fill=rgb)        # (inside the overview: the badges
                st.text(img, (cx + 1, oy - 2), str(k + 1), (0, 0, 0))   # line above stays clear)
                if tags:
                    self.widget((cx - 4, oy - 4, cx + 14, oy + 16), "tap",       # its tag: tap to go there,
                                lambda i=i, k=k: p.send("gotocue", i, k), ("deck-cuetag", i, k),   # hold to delete
                                long=lambda i=i, k=k: p.send("clearcue", i, k))
        px = ox + int(at * ow)
        d.line((px, oy - 2, px, oy + oh + 2), fill=t.hi, width=2)

    def overview_touch(self, i, phase, x, ox, ow):
        """a finger on deck i's overview: moved along it, the deck goes where it is; lifted without moving, the
        overview full screen"""
        if phase == "down":
            self.decks_down = (i, x, False)
            return
        if not self.decks_down:
            return
        _i, x0, dragging = self.decks_down
        if phase == "move" and (dragging or abs(x - x0) >= SCRUB):
            self.decks_down = (i, x0, True)
            self.decks_proc.send("seek", i, max(0.0, min(1.0, (x - ox) / ow)))
        elif phase == "up":
            self.decks_down = None
            if not dragging:
                self.decks_full = i

    def draw_deck_full(self, img, d, i, deck, overview):
        """deck i's overview filling the screen, its title, BPM and time left above; a tap anywhere: back"""
        t = self.theme
        colour = t.track[i]
        st.text(img, (6, 9), "AB"[i], colour)
        title = deck.get("title") or ("loading..." if deck.get("loading") else deck.get("error") or "-")
        st.text(img, (22, 9), fit(title, 270), t.hi)
        bpm = deck.get("bpm")
        st.text(img, (300, 9), f"{bpm:.1f} BPM" if bpm else "---.- BPM", colour)
        left = (deck.get("len") or 0) - (deck.get("pos") or 0)
        st.text(img, (410, 9), f"-{clock(left)}", t.hi)
        d.line((0, HDR_H - 1, W, HDR_H - 1), fill=t.c[0], width=2)
        self.draw_overview(img, d, i, deck, overview, (6, HDR_H + 20, W - 12, H - HDR_H - 40), tags=False)
        self.widget((0, 0, W, H), "tap", self.decks_back, "decks-full")

    def decks_back(self):
        self.decks_full = None

    def draw_deck_list(self, img, d, s, p):
        t = self.theme
        lib, cursor = p.library, s.get("cursor") or 0
        if cursor < self.decks_top:             # the browser knob's row kept in view
            self.decks_top = cursor
        elif cursor >= self.decks_top + ROWS:
            self.decks_top = cursor - ROWS + 1
        if not lib:
            empty = f"no music on {s.get('source')}" if s.get("usb") else "Studio DJ Music is empty: add tracks, SCAN"
            self.centre(img, (0, LIST_TOP, W, LIST_TOP + ROWS * ROW_H), empty, t.c[3])
        for r in range(ROWS):
            k = self.decks_top + r
            if k >= len(lib):
                break
            _rel, title, artist, bpm, key, cam = lib[k]
            y = LIST_TOP + r * ROW_H
            if k == cursor:
                d.rectangle((0, y, W, y + ROW_H - 1), fill=t.grey[0])
            name = f"{artist} - {title}" if artist else title
            st.text(img, (6, y + 2), fit(name, 340), t.hi if k == cursor else t.c[3])
            st.text(img, (356, y + 2), f"{bpm:.0f}" if bpm else "--", t.c[3])
            st.text(img, (400, y + 2), cam or "", t.c[4])
            self.widget((0, y, W, y + ROW_H - 1), "tap", lambda k=k: p.send("select", k), ("deck-row", k))
        by = LIST_TOP + ROWS * ROW_H + 4
        self.button(img, d, (4, by, 60, H - 4), "UP", lambda: self.decks_page(-ROWS), key="decks-up")
        self.button(img, d, (64, by, 120, H - 4), "DOWN", lambda: self.decks_page(ROWS), key="decks-down")
        self.button(img, d, (128, by, 300, H - 4), "LOAD A", lambda: p.send("load", 0), color=t.track[0],
                    key="decks-load-a")
        self.button(img, d, (304, by, 476, H - 4), "LOAD B", lambda: p.send("load", 1), color=t.track[1],
                    key="decks-load-b")

    def decks_page(self, step):
        p = self.decks_proc
        if p and p.status:
            p.send("select", max(0, min(len(p.library) - 1, (p.status.get("cursor") or 0) + step)))
