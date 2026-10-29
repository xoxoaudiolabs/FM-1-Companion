"""The Waveshare 1.44" LCD HAT: 128x128 colour (ST7735S) on SPI0 CE0, DC on GPIO25, reset on GPIO27, the backlight
on GPIO24. Its keys and joystick are the OLED HAT's (bridge.KEYS). Neither HAT can be read back over SPI, so which
one is fitted is a setting (state "screen": "oled" or "lcd").

The Pocket's screens are drawn 128x64 in one colour (the OLED's): show() puts them in the middle of the LCD, its
lit pixels in `ink`. An RGB image of 128x128 is shown as it is (the colour screens to come).

    python3 lcd.py              the test card for 30 s (stop fm1-bridge first: it holds the pins)"""
import sys
import time

from PIL import Image, ImageDraw

GPIO_CHIP = "/dev/gpiochip0"
PIN_DC, PIN_RST, PIN_BL = 25, 27, 24
W = H = 128
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


class ST7735:
    """the LCD, with the OLED's calls (show, contrast, power): the app needn't know which is fitted"""
    colour = True                                # (the app draws HOME in colour for it: pocketui)

    def __init__(self, rotate=0, contrast=128, ink=INK):
        import gpiod
        import spidev
        from gpiod.line import Direction, Value
        self.on, self.off = Value.ACTIVE, Value.INACTIVE
        self.pins = gpiod.request_lines(GPIO_CHIP, consumer="fm1-bridge lcd", config={
            (PIN_DC, PIN_RST, PIN_BL): gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE)})
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = 16_000_000
        self.spi.mode = 0
        self.rotate, self.ink, self.dim = rotate, ink, contrast <= 1
        self.pins.set_value(PIN_BL, self.off)
        self.pins.set_value(PIN_RST, self.off)
        time.sleep(0.01)
        self.pins.set_value(PIN_RST, self.on)
        time.sleep(0.12)
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
        self.cmd(0x11)                           # out of sleep
        time.sleep(0.12)
        self.fill((0, 0, 0))
        self.cmd(0x29)                           # display on
        self.pins.set_value(PIN_BL, self.on)

    def cmd(self, c, *data):
        self.pins.set_value(PIN_DC, self.off)
        self.spi.writebytes([c])
        if data:
            self.pins.set_value(PIN_DC, self.on)
            self.spi.writebytes(list(data))

    def window(self, x, y, w, h):
        self.cmd(0x2A, 0, X0 + x, 0, X0 + x + w - 1)
        self.cmd(0x2B, 0, Y0 + y, 0, Y0 + y + h - 1)
        self.cmd(0x2C)
        self.pins.set_value(PIN_DC, self.on)

    def fill(self, colour):
        self.window(0, 0, W, H)
        self.spi.writebytes2(mono565(Image.new("1", (W, H)), colour, colour))

    def show(self, img):
        turn = (self.rotate + TURN) % 360
        if turn:
            img = img.rotate(turn)
        if img.mode == "1":                      # a Pocket screen (128x64): in the middle, in its ink
            ink = tuple(v // 3 for v in self.ink) if self.dim else self.ink
            self.window(0, (H - img.height) // 2, img.width, img.height)
            self.spi.writebytes2(mono565(img, ink))
        else:
            self.window(0, 0, W, H)
            self.spi.writebytes2(rgb565(img))

    def contrast(self, value):
        """the OLED's contrast: here 1 (dimmed: no key pressed for a while) draws in a third of the ink's
        brightness (the backlight is on or off only); the next frame shows it"""
        self.dim = value <= 1

    def power(self, on):
        self.cmd(0x29 if on else 0x28)
        self.pins.set_value(PIN_BL, self.on if on else self.off)


def test_card():
    """a 1-pixel frame round the edge (all four sides should show), red, green and blue bars, TOP at the top and
    KEYS on the side the keys should be"""
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W - 1, H - 1), outline=(255, 255, 255))
    for k, (name, colour) in enumerate((("RED", (255, 0, 0)), ("GREEN", (0, 255, 0)), ("BLUE", (0, 0, 255)))):
        d.rectangle((20, 40 + k * 22, 107, 58 + k * 22), fill=colour)
        d.text((24, 44 + k * 22), name, fill=(0, 0, 0))
    d.text((52, 6), "TOP", fill=(255, 255, 255))
    d.text((4, 20), "KEYS", fill=(255, 255, 0))
    return img


if __name__ == "__main__":
    lcd = ST7735()
    lcd.show(test_card())
    time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 30)
    lcd.power(False)
