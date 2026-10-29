"""Which screen HAT the Pocket has. No Waveshare Zero HAT can be read back, so it's a setting ("screen"), chosen by
install.sh, by `fm1-screen` over SSH, or here: the screen picker, when the setting is "ask" (install.sh's "Not
sure") or KEY1 and KEY3 are held at power-on. It tries each driver in turn, each saying "Press KEY1 if you can read
this": the keys are on the same pins on every HAT, so they work whichever screen is fitted. A press is asked again
on the same screen ("Keep this screen? KEY1 again"), so one that lands a moment late, on the next driver, whose
screen can't be read, chooses nothing (seen on the Pocket: a late press picked the 1.3" LCD on its 1.44")."""
import time

from PIL import Image, ImageDraw

SCREENS = ("oled", "lcd144", "lcd13")           # the setting's values, in the order the picker tries them
NAMES = {"oled": '1.3" OLED', "lcd144": '1.44" LCD', "lcd13": '1.3" LCD'}
ALIASES = {"lcd": "lcd144"}                     # (the 1.44"'s name before the 1.3" came: boxes set up then keep it)
KEY1, KEY3 = 21, 16                             # bridge.KEYS's
GPIO_CHIP = "/dev/gpiochip0"
WAIT = 8.0                                      # seconds each screen asks for (and asks again after a press)


def setting(value):
    """the screen a setting names ("lcd" being "lcd144"), or None: ask (the picker)"""
    value = ALIASES.get(value, value)
    return value if value in SCREENS else None


def keys(pins=(KEY1, KEY3)):
    """the keys' lines, read with pull-ups (a pressed key pulls its line low: it reads inactive); None off a Pi"""
    try:
        import gpiod
        from gpiod.line import Bias, Direction
        return gpiod.request_lines(GPIO_CHIP, consumer="fm1-bridge screen picker", config={
            tuple(pins): gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP)})
    except (ImportError, OSError):
        return None


def pressed(request, pin):
    value = request.get_value(pin)              # (gpiod's Value.INACTIVE: by its name, so a stand-in can test it)
    return getattr(value, "name", str(value)) == "INACTIVE"


def held_at_start():
    """KEY1 and KEY3 both held as the Companion starts: open the picker"""
    request = keys()
    if request is None:
        return False
    try:
        return pressed(request, KEY1) and pressed(request, KEY3)
    finally:
        request.release()


def prompt(name, display, again=False):
    """what each screen shows while it's being tried (again: after a press, asking to keep it), in SLOOP's font:
    in one colour at 128x64 (the OLED's), or in colour at the panel's size"""
    import sloopstyle as st
    lines = (("Keep this", "screen?", "KEY1 again") if again else ("Press KEY1", "if you can", "read this"))         + (NAMES[name],)
    if getattr(display, "colour", False):
        size = getattr(display, "size", 128)
        img = Image.new("RGB", (size, size))
        d = ImageDraw.Draw(img)
        for i, line in enumerate(lines):
            d.text((6, 14 + i * 24), st.plain(line), font=st.font(), fill=(255, 255, 255) if i < 3 else (255, 200, 40))
        return img
    img = Image.new("1", (128, 64))
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((4, 2 + i * 15), st.plain(line), font=st.font(size=12), fill=1)
    return img


def press(request, wait, clock, sleep):
    """KEY1 pressed (and let go) within wait seconds"""
    until = clock() + wait
    while clock() < until:
        if request is not None and pressed(request, KEY1):
            while pressed(request, KEY1):
                sleep(0.02)
            return True
        sleep(0.05)
    return False


def pick(open_screen, choices=SCREENS, wait=WAIT, clock=time.monotonic, sleep=time.sleep, request=None):
    """try each screen until KEY1 is pressed on one, twice (asked, then asked to keep it): -> (its name, its open
    display). open_screen(name) opens a driver (an error: that one's skipped); each tried and not chosen is closed
    before the next."""
    request = request or keys((KEY1,))
    try:
        while True:
            for name in choices:
                try:
                    display = open_screen(name)
                except (OSError, RuntimeError, ValueError):
                    continue
                display.show(prompt(name, display))
                if press(request, wait, clock, sleep):
                    display.show(prompt(name, display, again=True))
                    if press(request, wait, clock, sleep):
                        return name, display
                getattr(display, "close", lambda: None)()
            if request is None:                   # (off a Pi: no keys to wait for)
                raise RuntimeError("no keys to pick a screen with")
    finally:
        if request is not None:
            request.release()
