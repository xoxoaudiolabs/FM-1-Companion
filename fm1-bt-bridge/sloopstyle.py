"""SLOOP's look, for the desk box's touchscreen: its five palettes, its four track colours, its greys, its
pixel font (Terminus, drawn 1x/2x/3x as SLOOP draws its big values), and a theme made in SLOOP's web editor.

The colours are SLOOP's own (isod89/sloop-fm1, firmware/src/gfx.c: PALETTES, TE_COL, TE_G), and the box follows
what FM-1 A shows (MENU > COLOR): read over USB by library.py (objects 1 and 11 of SLOOP's backup protocol,
theme_from_objects), or fixed in Settings.
"""

import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).resolve().parent / "vendor" / "fonts"
CACHE = Path.home() / ".cache" / "fm1-bridge"


def rgb(r, g, b):
    """SLOOP's RGB() as the panel shows it: through RGB565, so the colours match the FM-1's screen"""
    return (r >> 3 << 3, g >> 2 << 2, b >> 3 << 3)


def from565(c):
    """an RGB565 colour -> (r, g, b) as SLOOP's editor reads it (x * 8, x * 4, x * 8)"""
    return ((c >> 11) & 31) * 8, ((c >> 5) & 63) * 4, (c & 31) * 8


# the screen: five steps of one colour, faintest to strongest (rules, inactive, labels, secondary text, values)
PALETTES = {
    "GREEN": [rgb(0, 40, 12), rgb(0, 84, 30), rgb(16, 140, 54), rgb(56, 200, 92), rgb(120, 255, 146)],
    "AMBER": [rgb(60, 26, 0), rgb(110, 50, 0), rgb(170, 82, 0), rgb(225, 120, 8), rgb(255, 166, 40)],
    "CYAN": [rgb(0, 30, 50), rgb(0, 62, 96), rgb(16, 112, 160), rgb(56, 172, 222), rgb(140, 222, 255)],
    "RED": [rgb(52, 8, 8), rgb(100, 18, 14), rgb(170, 36, 26), rgb(226, 64, 48), rgb(255, 112, 92)],
    "MONO": [rgb(40, 40, 40), rgb(80, 80, 80), rgb(130, 130, 130), rgb(186, 186, 186), rgb(226, 226, 226)],
}
NAMES = list(PALETTES)                      # SLOOP's palette numbers: 0 GREEN ... 4 MONO
TRACKS = [rgb(40, 124, 255), rgb(30, 204, 112), rgb(255, 198, 24), rgb(255, 98, 26)]   # blue, green, yellow, orange

# the Studio's own themes, after SLOOP's five (FM-1 A can't show these): the five steps, the four track colours,
# the background and the highlight
EXTRA = {
    "NEON NOIR": ([rgb(46, 14, 64), rgb(92, 26, 120), rgb(186, 40, 190), rgb(255, 56, 170), rgb(60, 236, 255)],
                  [rgb(255, 40, 160), rgb(0, 224, 255), rgb(156, 84, 255), rgb(196, 255, 40)],
                  rgb(8, 4, 16), rgb(230, 250, 255)),
    "KAWAII": ([rgb(110, 84, 150), rgb(146, 116, 190), rgb(216, 174, 255), rgb(255, 168, 214), rgb(255, 252, 176)],
               [rgb(255, 168, 214), rgb(176, 208, 255), rgb(174, 255, 246), rgb(255, 252, 176)],
               rgb(74, 52, 110), rgb(255, 255, 255)),
    "BUBBLEGUM": ([rgb(176, 52, 124), rgb(214, 92, 162), rgb(255, 150, 204), rgb(255, 204, 230), rgb(255, 255, 255)],
                  [rgb(255, 255, 255), rgb(255, 172, 216), rgb(255, 84, 176), rgb(236, 150, 255)],
                  rgb(130, 22, 88), rgb(255, 255, 255)),
    "SYNTHWAVE": ([rgb(56, 20, 84), rgb(110, 32, 128), rgb(196, 52, 150), rgb(255, 92, 132), rgb(255, 192, 88)],
                  [rgb(255, 64, 150), rgb(255, 140, 40), rgb(40, 210, 255), rgb(170, 90, 255)],
                  rgb(16, 6, 34), rgb(255, 236, 200)),
    "8-BIT": ([rgb(36, 70, 36), rgb(56, 104, 48), rgb(100, 140, 24), rgb(139, 172, 15), rgb(196, 220, 90)],
              [rgb(196, 220, 90), rgb(90, 150, 70), rgb(236, 240, 180), rgb(130, 170, 30)],
              rgb(15, 40, 15), rgb(224, 240, 170)),
    "INFERNO": ([rgb(60, 10, 4), rgb(120, 24, 8), rgb(200, 56, 10), rgb(255, 130, 20), rgb(255, 222, 90)],
                [rgb(255, 60, 30), rgb(255, 150, 20), rgb(255, 230, 80), rgb(200, 40, 120)],
                rgb(14, 2, 0), rgb(255, 246, 220)),
    "TOXIC": ([rgb(30, 50, 10), rgb(60, 100, 14), rgb(110, 180, 20), rgb(170, 245, 30), rgb(220, 255, 120)],
              [rgb(170, 245, 30), rgb(190, 70, 255), rgb(255, 230, 40), rgb(40, 230, 190)],
              rgb(6, 10, 4), rgb(240, 255, 220)),
    "DEEP SEA": ([rgb(4, 40, 56), rgb(8, 74, 100), rgb(16, 130, 150), rgb(40, 200, 200), rgb(160, 250, 236)],
                 [rgb(40, 150, 255), rgb(40, 230, 180), rgb(255, 210, 120), rgb(255, 110, 140)],
                 rgb(2, 10, 22), rgb(230, 255, 252)),
}
ALL = NAMES + list(EXTRA)                   # MORE > THEME's list
GREYS = [rgb(26, 26, 30), rgb(54, 54, 60), rgb(118, 118, 126), rgb(196, 196, 204)]     # tiles, empty, labels, text

THEME_MAGIC = 0x324D4854                    # "THM2": SLOOP 2.7's theme record (gfx.c theme_t, 40 bytes)
CUSTOM_BIT = 1 << 30                        # the settings' lights word: the custom theme is the one shown


def scale(c, num, den):
    return tuple(v * num // den for v in c)


def mix(c, bg, num, den):
    """num/den of c, the rest bg"""
    return tuple((v * num + b * (den - num)) // den for v, b in zip(c, bg))


class Theme:
    """the colours to draw with: c[0..4] (the screen's steps), bg, hi (white unless a custom theme says),
    track[k] (full), mid[k] (2/3), dim[k] (1/3), grey[0..3] (adjusted for a non-black background, as SLOOP)"""

    def __init__(self, name="GREEN", c=None, tracks=None, bg=None, hi=None):
        own = EXTRA.get(name) if c is None else None    # one of the Studio's own, by name
        if own:
            c, tracks, bg, hi = own[0], tracks or own[1], bg or own[2], hi or own[3]
        self.name = name                      # (colours as tuples: a theme read back from JSON has lists, which
        self.c = [tuple(x) for x in (c or PALETTES.get(name, PALETTES["GREEN"]))]   # Pillow 11 refuses)
        self.bg, self.hi = tuple(bg or (0, 0, 0)), tuple(hi or (255, 255, 255))
        self.track = [tuple(t) for t in (tracks or TRACKS)]
        if name in EXTRA:                     # the Studio's own: dimmed toward their background, not black
            self.mid = [mix(t, self.bg, 2, 3) for t in self.track]
            self.dim = [mix(t, self.bg, 1, 3) for t in self.track]
        else:
            self.mid = [scale(t, 2, 3) for t in self.track]
            self.dim = [scale(t, 1, 3) for t in self.track]
        self.grey = [self.toward(g) for g in GREYS]

    def toward(self, grey):
        """SLOOP's te_gray: a grey drawn for black, the same share of the way from this background toward white
        (a dark one) or black (a light one)"""
        if self.bg == (0, 0, 0):
            return grey
        light = self.bg[0] * 299 + self.bg[1] * 587 + self.bg[2] * 114 > 128000
        return tuple(b + ((0 if light else 255) - b) * g // 255 for b, g in zip(self.bg, grey))

    def __eq__(self, other):
        return isinstance(other, Theme) and vars(self) == vars(other)


def parse_theme(data):
    """SLOOP's theme record (40 bytes) -> Theme, or None if it isn't one"""
    if len(data) < 38:
        return None
    magic, name = struct.unpack_from("<I8s", data)
    if magic != THEME_MAGIC:
        return None
    words = struct.unpack_from("<11H", data, 12)              # c[5], trk[4], bg, hi
    name = name.split(b"\0")[0].decode("ascii", "replace") or "MY THEME"
    return Theme(name, [from565(w) for w in words[:5]], [from565(w) for w in words[5:9]],
                 from565(words[9]), from565(words[10]))


def theme_from_objects(settings, theme):
    """SLOOP's settings object (1) and theme object (11, may be empty), as BK_GET returns them -> the Theme FM-1 A
    shows: its custom theme when MENU > COLOR has it, else the palette it's set to"""
    palette, lights = 0, 0
    if len(settings) >= 8:
        palette = struct.unpack_from("<I", settings, 4)[0]
        lights = struct.unpack_from("<I", settings, len(settings) - 4)[0] if len(settings) >= 12 else 0
    custom = parse_theme(theme or b"")
    if custom and lights & CUSTOM_BIT:
        return custom
    return Theme(NAMES[palette % len(NAMES)])


def theme_dict(t):
    return {"name": t.name, "c": t.c, "tracks": t.track, "bg": t.bg, "hi": t.hi}


def theme_load(d):
    """theme_dict's output (kept in a file) -> Theme"""
    try:
        return Theme(d["name"], d["c"], d["tracks"], d["bg"], d["hi"])
    except (KeyError, TypeError):
        return Theme()


# ---------------------------------------------------------------- the font

_fonts = {}


def font(bold=True, size=16):
    """Terminus 16 px (8 x 16 cells), SLOOP's font, as a Pillow font; size 12 (6 x 12, the Pocket's LCD: no bold)"""
    key = f"{size}{'n' if size == 12 or not bold else 'b'}"
    if key not in _fonts:
        name = f"ter-u{key}"
        pil = CACHE / f"{name}.pil"
        if not pil.exists():
            from PIL import BdfFontFile
            CACHE.mkdir(parents=True, exist_ok=True)
            with open(FONT_DIR / f"{name}.bdf", "rb") as f:
                BdfFontFile.BdfFontFile(f).save(str(CACHE / name))
        _fonts[key] = ImageFont.load(str(pil))
    return _fonts[key]


PLAIN = str.maketrans({"▶": ">", "◀": "<", "▲": "^", "▼": "v", "●": "*",
                       "•": "*", "›": ">", "‹": "<", "±": "+", "…": "...",
                       "–": "-", "—": "-", "→": ">"})


def plain(s):
    """s in what Terminus (as Pillow loads a BDF: Latin-1) can draw: SLOOP's own screens use ASCII"""
    return s.translate(PLAIN).encode("latin-1", "replace").decode("latin-1")


def text_size(s, size=1):
    """(width, height) of s drawn at size (1: 16 px high, 2: 32, 3: 48)"""
    return 8 * len(s) * size, 16 * size


def text(img, xy, s, color, size=1, bold=True):
    """s at xy (its top left) in Terminus, size times as big with square pixels, as SLOOP draws L = S at 2x"""
    s = plain(s)
    if not s:
        return
    if size == 1:
        ImageDraw.Draw(img).text(xy, s, font=font(bold), fill=color)
        return
    w, h = text_size(s)
    mask = Image.new("1", (w, h))
    ImageDraw.Draw(mask).text((0, 0), s, font=font(bold), fill=1)
    mask = mask.resize((w * size, h * size), Image.NEAREST)
    img.paste(Image.new("RGB", mask.size, color), (int(xy[0]), int(xy[1])), mask)
