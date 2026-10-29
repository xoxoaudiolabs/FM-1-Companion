"""The Waveshare Zero LCD HATs, both on SPI0 CE0 with DC on GPIO25, reset on GPIO27 and the backlight on GPIO24, and
the OLED HAT's keys and joystick (bridge.KEYS):

  1.44" LCD HAT   ST7735S, 128x128 colour          ST7735   (tried on the Pocket)
  1.3" LCD HAT    ST7789, 240x240 colour IPS       ST7789   (not tried on one yet: its colour order, turn and
                                                             offsets are from Waveshare's demo; check them with
                                                             the test card)

No HAT can be read back over SPI, so which one is fitted is a setting (state "screen": "oled", "lcd144" or "lcd13";
"lcd" is the 1.44" too, its name before the 1.3" came). The colour screens (pocketui) are drawn at the panel's
`size`: 128 on the 1.44", 120 on the 1.3", shown there at twice the size. A 128x64 picture in one colour (the
OLED's) goes in the middle in `ink`.

    python3 lcd.py [lcd144|lcd13] [SECONDS]   the test card (stop fm1-bridge first: it holds the pins)"""
import sys
import time

from PIL import Image, ImageDraw

GPIO_CHIP = "/dev/gpiochip0"
PIN_DC, PIN_RST, PIN_BL = 25, 27, 24
W = H = 128                    # the 1.44" (ST7735S):
X0, Y0 = 1, 2                  # the panel's first pixel in the controller's RAM (132x162): Waveshare's 2, 1 swapped,
                               # as its code does with rows and columns exchanged (MADCTL's 0x20)
MADCTL = 0x60                  # row/column order (with it the picture came out upside down on the Pocket: TURN)
TURN = 180                     # the LCD sits 180 degrees round from the OLED: the same "rotate" setting does for both
BGR = 0x08                     # the panel's colour order is BGR
INK = (255, 255, 255)          # a 128x64 screen's lit pixels


def rgb565(img):
    """an RGB image -> its pixels as RGB565, big-endian (the ST7735S's 16-bit colour)"""
    import numpy as np
    a = np.asarray(img.convert("RGB"), dtype=np.uint16)
    v = ((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)
    return v.astype(">u2").tobytes()


def mono565(img, ink, paper=(0, 0, 0)):
    """a 1-bit image -> RGB565 in two colours, without numpy's per-pixel work: each pixel's two bytes from a
    lookup (an "LA" image's bytes are its two bands interleaved)"""
    def word(c):
        return ((c[0] & 0xF8) << 8) | ((c[1] & 0xFC) << 3) | (c[2] >> 3)
    on, off = word(ink), word(paper)
    grey = img.convert("L")
    hi = grey.point(lambda v: on >> 8 if v else off >> 8)
    lo = grey.point(lambda v: on & 0xFF if v else off & 0xFF)
    return Image.merge("LA", (hi, lo)).tobytes()


class Panel:
    """an SPI colour LCD on the HAT's pins, with the OLED's calls (show, contrast, power): the app needn't know
    which is fitted. A panel gives its controller's set-up (setup), its pixels (W, H), where they start in its RAM
    (X0, Y0), how far round it sits from the OLED (TURN), its SPI clock and the size the screens are drawn at."""
    colour = True                                # (the app draws its screens in colour for it: pocketui)
    W = H = 128
    X0 = Y0 = 0
    TURN = 0
    SPEED = 16_000_000
    size = 128

    def __init__(self, rotate=0, contrast=128, ink=INK):
        import gpiod
        import spidev
        from gpiod.line import Direction, Value
        self.on, self.off = Value.ACTIVE, Value.INACTIVE
        self.pins = gpiod.request_lines(GPIO_CHIP, consumer="fm1-bridge lcd", config={
            (PIN_DC, PIN_RST, PIN_BL): gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE)})
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = self.SPEED
        self.spi.mode = 0
        self.rotate, self.ink, self.dim = rotate, ink, contrast <= 1
        self.pins.set_value(PIN_BL, self.off)
        self.pins.set_value(PIN_RST, self.off)
        time.sleep(0.01)
        self.pins.set_value(PIN_RST, self.on)
        time.sleep(0.12)
        self.setup()
        self.cmd(0x11)                           # out of sleep
        time.sleep(0.12)
        self.fill((0, 0, 0))
        self.cmd(0x29)                           # display on
        self.pins.set_value(PIN_BL, self.on)

    def setup(self):
        pass

    def cmd(self, c, *data):
        self.pins.set_value(PIN_DC, self.off)
        self.spi.writebytes([c])
        if data:
            self.pins.set_value(PIN_DC, self.on)
            self.spi.writebytes(list(data))

    def window(self, x, y, w, h):
        x, y = self.X0 + x, self.Y0 + y
        self.cmd(0x2A, x >> 8, x & 0xFF, (x + w - 1) >> 8, (x + w - 1) & 0xFF)
        self.cmd(0x2B, y >> 8, y & 0xFF, (y + h - 1) >> 8, (y + h - 1) & 0xFF)
        self.cmd(0x2C)
        self.pins.set_value(PIN_DC, self.on)

    def fill(self, colour):
        self.window(0, 0, self.W, self.H)
        self.spi.writebytes2(mono565(Image.new("1", (self.W, self.H)), colour, colour))

    def show(self, img):
        turn = (self.rotate + self.TURN) % 360
        if turn:
            img = img.rotate(turn)
        if img.mode == "1":                      # a Pocket screen (128x64): in the middle, in its ink
            ink = tuple(v // 3 for v in self.ink) if self.dim else self.ink
            if img.width > self.W:
                img = img.crop(((img.width - self.W) // 2, 0, (img.width + self.W) // 2, img.height))
            self.window((self.W - img.width) // 2, (self.H - img.height) // 2, img.width, img.height)
            self.spi.writebytes2(mono565(img, ink))
        else:
            if img.size != (self.W, self.H):     # drawn at self.size: the 1.3"'s 120 at twice the size
                img = img.resize((self.W, self.H), Image.NEAREST)
            self.window(0, 0, self.W, self.H)
            self.spi.writebytes2(rgb565(img))

    def contrast(self, value):
        """the OLED's contrast: here 1 (dimmed: no key pressed for a while) draws in a third of the ink's
        brightness (the backlight is on or off only); the next frame shows it"""
        self.dim = value <= 1

    def power(self, on):
        self.cmd(0x29 if on else 0x28)
        self.pins.set_value(PIN_BL, self.on if on else self.off)

    def close(self):
        """the pins and SPI let go (the screen picker tries the next HAT's driver on them)"""
        self.pins.release()
        self.spi.close()


class ST7735(Panel):
    """the 1.44" LCD HAT (tried on the Pocket: these settings were checked on its test card)"""
    W, H, X0, Y0, TURN, SPEED, size = W, H, X0, Y0, TURN, 16_000_000, 128

    def setup(self):
        # Waveshare's ST7735S set-up for this panel: frame rates, power, gamma, 16-bit colour
        for c, *data in ((0xB1, 0x01, 0x2C, 0x2D), (0xB2, 0x01, 0x2C, 0x2D),
                         (0xB3, 0x01, 0x2C, 0x2D, 0x01, 0x2C, 0x2D), (0xB4, 0x07),
                         (0xC0, 0xA2, 0x02, 0x84), (0xC1, 0xC5), (0xC2, 0x0A, 0x00), (0xC3, 0x8A, 0x2A),
                         (0xC4, 0x8A, 0xEE), (0xC5, 0x0E),
                         (0xE0, 0x0F, 0x1A, 0x0F, 0x18, 0x2F, 0x28, 0x20, 0x22, 0x1F, 0x1B, 0x23, 0x37, 0x00, 0x07,
                          0x02, 0x10),
                         (0xE1, 0x0F, 0x1B, 0x0F, 0x17, 0x33, 0x2C, 0x29, 0x2E, 0x30, 0x30, 0x39, 0x3F, 0x00, 0x07,
                          0x03, 0x10),
                         (0xF0, 0x01), (0xF6, 0x00), (0x3A, 0x05), (0x36, MADCTL | BGR)):
            self.cmd(c, *data)


class ST7789(Panel):
    """the 1.3" LCD HAT, 240x240: the screens drawn at 120 and shown at twice the size. NOT TRIED ON ONE YET: the
    set-up is Waveshare's demo's for this HAT (MADCTL 0x70, RGB order, colours inverted as IPS panels want, no
    offset at 240x240), and TURN guesses it sits as the 1.44" does. Its test card says what to change."""
    W, H, X0, Y0, TURN, SPEED, size = 240, 240, 0, 0, 180, 40_000_000, 120

    def setup(self):
        for c, *data in ((0x36, 0x70), (0x3A, 0x05), (0xB2, 0x0C, 0x0C, 0x00, 0x33, 0x33), (0xB7, 0x35),
                         (0xBB, 0x19), (0xC0, 0x2C), (0xC2, 0x01), (0xC3, 0x12), (0xC4, 0x20), (0xC6, 0x0F),
                         (0xD0, 0xA4, 0xA1),
                         (0xE0, 0xD0, 0x04, 0x0D, 0x11, 0x13, 0x2B, 0x3F, 0x54, 0x4C, 0x18, 0x0D, 0x0B, 0x1F, 0x23),
                         (0xE1, 0xD0, 0x04, 0x0C, 0x11, 0x13, 0x2C, 0x3F, 0x44, 0x51, 0x2F, 0x1F, 0x1F, 0x20, 0x23),
                         (0x21,)):        # (0x21: colours inverted, as this IPS panel shows them right)
            self.cmd(c, *data)


PANELS = {"lcd144": ST7735, "lcd": ST7735, "lcd13": ST7789}


def test_card(size=128):
    """a 1-pixel frame round the edge (all four sides should show), red, green and blue bars, TOP at the top and
    KEYS on the side the keys should be (drawn at size: the panel's size)"""
    img = Image.new("RGB", (size, size))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, size - 1, size - 1), outline=(255, 255, 255))
    for k, (name, colour) in enumerate((("RED", (255, 0, 0)), ("GREEN", (0, 255, 0)), ("BLUE", (0, 0, 255)))):
        d.rectangle((20, 40 + k * 22, size - 21, 58 + k * 22), fill=colour)
        d.text((24, 44 + k * 22), name, fill=(0, 0, 0))
    d.text((size // 2 - 12, 6), "TOP", fill=(255, 255, 255))
    d.text((4, 20), "KEYS", fill=(255, 255, 0))
    return img


if __name__ == "__main__":
    args = sys.argv[1:]
    kind = args.pop(0) if args and args[0] in PANELS else "lcd144"
    lcd = PANELS[kind]()
    lcd.show(test_card(lcd.size))
    time.sleep(float(args[0]) if args else 30)
    lcd.power(False)
