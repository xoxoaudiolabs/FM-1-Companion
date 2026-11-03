"""Render the Pocket's demo video with the box's own drawing code: the 1.44" LCD in the XOXO theme, driven by the
same key presses a user makes (each one lit on the drawn HAT), with a real recording of the FM-1 as its sound. The
meters are fed that recording, so they move with what you hear.

  python tools/render_video.py AUDIO.wav OUT.mp4 [--fonts DIR] [--ffmpeg PATH]

AUDIO.wav: the FM-1 recorded by the box (any rate, stereo). DIR: DejaVuSans.ttf and DejaVuSans-Bold.ttf (as for
render_screens.py). PATH: an ffmpeg (default: the one on PATH, else imageio-ffmpeg's). The captions use Windows'
Bahnschrift and Consolas when they're there, else DejaVu. Needs Pillow and numpy; no Pi or HAT.
"""
import argparse
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CLOCK = [1000.0]                          # the app's clock, moved a frame at a time (not the computer's)
time.monotonic = lambda: CLOCK[0]

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_screens as rs  # noqa: E402  (an empty library, the stand-ins, the screens' setups)

bridge, meters = rs.bridge, rs.meters
W, H, FPS = 1280, 720, 30
BG, BOARD, EDGE, INK, DIM, SIGNAL = (11, 11, 11), (24, 24, 24), (52, 52, 52), (242, 239, 233), (138, 134, 128), (255, 59, 31)
SCALE = 4                                 # the 128x128 LCD shown at 512x512
SX, SY = 196, 104                         # where the screen sits
LIT = 0.35                                # s a pressed key stays lit


def font(names, size, variation=None):
    for name in names:
        for folder in (Path("C:/Windows/Fonts"), Path(FONTS)):
            try:
                f = ImageFont.truetype(str(folder / name), size)
                if variation:
                    try:
                        f.set_variation_by_name(variation)
                    except (OSError, ValueError):
                        pass
                return f
            except OSError:
                continue
    return ImageFont.load_default()


class Audio:
    """the recording: the whole of it at 16 kHz for the meters"""

    def __init__(self, path):
        with wave.open(str(path)) as w:
            rate, ch = w.getframerate(), w.getnchannels()
            data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, ch)
        if ch == 1:
            data = np.repeat(data, 2, axis=1)
        idx = (np.arange(int(len(data) * meters.RATE / rate)) * rate / meters.RATE).astype(int)
        self.frames = data[idx, :2].astype(np.int16)
        self.seconds = len(data) / rate


class Levels:
    """meters.LevelReader, reading the recording at the video's time"""

    def __init__(self, audio):
        self.audio, self.target, self.proc, self.last = audio, None, None, None

    def start(self, target):
        self.target, self.proc = target, True

    def running(self):
        return True

    @property
    def seq(self):                        # (a new block each 32 ms, as the reader counts them)
        return int((CLOCK[0] - START) * meters.RATE / meters.BLOCK)

    def stop(self):
        self.target, self.proc = None, None

    def take(self):
        now = int((CLOCK[0] - START) * meters.RATE)
        last = self.last if self.last is not None and self.last <= now else max(0, now - meters.BLOCK)
        self.last = now
        f = self.audio.frames
        return f[last:now], f[max(0, now - meters.RECENT_N):now] if now else f[:0]


def board(img, lit):
    """the Waveshare 1.44" LCD HAT, drawn: KEY1-3 on the left, the joystick on the right, the screen between"""
    d = ImageDraw.Draw(img)
    d.rectangle((32, 72, 880, 648), fill=BOARD, outline=EDGE, width=2)
    for x, y in ((52, 92), (860, 92), (52, 628), (860, 628)):            # the mounting holes
        d.ellipse((x - 9, y - 9, x + 9, y + 9), fill=BG, outline=EDGE, width=2)
    d.rectangle((SX - 8, SY - 8, SX + 512 + 8, SY + 512 + 8), fill=(0, 0, 0))
    cx, cy = 800, 360                                                    # the joystick
    d.rectangle((cx - 56, cy - 56, cx + 56, cy + 56), fill=(18, 18, 18), outline=EDGE, width=2)
    arrows = {"up": (cx, cy - 38), "down": (cx, cy + 38), "left": (cx - 38, cy), "right": (cx + 38, cy)}
    for key, (x, y) in arrows.items():
        c = SIGNAL if key in lit else DIM
        tri = {"up": [(x, y - 9), (x - 9, y + 6), (x + 9, y + 6)], "down": [(x, y + 9), (x - 9, y - 6), (x + 9, y - 6)],
               "left": [(x - 9, y), (x + 6, y - 9), (x + 6, y + 9)], "right": [(x + 9, y), (x - 6, y - 9), (x - 6, y + 9)]}
        d.polygon(tri[key], fill=c)
    d.rectangle((cx - 18, cy - 18, cx + 18, cy + 18), fill=SIGNAL if "press" in lit else (40, 40, 40))
    d.text((cx, cy + 82), "JOYSTICK", font=MONO_S, fill=DIM, anchor="mm")
    for i, key in enumerate(("key1", "key2", "key3")):                   # KEY1 at the top, as the HAT is marked
        y = 236 + i * 124
        on = key in lit
        d.rectangle((80, y - 26, 140, y + 26), fill=SIGNAL if on else (30, 30, 30), outline=EDGE, width=2)
        d.text((110, y), key.upper().replace("KEY", "KEY "), font=MONO_S, fill=BG if on else INK, anchor="mm")


def wrap(d, text, f, width):
    """text's lines at most width wide (a newline in it starts a new one)"""
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            trial = (line + " " + word).strip()
            if d.textlength(trial, font=f) > width and line:
                lines.append(line)
                line = word
            else:
                line = trial
        lines += [line] if line else []
    return lines


def frame(screen, lit, title, text):
    img = Image.new("RGB", (W, H), BG)
    board(img, lit)
    img.paste(screen.resize((512, 512), Image.NEAREST), (SX, SY))
    d = ImageDraw.Draw(img)
    d.text((32, 22), "FM-1//COMPANION", font=BRAND, fill=INK)
    d.text((d.textlength("FM-1//COMPANION", font=BRAND) + 52, 34), "POCKET v" + VERSION, font=MONO, fill=SIGNAL)
    d.text((912, 150), title, font=TITLE, fill=SIGNAL)
    y = 226
    for line in wrap(d, text, BODY, 340):
        d.text((912, y), line, font=BODY, fill=INK)
        y += 36
    for i, line in enumerate(("Drawn by the Pocket's own code on a computer;",
                              "the sound is the FM-1, recorded by the box.")):
        d.text((32, 668 + i * 22), line, font=MONO_S, fill=DIM)
    return img


def script(app):
    """[(at s, caption title, caption, what's done then)]: what's done is a key name, or a function"""
    def setup_home():
        app.battery = {"percent": 78, "mv": 3818, "plugged": False}
        app.midi.peer = None

    sc = dict(rs.scenes(app))
    steps = [(0.0, "HOME", "The FM-1 on a Bluetooth speaker, a USB keyboard playing it, the battery's charge.",
              setup_home),
             (4.0, None, None, "up"), (4.6, None, None, "up"), (5.2, None, None, "down"),
             (7.5, "METERS", "Eleven meters, fed the FM-1 as it plays. Joystick left from HOME, up and down for the next.",
              "left")]
    t = 10.0
    for name in meters.METERS[1:]:
        steps.append((t, None, f"Meter: {name}.", "down"))
        t += 2.8
    steps += [(t + 0.6, "HOME", "Joystick right: back to HOME.", "right"),
              (t + 2.2, "SETTINGS", "Seven pages: Mixer, Playing, MIDI, Bluetooth, Studio link, Library and Box.",
               "right")]
    t += 3.6
    for _ in range(5):
        steps.append((t, None, None, "down"))
        t += 0.9
    steps += [(t, "LIBRARY", "The FM-1's files: backups, projects, songs, samples, DX7 patches, recordings, firmware.",
               "press"), (t + 2.5, None, None, "press")]
    t += 5.5
    steps += [(t, "TEN FIRMWARES", "Library's first page is named after what the FM-1 runs, with what's done for it: "
                                   "here, Felucca. Only SLOOP has been tried on an FM-1 so far.",
               lambda: (setattr(app, "fw_label", "Felucca v1.9.0"), app.render(force=True)))]
    t += 6.0
    steps += [(t, "DX7 PATCHES", "A bank of DX7 voices, sent whole or a voice at a time to a firmware that takes them.",
               sc["dx7-bank"]), (t + 2.0, None, None, "down"), (t + 2.8, None, None, "down")]
    t += 6.5
    steps += [(t, "MIDI ROUTES", "Bluetooth, USB keyboards, two FM-1s and the box's clock, routed to each other.",
               sc["matrix-two"]), (t + 2.0, None, None, "right"), (t + 3.0, None, None, "down"),
              (t + 4.5, "A ROUTE", "Transpose, channels, velocity, a key range or a split, arp and chord.", "press"),
              (t + 6.0, None, None, "down"), (t + 6.8, None, None, "down")]
    t += 10.0
    steps += [(t, "SAMPLE EDITOR", "A take turned into a sample: trim, fade, normalize, reverse, tune it to its note.",
               sc["editor"]), (t + 2.5, None, None, "down"), (t + 4.0, None, None, "down")]
    t += 7.5
    steps += [(t, "MIXER", "Two FM-1s and a keyboard's own synth, each at its level, recorded as parts too.",
               sc["settings-mixer"])]
    t += 5.5

    def themes():
        app.screen, app.settings_menu = "settings", "box"
        app.setting = [r[0] for r in app.settings_rows()].index("theme")
        app.change_setting()

    steps += [(t, "THEMES", "XOXO, the Studio's eight, or FM-1 A's own colours, shown as you move.", themes)]
    for i in range(4):
        steps.append((t + 1.5 + i * 1.1, None, None, "down"))
    t += 7.5

    def about():
        app.pick, app.screen, app.settings_menu = None, "settings", "box"
        app.setting = [r[0] for r in app.settings_rows()].index("about")
        app.change_setting()

    def home():                           # as it began: one FM-1 on SLOOP
        app.pick, app.screen, app.fw_label, app.midi.usb_b, app.source_b = None, "status", "SLOOP 2.8", None, None

    steps += [(t, "ABOUT", "Settings › Box › About: the version, the FM-1, the box's name and address.", about),
              (t + 5.0, "FM-1 COMPANION", "The code and the guide:\ngithub.com/xoxoaudiolabs\n/FM-1-Companion", home)]
    return steps


def main():
    global FONTS, BRAND, TITLE, BODY, MONO, MONO_S, START, VERSION
    parser = argparse.ArgumentParser()
    parser.add_argument("audio")
    parser.add_argument("out")
    parser.add_argument("--fonts", default="/usr/share/fonts/truetype/dejavu")
    parser.add_argument("--ffmpeg", default=None)
    args = parser.parse_args()
    FONTS = args.fonts
    bridge.font = lambda size, bold=False: ImageFont.truetype(
        str(Path(FONTS) / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)
    BRAND = font(["bahnschrift.ttf", "DejaVuSans-Bold.ttf"], 34, b"Bold Condensed")
    TITLE = font(["bahnschrift.ttf", "DejaVuSans-Bold.ttf"], 58, b"Bold Condensed")
    BODY = font(["bahnschrift.ttf", "DejaVuSans.ttf"], 27, b"Regular")
    MONO = font(["consolab.ttf", "DejaVuSans-Bold.ttf"], 20)
    MONO_S = font(["consola.ttf", "DejaVuSans.ttf"], 15)
    import device
    VERSION = device.POCKET_VERSION
    ffmpeg = args.ffmpeg or shutil.which("ffmpeg")
    if not ffmpeg:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    audio = Audio(args.audio)
    meters.load_numpy()
    import library
    rs.TAKE = rs.write_take(library.folder("recordings") / "2026-10-22_101544_fm1.wav")
    display = rs.LcdCapture()
    state = dict(bridge.DEFAULTS, last_name="JBL Go 3", last_mac="00:00:00:00:00:00", clock_mode="box",
                 desk_theme="XOXO", bpm=120)
    app = rs.pocket_app(display, state)
    app.levels = Levels(audio)
    app.midi.controllers = ["SMK-37+VA"]
    steps = script(app)
    seconds = min(audio.seconds, steps[-1][0] + 6.0)
    START = CLOCK[0]
    proc = subprocess.Popen([ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-i", args.audio, "-t", f"{seconds:.2f}",
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "slow",
                             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", args.out],
                            stdin=subprocess.PIPE)
    title, text, pressed, i = "", "", {}, 0
    for n in range(int(seconds * FPS)):
        t = n / FPS
        CLOCK[0] = START + t
        while i < len(steps) and steps[i][0] <= t:
            _, new_title, new_text, act = steps[i]
            title = new_title or title
            text = new_text or text
            if isinstance(act, str):
                app.on_key(act)
                pressed[act] = t
            elif act:
                act()
            i += 1
        app.render(force=app.screen == "meter")
        lit = {k for k, at in pressed.items() if t - at < LIT}
        proc.stdin.write(frame(display.image, lit, title, text).tobytes())
        if n % (FPS * 10) == 0:
            print(f"{t:5.1f} s  {title}", flush=True)
    proc.stdin.close()
    proc.wait()
    print("wrote", args.out)


if __name__ == "__main__":
    main()
