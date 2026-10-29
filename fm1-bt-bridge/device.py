"""Which FM-1 Companion this is, and what it can do.

Two builds share one codebase: the pocket box (a Pi Zero W or Zero 2 W with a Waveshare Zero HAT: a screen,
a joystick and three keys) and the desk box (a Pi 3/4 with a 3.5" 480x320 SPI touchscreen). The box looks at its
board and screen at start; features that need more than a Zero can carry ask detect()'s "can" set instead of the
board. Settings' "build" ("auto", "pocket" or "desk") overrides the guess. Any Pi Zero is the pocket box, but only
one with Bluetooth (the W boards) can do its job: detect()'s "bluetooth" says which.
"""

import os
from pathlib import Path

POCKET_VERSION = "2.11"         # the Pocket's release (the Studio's: deskboot.VERSION), shown by fm1-report
MODEL = Path("/proc/device-tree/model")
FRAMEBUFFERS = Path("/sys/class/graphics")
BLUETOOTH = Path("/sys/class/bluetooth")


def board(path=MODEL):
    """"Raspberry Pi 3 Model B Plus Rev 1.3", or "" off a Pi"""
    try:
        return path.read_bytes().rstrip(b"\0").decode(errors="replace")
    except OSError:
        return ""


def bluetooth(root=BLUETOOTH):
    """the board has a Bluetooth adapter (hci0): a Pi Zero W or Zero 2 W does, a Pi Zero (1.3, H) doesn't"""
    try:
        return any(p.name.startswith("hci") for p in root.iterdir())
    except OSError:
        return False


def touchscreen(root=FRAMEBUFFERS):
    """(framebuffer device, width, height) of a small SPI screen (480x320), or None: fbtft's (fb_ili9486) or the
    kernel's DRM driver's (ili9486drmfb: the piscreen overlay's, Raspberry Pi OS from 2026), which is /dev/fb0
    when no HDMI monitor was there at boot, else /dev/fb1"""
    for fb in sorted(root.glob("fb[0-9]")):
        try:
            width, height = (int(v) for v in (fb / "virtual_size").read_text().strip().split(","))
        except (OSError, ValueError):
            continue
        try:
            name = (fb / "name").read_text().strip().lower()
        except OSError:
            name = ""
        spi = any(k in name for k in ("fb_", "ili94", "piscreen", "mipi-dbi"))
        if spi or (fb.name != "fb0" and width * height <= 800 * 480):   # (fb0 unnamed: an HDMI monitor)
            return f"/dev/{fb.name}", width, height
    return None


def detect(setting="auto", model=None, screen="look", radio=None, cpus=None):
    """-> {"build": "pocket" or "desk", "board", "screen": (device, w, h) or None, "can": set(), "bluetooth",
    "cpus"}

    can: "touch" and "color" (the desk box's screen), "cores" (4 of them: smooth meters, more at once),
    "usb_ports" (built-in USB ports: no hub, no 12 Mbit/s setting). bluetooth: an adapter is there (a Pi Zero
    without it can't be a Companion). cpus: the core count (1 on a Zero W, 4 on a Zero 2 W)."""
    model = board() if model is None else model
    screen = touchscreen() if screen == "look" else screen
    radio = bluetooth() if radio is None else radio
    cpus = (os.cpu_count() or 1) if cpus is None else cpus
    zero = "Zero" in model
    if setting in ("pocket", "desk"):
        build = setting
    else:
        build = "desk" if screen and not zero else "pocket"
    can = set()
    if build == "desk":
        can |= {"touch", "color"}
    if cpus >= 4 and not model.startswith("Raspberry Pi Zero W"):
        can.add("cores")
    if model and not zero:
        can.add("usb_ports")
    return {"build": build, "board": model, "screen": screen, "can": can, "bluetooth": radio, "cpus": cpus}


def no_bluetooth_text(box):
    """what the screen says on a Pi Zero with no Bluetooth (a Zero, 1.3 or H: no W), or None when there is"""
    if box["build"] != "pocket" or box["bluetooth"]:
        return None
    return ["No Bluetooth", "This Pi has no", "wireless: use a", "Pi Zero W or 2 W"]
