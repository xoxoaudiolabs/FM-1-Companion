"""Tests for the Pocket's boards and screens: which Pi Zero can be one, the screen setting and its picker, the OLED
over I2C, the 1.3" LCD (ST7789) and the screens drawn at its size (120), fm1-screen.

  python tests/test_pocket_hw.py     (needs Pillow and numpy; no Pi or HAT)
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-pocket-hw-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"))
(TMP / "run").mkdir()

from PIL import Image, ImageDraw  # noqa: E402

import bridge  # noqa: E402
import device  # noqa: E402
import lcd  # noqa: E402
import oledi2c  # noqa: E402
import pocketui  # noqa: E402
import screenpick  # noqa: E402

ZERO_W = "Raspberry Pi Zero W Rev 1.1"
ZERO_2W = "Raspberry Pi Zero 2 W Rev 1.0"
ZERO = "Raspberry Pi Zero Rev 1.3"


def test_boards():
    """any Pi Zero is the Pocket; one without Bluetooth (no W) is told so; the core count is there"""
    w = device.detect(model=ZERO_W, screen=None, radio=True, cpus=1)
    two = device.detect(model=ZERO_2W, screen=None, radio=True, cpus=4)
    plain = device.detect(model=ZERO, screen=None, radio=False, cpus=1)
    assert w["build"] == two["build"] == plain["build"] == "pocket"
    assert w["cpus"] == 1 and two["cpus"] == 4 and "cores" in two["can"] and "cores" not in w["can"]
    assert device.no_bluetooth_text(w) is None and device.no_bluetooth_text(two) is None
    assert device.no_bluetooth_text(plain)[0] == "No Bluetooth"
    studio = device.detect(model="Raspberry Pi 3 Model B Plus Rev 1.3", screen=("/dev/fb1", 480, 320), radio=False)
    assert device.no_bluetooth_text(studio) is None                       # (the Pocket's rule alone)
    with tempfile.TemporaryDirectory() as tmp:
        assert not device.bluetooth(Path(tmp))
        (Path(tmp) / "hci0").mkdir()
        assert device.bluetooth(Path(tmp))
    assert not device.bluetooth(Path(tmp) / "gone")


def test_screen_setting():
    assert screenpick.setting("lcd") == "lcd144"                           # boxes set up with v2.10 keep it
    assert [screenpick.setting(v) for v in ("oled", "lcd144", "lcd13")] == ["oled", "lcd144", "lcd13"]
    assert screenpick.setting("ask") is None and screenpick.setting(None) is None
    assert lcd.PANELS["lcd"] is lcd.PANELS["lcd144"] is lcd.ST7735 and lcd.PANELS["lcd13"] is lcd.ST7789


class FakeKeys:
    """gpiod's request for the picker: KEY1 held over the given (from, to) times"""

    def __init__(self, clock, *presses):
        self.clock, self.presses, self.released = clock, presses, False

    def get_value(self, pin):
        from types import SimpleNamespace
        pressed = pin == screenpick.KEY1 and any(a <= self.clock() < b for a, b in self.presses)
        return SimpleNamespace(name="INACTIVE") if pressed else SimpleNamespace(name="ACTIVE")

    def release(self):
        self.released = True


class FakeScreen:
    def __init__(self, name, colour=False, size=128):
        self.name, self.colour, self.size, self.shown, self.closed = name, colour, size, [], False

    def show(self, img):
        self.shown.append(img)

    def close(self):
        self.closed = True


def test_screen_picker():
    """each screen asks for KEY1 in turn, and asks again after a press: the one pressed on twice is kept, open; a
    single press (a late one, landing on a screen that can't be read) chooses nothing; the others are closed; a
    driver that can't open is skipped; on round again until it's chosen"""
    now = [0.0]
    clock = lambda: now[0]                                                 # noqa: E731

    def sleep(seconds):
        now[0] += seconds
    opened = []

    def open_screen(name):
        if name == "lcd13":
            raise OSError("no such panel")
        opened.append(FakeScreen(name, colour=name != "oled"))
        return opened[-1]
    keys = FakeKeys(clock, (1.0, 1.2), (8.0, 8.2), (10.0, 10.2))         # once on the OLED, twice on the 1.44"
    name, display = screenpick.pick(open_screen, wait=5.0, clock=clock, sleep=sleep, request=keys)
    assert name == "lcd144" and display is opened[1] and not display.closed and keys.released
    assert opened[0].closed and opened[0].shown[0].mode == "1" and len(opened[0].shown) == 2   # asked, asked again
    assert display.shown[0].mode == "RGB" and display.shown[0].size == (128, 128) and len(display.shown) == 2
    now[0] = 0.0
    opened.clear()
    keys = FakeKeys(clock, (11.0, 11.1), (13.0, 13.1))                     # nothing on the first round: round again
    name, display = screenpick.pick(open_screen, wait=5.0, clock=clock, sleep=sleep, request=keys)
    assert name == "oled" and len(opened) == 3 and opened[0].closed and opened[1].closed


def test_pocket_screen():
    """the settings' screen opened ("lcd" as the 1.44"); "ask" opens the picker and keeps its choice; the OLED
    over I2C when one answers there"""
    made = []
    was = (dict(lcd.PANELS), oledi2c.find, bridge.SH1106, bridge.save_state, screenpick.pick,
           screenpick.held_at_start, oledi2c.SH1106I2C)
    try:
        for key in list(lcd.PANELS):
            lcd.PANELS[key] = lambda rotate, contrast, key=key: made.append(key) or FakeScreen(key, True)
        bridge.SH1106 = lambda rotate, contrast: made.append("spi oled") or FakeScreen("oled")
        oledi2c.SH1106I2C = lambda rotate, contrast, addr: made.append(f"i2c oled {addr:#x}") or FakeScreen("oled")
        saved = []
        bridge.save_state = lambda state: saved.append(dict(state))
        screenpick.held_at_start = lambda: False
        state = dict(bridge.DEFAULTS)
        oledi2c.find = lambda: None
        for value, want in (("oled", "spi oled"), ("lcd", "lcd144"), ("lcd144", "lcd144"), ("lcd13", "lcd13")):
            state["screen"] = value
            bridge.pocket_screen(state)
            assert made[-1] == want, (value, made)
        oledi2c.find = lambda: 0x3C
        state["screen"] = "oled"
        bridge.pocket_screen(state)
        assert made[-1] == "i2c oled 0x3c"
        screenpick.pick = lambda open_screen: ("lcd13", open_screen("lcd13"))
        state["screen"] = "ask"
        bridge.pocket_screen(state)
        assert state["screen"] == "lcd13" and saved[-1]["screen"] == "lcd13"
        screenpick.held_at_start = lambda: True                            # KEY1 + KEY3 at power-on: the picker
        state["screen"], saved[:] = "oled", []
        bridge.pocket_screen(state)
        assert saved[-1]["screen"] == "lcd13"
    finally:
        lcd.PANELS.clear()
        lcd.PANELS.update(was[0])
        (oledi2c.find, bridge.SH1106, bridge.save_state, screenpick.pick, screenpick.held_at_start,
         oledi2c.SH1106I2C) = was[1:]


def test_oled_over_i2c():
    """the SH1106's set-up as over SPI, then each page as 32-byte blocks after 0x40; found at 0x3C or 0x3D"""
    writes = []

    class Bus:
        def __init__(self, bus):
            pass

        def write_i2c_block_data(self, addr, control, data):
            writes.append((addr, control, list(data)))

        def read_byte(self, addr):
            if addr != 0x3D:
                raise OSError
            return 0

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass
    import types
    sys.modules["smbus2"] = types.SimpleNamespace(SMBus=Bus)
    try:
        assert oledi2c.find() == 0x3D
        oled = oledi2c.SH1106I2C(0, 128, 0x3D)
        assert writes[0][:2] == (0x3D, 0x00) and writes[0][2][:3] == [0xAE, 0xD5, 0x80] and 0x8B in writes[0][2]
        writes.clear()
        img = Image.new("1", (128, 64))
        ImageDraw.Draw(img).rectangle((0, 0, 127, 7), fill=1)             # the top page lit
        oled.show(img)
        pages = [w for w in writes if w[1] == 0x00]
        data = [w for w in writes if w[1] == 0x40]
        assert len(pages) == 8 and pages[0][2] == [0xB0, 0x02, 0x10] and len(data) == 32
        assert all(len(w[2]) == 32 for w in data) and data[0][2] == [0xFF] * 32 and data[4][2] == [0] * 32
        assert oledi2c.pack_pages(img) == bridge.pack_pages(img)
    finally:
        del sys.modules["smbus2"]


def test_st7789():
    """the 1.3" LCD: 240x240, the screens drawn at 120 and sent at twice the size; an OLED picture in the middle"""
    sent = []

    class Spi:
        def writebytes(self, data):
            sent.append(("cmd", list(data)))

        def writebytes2(self, data):
            sent.append(("pixels", bytes(data)))

    class Pins:
        def set_value(self, pin, value):
            pass
    panel = lcd.ST7789.__new__(lcd.ST7789)
    panel.spi, panel.pins, panel.on, panel.off = Spi(), Pins(), 1, 0
    panel.rotate, panel.ink, panel.dim = 0, (255, 255, 255), False
    assert panel.size == 120 and (panel.W, panel.H) == (240, 240)
    img = Image.new("RGB", (120, 120))
    img.putpixel((0, 0), (255, 0, 0))
    panel.show(img)
    assert sent[-5][1] == [0, 0, 0, 239] and sent[-3][1] == [0, 0, 0, 239] and len(sent[-1][1]) == 240 * 240 * 2
    frame = sent[-1][1]                                   # (TURN 180: the red pixel at the far corner, 2x2)
    assert frame[-2:] == b"\xf8\x00" and frame[-4:-2] == b"\xf8\x00" and frame[:2] == b"\x00\x00"
    panel.show(Image.new("1", (128, 64)))
    assert sent[-5][1] == [0, 56, 0, 183] and sent[-3][1] == [0, 88, 0, 151]      # 128x64 in the middle
    assert lcd.test_card(120).size == (120, 120)


class Lcd120:
    colour, size, image = True, 120, None

    def show(self, img):
        self.image = img.copy()

    def contrast(self, value):
        pass

    def power(self, on):
        pass


def test_screens_at_120():
    """every screen and meter at 120x120 for the 1.3" LCD: five rows to a list, nothing past the right edge, the
    1.44"'s 128 back afterwards"""
    import meters
    meters.load_numpy()
    app = bridge.App(Lcd120(), dict(bridge.DEFAULTS, desk_theme="CYAN", last_name="JBL Go 3"))
    app.save_settings = lambda: None
    app.pick = {"title": "Load project", "cursor": 4, "items": [(f"project {i}", "1 MB") for i in range(9)]}
    app.confirm = {"title": "Restore", "lines": ["Replaces FM-1 A's projects"]}
    app.job_title = "Backing up"
    app.scan_kind = "audio"
    app.route_key = next(iter(app.routes()))
    app.set_route(channels=list(range(16)))
    app.ed = {"loading": False, "error": None, "field": 1, "seconds": 4.0, "start": 1.0, "end": 3.0, "fade_in": 0.2,
              "fade_out": 0.0, "normalize": False, "reverse": False, "note": None, "found": None,
              "wave": [(-0.5, 0.5)] * 128, "out_name": "take"}
    app.message = None
    for screen in pocketui.SCREENS:
        app.screen = screen
        app.render(force=True)
        assert app.display.image.size == (120, 120), screen
    assert pocketui.ROWS == 5 and pocketui.FOOT == 104 and pocketui.CHARS == 19
    app.screen = "pick"
    app.render(force=True)
    t = app.theme
    lit = [y for y in range(pocketui.TOP, pocketui.FOOT) if app.display.image.getpixel((0, y)) == t.track[0]]
    assert lit and lit[0] == pocketui.TOP + 2 * pocketui.ROW_H - 1               # project 4 of 9: third row of 2-6
    for index in range(len(meters.METERS)):
        app.state["meter"] = index
        app.open_meters()
        app.screen = "meter"
        app.render(force=True)
        assert app.display.image.size == (120, 120)
    img = Image.new("RGB", (120, 120))
    pocketui.footer(ImageDraw.Draw(img), t, "press = pair   K1 = rescan")
    assert img.getbbox()[2] <= 120
    splash = pocketui.draw_splash(t, 120)
    assert splash.size == (120, 120)
    pocketui.use_size(128)
    assert (pocketui.W, pocketui.ROWS, pocketui.FOOT, pocketui.CHARS) == (128, 6, 112, 21)


def test_fm1_screen():
    """fm1-screen keeps the choice in the settings (the Companion restarted by systemd, not here)"""
    home = TMP / "home"
    settings = home / ".config" / "fm1-bridge" / "fm1-bridge.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"screen": "lcd", "rotate": 0}))
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "fm1-bt-bridge/config/fm1-screen"), *a],  # noqa
                                    env=env, capture_output=True, text=True)
    assert run().stdout.strip() == "screen: lcd144"
    assert run("lcd13").returncode == 0
    assert json.loads(settings.read_text()) == {"screen": "lcd13", "rotate": 0}
    assert run("hdmi").returncode == 2


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
