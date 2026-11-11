#!/usr/bin/env python3
"""The FM-1 library: backups, projects, samples and firmware, one job at a time.

  library.py --fm1 A|B|C COMMAND ...  that FM-1 (A: the lowest USB port) instead of Settings > Sloop's, for a
                                      linked Studio's library (its FM-1 E-G are this Pocket's A-C)
  library.py backup [--auto] [--all]  back up the FM-1 (SLOOP 2.3+) into ~/fm1-library/backups; --all: every
                                      FM-1 plugged in, each in turn (one that fails doesn't stop the others)
  library.py restore FILE             a whole backup back onto the FM-1 (backs up first)
  library.py load-project FILE SRC TARGET
                                      a project into the FM-1: SRC working/A-D in a backup (ignored for a
                                      project file), TARGET working/A-D (backs up first)
  library.py save-project FILE SRC NAME
                                      a backup's project as its own file in ~/fm1-library/projects
  library.py song-backup [NAME]       the FM-1's song (SLOOP 2.5+: sections A-D and the song order) into
                                      ~/fm1-library/songs
  library.py song-load FILE           a song back onto the FM-1: its sections and song order, the rest of its
                                      settings kept (backs up first)
  library.py dx7-send FILE [VOICE]    a DX7 bank (.syx) to an FM-1 firmware that takes them, or one voice of it
                                      (1-32) as a single voice; not to SLOOP or Clipper, which don't
  library.py load-sample SLOT NAME WAV...
                                      WAV files into USR SLOT (1-4), one zone each
  library.py flash FILE.fwsc          install a firmware package (backs up first when it can)
  library.py fetch sloop|clipper      download the newest SLOOP or Clipper release into ~/fm1-library/firmware
                                      (fetch-sloop: the same as fetch sloop)
  library.py import-sd                copy new files from the SD card's fm1-library folder
  library.py list                     the library as JSON
  library.py info                     what the FM-1 runs
  library.py identify                 the same, quietly, for the screens ("SLOOP 2.8", not its USB name): every
                                      FM-1 plugged in, each noted on its own

Progress and the result go to $XDG_RUNTIME_DIR/fm1-library.json (the screen and the web page read it);
one job runs at a time. Exit code 0 when the job worked.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sloop  # noqa: E402
import x0x  # noqa: E402

LIBRARY = Path(os.environ.get("FM1_LIBRARY", Path.home() / "fm1-library"))
FOLDERS = ("backups", "projects", "samples", "firmware", "recordings", "x0x",   # x0x: X0X's backups (.x0b)
           "songs", "patches", "midi")                               # SLOOP songs; DX7 .syx; MIDI files to play
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir())
STATE, LOCK = RUNTIME / "fm1-library.json", RUNTIME / "fm1-library.lock"
FIRMWARE = RUNTIME / "fm1-firmware.json"     # what the connected FM-1 last said it runs
THEME = RUNTIME / "fm1-theme.json"           # FM-1 A's colours (SLOOP MENU > COLOR), for the Pocket's LCD
                                             # (its OLED has one colour: it never asks)
SETTINGS = Path(os.environ.get("FM1_SETTINGS") or Path.home() / ".config" / "fm1-bridge" / "fm1-bridge.json")
SD = Path(os.environ.get("FM1_SD_LIBRARY", "/boot/firmware/fm1-library"))
SD_SYNC = "/usr/local/sbin/fm1-sd-sync"
KEEP_AUTO = 20                               # the box's own backups kept unless Settings says (keep_backups, 1-100)
BOX_MADE = re.compile(r"_(studio-)?(auto|before-[a-z-]+)\.json$")   # write_backup's kinds but "manual" (Back up now)
X0X_MADE = re.compile(r"_X0X_(auto|before-[a-z-]+)\.x0b$")          # the same of X0X's
FM1_LETTERS = "ABC"                          # the FM-1s the library works on, by USB port (sloop.fm1_cards)
FM1 = None                                   # --fm1: one of them, else Settings > Sloop's (library_fm1)
FIRMWARES = {"sloop": ("SLOOP", "isod89/sloop-fm1"),            # isod89's firmwares, both based on Felucca
             "clipper": ("Clipper", "isod89/clipper-fm1")}       # (Clipper: experimental)
RELEASES = "https://api.github.com/repos/{}/releases?per_page=10"
SUFFIXES = {"backups": (".json",), "projects": (".json",), "samples": (".wav",), "firmware": (".fwsc",),
            "recordings": (".wav",), "x0x": (".x0b",), "songs": (".json",), "patches": (".syx",),
            "midi": (".mid", ".midi")}


def folder(name):
    path = LIBRARY / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def slug(text):
    return re.sub(r"[^A-Za-z0-9.]+", "-", str(text)).strip("-").lower() or "fm1"


# ---------------------------------------------------------------- one job at a time, with its progress

class Busy(Exception):
    pass


class Job:
    """The running job: holds the lock and writes its progress where the screen and web page look."""

    def __init__(self, name):
        self.name, self.lock = name, None
        self.status = {"job": name, "state": "running", "step": "", "percent": None, "message": "",
                       "started": time.time(), "pid": os.getpid(), "fm1": FM1}
        self.prefix = ""                       # "FM-1 B: " while a job goes through each FM-1 (each_fm1)

    def __enter__(self):
        RUNTIME.mkdir(parents=True, exist_ok=True)
        self.lock = open(LOCK, "a")
        try:
            import fcntl
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:                    # (Windows test runs: no lock)
            pass
        except OSError:
            self.lock.close()
            raise Busy("another library job is running")
        self.write()
        return self

    def __exit__(self, kind, error, trace):
        if kind is not None and self.status["state"] == "running":
            message = str(error) if isinstance(error, (sloop.SloopError, Busy, OSError, ValueError)) else repr(error)
            self.fail(message)
        self.lock.close()
        return False

    def write(self):
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.status))
        tmp.replace(STATE)

    def step(self, step, percent=None, message=""):
        step = self.prefix + step
        self.status.update(step=step, percent=percent, message=message)
        self.write()
        print(f"{step} {'' if percent is None else f'{percent:3.0f}% '}{message}".rstrip(), flush=True)

    def progress(self, step):
        """a progress(done, total) callback that updates at most a few times a second"""
        last = [0.0]

        def report(done, total):
            now = time.monotonic()
            if now - last[0] > 0.3 or done >= total:
                last[0] = now
                self.step(step, min(100.0, 100.0 * done / max(total, 1)))
        return report

    def done(self, message, **result):
        self.status.update(state="done", message=message, percent=100, finished=time.time(), result=result)
        self.write()
        print("done:", message, flush=True)

    def fail(self, message):
        self.status.update(state="error", message=message, finished=time.time())
        self.write()
        print("error:", message, file=sys.stderr, flush=True)


def read_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return None


def running():
    """the state of the library job that is running now (its process alive), else None"""
    state = read_state()
    if not state or state.get("state") != "running":
        return None
    try:
        os.kill(state.get("pid", 0), 0)
    except (OSError, TypeError):
        return None                           # it died without saying
    return state


def spawn(args):
    """start `library.py args` in the background, as its own systemd user unit where there is one (so it
    outlives whoever started it); -> an error message, or None"""
    if running():
        return "a library job is running"
    command = [sys.executable, str(Path(__file__).resolve()), *args]
    if shutil.which("systemd-run"):
        command = ["systemd-run", "--user", "--collect", "--quiet", f"--unit=fm1-library-{time.time_ns()}", *command]
    try:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        return str(e)
    return None


# A request from the web page to write to the FM-1: the box shows it and acts only when it's confirmed there
REQUEST = RUNTIME / "fm1-web-request.json"


def ask_box(args, title, lines, fm1=None):
    """fm1: the FM-1 it's for (A-C, --fm1), or None for Settings > Sloop's"""
    REQUEST.parent.mkdir(parents=True, exist_ok=True)
    # written in place: the box reads it every second and skips a half-written one
    REQUEST.write_text(json.dumps({"args": args, "title": title, "lines": lines, "fm1": fm1, "time": time.time()}))


def take_request():
    """the web page's pending request (taken once), if it's under 2 minutes old"""
    try:
        request = json.loads(REQUEST.read_text())
        REQUEST.unlink()
    except (OSError, ValueError):
        return None
    return request if time.time() - request.get("time", 0) < 120 else None


STATUS = RUNTIME / "fm1-status.json"    # the box's live status, for the web page
COMMANDS = RUNTIME / "fm1-commands.jsonl"  # the web page's settings commands, one JSON object a line


def write_status(status):
    """the box: its status for the web page (RAM: $XDG_RUNTIME_DIR), written in place like ask_box"""
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(dict(status, time=time.time())))


def read_status():
    """the web page: the box's status, or None if there's none or it's over 5 s old (the box isn't running)"""
    try:
        status = json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return None
    return status if time.time() - status.get("time", 0) < 5 else None


def queue_command(command):
    """the web page: a command for the box (settings, routes, transport, recording); appended, so several
    clicks in a row all arrive"""
    COMMANDS.parent.mkdir(parents=True, exist_ok=True)
    with open(COMMANDS, "a") as f:
        f.write(json.dumps(dict(command, time=time.time())) + "\n")


def take_commands():
    """the box: the queued commands (taken once), each under 30 s old"""
    taking = COMMANDS.with_suffix(".taking")
    try:
        COMMANDS.rename(taking)
        lines = taking.read_text().splitlines()
        taking.unlink()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            command = json.loads(line)
        except ValueError:
            continue
        if isinstance(command, dict) and time.time() - command.get("time", 0) < 30:
            out.append(command)
    return out


# ---------------------------------------------------------------- the device

def target_card():
    """the sound card of the FM-1 the library works on: with two or more plugged in, --fm1's or the one chosen in
    Settings > Sloop (FM-1 A, B or C, by USB port); None with one (whichever it is). One that isn't plugged in is
    an error, not another FM-1 (a Studio's FM-1 G must never write to its F)"""
    cards = sloop.fm1_cards()
    which = FM1 or chosen_fm1()
    n = FM1_LETTERS.index(which)
    if len(cards) < 2 and (n == 0 or not FM1):
        return None
    if n >= len(cards):
        if not FM1:                           # Settings' choice left over from an FM-1 since unplugged: A
            return cards[0] if cards else None
        raise sloop.SloopError("notfound", f"no FM-1 {which}: {len(cards)} plugged in")
    return cards[n]


def chosen_fm1():
    """Settings > Sloop's FM-1 (library_fm1): A, B or C"""
    try:
        which = json.loads(SETTINGS.read_text()).get("library_fm1", "A")
    except (OSError, ValueError, AttributeError):
        which = "A"
    return which if isinstance(which, str) and len(which) == 1 and which in FM1_LETTERS else "A"


def colour_screen():
    """True with a screen in colour: the Pocket's 1.44" or 1.3" LCD (Settings: "screen"; "lcd" the 1.44"'s old name)"""
    try:
        lcd = json.loads(SETTINGS.read_text()).get("screen") in ("lcd", "lcd144", "lcd13")
    except (OSError, ValueError, AttributeError):
        lcd = False
    return lcd


def read_theme(dev=None):
    """FM-1 A's colours as SLOOP shows them (its palette, or the theme made in SLOOP's web editor when that's
    chosen), saved in THEME for the Pocket's LCD. dev: an open FM-1 A, else it's opened here"""
    import sloopstyle
    cards = sloop.fm1_cards()
    if dev is None or (len(cards) > 1 and target_card() != cards[0]):
        dev = sloop.Sloop(sloop.Link(card=cards[0] if len(cards) > 1 else None))
    if not dev.can_backup() or sloop.family(dev.version) not in sloop.SLOOP_OWN:
        return None                           # not SLOOP 2.3+: no settings to read (the screen keeps its own)
    objects = dev.read_objects({1, 11})
    theme = sloopstyle.theme_from_objects(objects.get(1, b""), objects.get(11, b""))
    try:
        THEME.write_text(json.dumps(sloopstyle.theme_dict(theme)))
    except OSError:
        pass
    return theme


def connect():
    dev = sloop.Sloop(sloop.Link(card=target_card()))
    save_firmware({"firmware": str(dev.version)})
    return dev


def letter():
    """the FM-1 the library works on now, as target_card picks it: --fm1's, else Settings > Sloop's while it's
    plugged in, else A (the only one, or Settings' choice left over from an FM-1 since unplugged)"""
    if FM1:
        return FM1
    which = chosen_fm1()
    return which if FM1_LETTERS.index(which) < len(sloop.fm1_cards()) else "A"


def plugged_letters():
    """the FM-1s plugged in, by USB port: "A", "B", "C" ([] without any)"""
    return list(FM1_LETTERS[:len(sloop.fm1_cards())])


def seen_firmware():
    """{letter: what that FM-1 last said it runs}: each FM-1 on its own, so FM-1 B's never shows as A's"""
    try:
        seen = json.loads(FIRMWARE.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(seen, dict):
        return {}
    return {k: v for k, v in seen.items() if k in FM1_LETTERS and isinstance(v, dict)}


def save_firmware(entry):
    """what the FM-1 the library works on now (letter) says it runs"""
    seen = seen_firmware()
    seen[letter()] = entry
    try:
        FIRMWARE.write_text(json.dumps(seen))
    except OSError:
        pass


def forget_firmware():
    try:
        FIRMWARE.unlink()
    except OSError:
        pass


def firmware_labels():
    """{letter: firmware_label} of each FM-1 plugged in (None: not asked yet)"""
    return {x: firmware_label(x) for x in plugged_letters()}


def firmware_label(which=None):
    """"SLOOP 2.8" from what the FM-1 (which: A-C, else the one the library works on) last said ("FELUCCA SLOOP
    2.8"); None if nothing has asked it yet. Its USB name says Felucca whatever it runs. One without SLOOP's
    protocol: its handshake's ("FM-1+VA 102", "Stock 15": note_firmware)"""
    try:
        seen = seen_firmware()[which or letter()]
        if seen.get("label"):
            return str(seen["label"])
        words = str(seen["firmware"]).split()
    except (KeyError, TypeError, AttributeError):
        return None
    if len(words) > 1 and words[0].upper() == "FELUCCA" and not any(c.isdigit() for c in words[1]):
        words = words[1:]
    return " ".join(w if any(c.isdigit() for c in w) or w.upper() == "SLOOP" else w.capitalize()
                    for w in words) or None


def note_firmware(ident):
    """an FM-1 that answers M-VAVE's handshake but not SLOOP's protocol: what it runs, for the screens (its label:
    "FM-1+VA 102", "Stock 15"); None if it's neither"""
    import mvave
    kind = mvave.kind(ident)
    if kind not in ("baudgirl", "stock"):
        return None
    label = f"{'FM-1+VA' if kind == 'baudgirl' else 'Stock'} {ident.version}"
    save_firmware({"firmware": ident.text, "label": label})
    return label


def safety_backup(dev, job, why):
    """a backup before anything is written to the FM-1; None if this firmware can't make one"""
    if not dev.can_backup():
        return None
    job.step("Backing up first", 0)
    data = dev.backup(job.progress("Backing up first"))
    return write_backup(data, why)


def fm1_tag():
    """"_fm1-b" in a backup's name while two or more FM-1s are plugged in (which one it came from, and two backups
    in the same second don't share a name); "" with one"""
    return f"_fm1-{letter().lower()}" if len(sloop.fm1_cards()) > 1 else ""


def write_backup(data, kind):
    when = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = folder("backups") / f"{when}_{slug(data.get('firmware'))}{fm1_tag()}_{kind}.json"
    sloop.save_json(path, data)
    if kind != "manual":
        prune_auto()
    sd_export()
    return path


def keep_count():
    """Settings' keep_backups: how many of the box's own backups are kept (1-100)"""
    try:
        keep = json.loads(SETTINGS.read_text()).get("keep_backups", KEEP_AUTO)
    except (OSError, ValueError, AttributeError):
        keep = KEEP_AUTO
    return keep if isinstance(keep, int) and not isinstance(keep, bool) and 1 <= keep <= 100 else KEEP_AUTO


def prune_auto(keep=None):
    """the box's own backups (auto, and the safety ones before a restore or a load) beyond the newest keep_count:
    deleted. Back up now's are the user's: never. -> how many went"""
    old = []
    for name, made in (("backups", BOX_MADE), ("x0x", X0X_MADE)):
        found = sorted(p for p in folder(name).iterdir() if made.search(p.name))
        old += found[:-(keep or keep_count())]
    for path in old:
        path.unlink(missing_ok=True)
    return len(old)


# ---------------------------------------------------------------- the SD card's folder

def sd_export():
    """copy backups to the SD card (FAT, root only: through the installed helper); best effort"""
    if Path(SD_SYNC).exists():
        subprocess.run(["sudo", "-n", SD_SYNC], capture_output=True, timeout=60)


def import_sd():
    """new files from the SD card's fm1-library folders into the library; -> names copied"""
    copied = []
    for name in FOLDERS:
        if name == "recordings":              # made on the box, not brought in
            continue
        source = SD / name
        if not source.is_dir():
            continue
        for path in sorted(source.iterdir()):
            if not path.is_file() or path.suffix.lower() not in SUFFIXES[name] or path.name.startswith("."):
                continue
            target = folder(name) / path.name
            if target.exists() and target.stat().st_size == path.stat().st_size:
                continue
            shutil.copyfile(path, target)
            copied.append(f"{name}/{path.name}")
    return copied


# ---------------------------------------------------------------- the jobs

def each_fm1(job, work):
    """work(job) on every FM-1 plugged in, in turn (--fm1 set to each): one that fails doesn't stop the others.
    -> (lines, failed letters); with one FM-1 (or none, or --fm1 given), work(job) just once"""
    global FM1
    letters = [] if FM1 else plugged_letters()
    if len(letters) < 2:
        work(job)
        return None, []
    lines, failed = [], []
    try:
        for x in letters:
            FM1, job.prefix = x, f"FM-1 {x}: "
            try:
                work(job)
                lines.append(f"FM-1 {x}: {job.status['message']}")
            except (sloop.SloopError, OSError, ValueError) as e:
                lines.append(f"FM-1 {x}: {e}")
                failed.append(x)
            job.status.update(state="running", result=None)
    finally:
        FM1, job.prefix = None, ""
    if len(failed) == len(letters):
        raise sloop.SloopError("rc", "; ".join(lines))
    return lines, failed


def job_backup(auto=False, every=False):
    """every: each FM-1 plugged in (the auto backups), else the one the library works on"""
    with Job("backup") as job:
        if every:
            lines, failed = each_fm1(job, lambda j: backup_one(j, auto))
            if lines:
                job.done("; ".join(lines), failed=failed)
        else:
            backup_one(job, auto)


def backup_one(job, auto=False):
    """the FM-1 the library works on, backed up in its firmware's own way"""
    job.step("Connecting")
    try:
        dev = connect()
    except sloop.SloopError as e:
        if e.code != "noreply":
            raise
        return fm1va_backup(job, auto)         # (no SLOOP protocol: Baud Girl's FM-1+VA, if it's that)
    try:
        if sloop.family(dev.version) == "x0x":
            return x0x_fm1_backup(job, dev, "auto" if auto else "manual")
        dev.require_backup()
        data = dev.backup(job.progress("Backing up"))
        if colour_screen() and letter() == "A":   # and FM-1 A's colours, for a screen in colour: the boot
            try:                                   # backup learns what it runs, so "identify" isn't asked
                read_theme(dev)
            except sloop.SloopError:
                pass
        if auto:                               # timed backups: no new file when nothing changed
            latest = newest_auto()
            if latest and same_content(latest, data):
                job.done(f"No changes since {latest.name[11:13]}:{latest.name[13:15]}", file=latest.name,
                         unchanged=True)
                return
        path = write_backup(data, "auto" if auto else "manual")
        job.done(f"Backed up {dev.version}", file=path.name)
    finally:
        dev.link.close()                       # (each_fm1: the next FM-1 opens its own)


def x0x_fm1_backup(job, dev, kind):
    """an FM-1 running X0X: its project as a .x0b in the x0x folder (mvave.py), X0X's own backup format"""
    import mvave
    image, flags = mvave.x0x_backup(dev.link, job.progress("Backing up"))
    try:
        x0x.read_backup(image)
    except x0x.X0XError as e:
        raise sloop.SloopError("bad", f"X0X's backup: {e}")
    if kind == "auto":                         # (no new file when nothing changed)
        autos = sorted(folder("x0x").glob("*_X0X_auto.x0b"))
        if autos and autos[-1].read_bytes() == image:
            job.done(f"No changes since {autos[-1].name[11:13]}:{autos[-1].name[13:15]}", file=autos[-1].name,
                     unchanged=True)
            return autos[-1]
    path = folder("x0x") / f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_X0X_{kind}.x0b"
    path.write_bytes(image)
    if kind != "manual":
        prune_auto()
    sd_export()
    job.done(f"Backed up {dev.version}" + (" (not saved yet: left out)" if flags & 1 else ""), file=path.name)
    return path


def x0x_fm1_restore(job, file):
    """a .x0b onto an FM-1 running X0X: checked first, its project backed up first, then X0X takes the file and asks
    on its own screen (SEL yes, HOME no)"""
    import mvave
    image = Path(file).read_bytes()
    try:
        x0x.read_backup(image)                 # damaged files stop here, before anything is sent
    except x0x.X0XError as e:
        raise sloop.SloopError("bad", f"{Path(file).name}: {e}")
    job.step("Connecting")
    dev = connect()
    if sloop.family(dev.version) != "x0x":
        raise sloop.SloopError("family", f"that's an X0X backup, the FM-1 runs {dev.version}")
    job.step("Backing up first", 0)
    image_before, _ = mvave.x0x_backup(dev.link, job.progress("Backing up first"))
    before = folder("x0x") / f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_X0X_before-restore.x0b"
    before.write_bytes(image_before)
    prune_auto()
    code = mvave.x0x_restore(dev.link, image, job.progress("Sending"),
                             asking=lambda: job.step("On the FM-1: SEL to restore"))
    if code == mvave.X0X_PLAYING:
        raise sloop.SloopError("stop", "stop X0X first")
    if code == mvave.X0X_DECLINED:
        raise sloop.SloopError("rc", "not restored: HOME on the FM-1")
    if code:
        raise sloop.SloopError("rc", f"not restored: {mvave.X0X_ERRORS.get(code, f'code {code}')}")
    job.done(f"Restored {Path(file).name}", before=before.name)


def fm1va_link():
    """(link, identity) of an FM-1 running Baud Girl's FM-1+VA (mvave.py's handshake); SloopError otherwise"""
    import mvave
    link = sloop.Link(card=target_card())
    ident = mvave.identity(link)
    if mvave.kind(ident) != "baudgirl":
        link.close()
        raise sloop.SloopError("noreply", f"{ident.text if ident else 'the FM-1'}: no firmware the library knows")
    return link, ident


def fm1va_backup(job, auto=False):
    """its 128 presets (baudgirl.py) as a backup file of their own format, in the backups folder"""
    import baudgirl
    link, ident = fm1va_link()
    note_firmware(ident)
    try:
        data = baudgirl.backup(link, f"FM-1+VA {ident.text}", job.progress("Backing up"))
    finally:
        link.close()
    if auto:
        latest = newest_auto()
        if latest and same_content(latest, data):
            job.done(f"No changes since {latest.name[11:13]}:{latest.name[13:15]}", file=latest.name, unchanged=True)
            return
    path = write_backup(data, "auto" if auto else "manual")
    job.done(f"Backed up {ident.text}'s presets", file=path.name)


def fm1va_restore(job, file, data):
    """an fm1va-presets backup back: checked, the presets backed up first, then each written and read back"""
    import baudgirl
    baudgirl.presets_of(data)                  # damaged files stop here, before anything is written
    job.step("Connecting")
    link, ident = fm1va_link()
    try:
        before = write_backup(baudgirl.backup(link, f"FM-1+VA {ident.text}", job.progress("Backing up first")),
                              "before-restore")
        baudgirl.restore(link, data, job.progress("Restoring"))
    finally:
        link.close()
    job.done(f"Restored {Path(file).name}", before=before.name)


def newest_auto():
    """the newest auto backup of this FM-1 (with two plugged in, its own: A's and B's would never match)"""
    autos = sorted(folder("backups").glob(f"*{fm1_tag()}_auto.json"))
    return autos[-1] if autos else None


def same_content(path, data):
    """the backup file holds exactly the objects in data (dates and firmware strings aside)"""
    if data.get("format") == "fm1va-presets":
        import baudgirl
        try:
            return baudgirl.presets_of(sloop.load_json(path)) == baudgirl.presets_of(data)
        except sloop.SloopError:
            return False
    try:
        return sloop.objects_of(sloop.load_json(path)) == sloop.objects_of(data)
    except sloop.SloopError:
        return False


def job_restore(file):
    with Job("restore") as job:
        if str(file).endswith(".x0b"):          # X0X's, onto an FM-1 running X0X
            return x0x_fm1_restore(job, file)
        backup = sloop.load_json(file)
        if backup.get("format") == "fm1va-presets":   # Baud Girl's FM-1+VA's presets
            return fm1va_restore(job, file, backup)
        sloop.objects_of(backup)               # damaged files stop here, before anything is written
        job.step("Connecting")
        dev = connect()
        sloop.same_family(dev.version, backup.get("firmware"))      # before anything, even the backup
        dev.check_stopped()
        before = safety_backup(dev, job, "before-restore")
        dev.restore(backup, job.progress("Restoring"))
        job.done(f"Restored {Path(file).name}", before=before and before.name)


def job_load_project(file, source, target):
    if target not in sloop.PROJECT_IDS:
        raise ValueError("TARGET is working, A, B, C or D")
    with Job("load-project") as job:
        project = sloop.load_json(file)
        data = sloop.project_from(project, source)
        job.step("Connecting")
        dev = connect()
        sloop.same_family(dev.version, project.get("firmware"))     # before anything, even the backup
        dev.check_stopped()
        before = safety_backup(dev, job, "before-project")
        dev.put_project(data, target, job.progress("Loading project"), firmware=project.get("firmware"))
        where = "the working project" if target == "working" else f"project {target}"
        job.done(f"Loaded into {where}", before=before and before.name)


def job_song_backup(name=None):
    """the song on the FM-1 (its four sections and song order) as a song file"""
    with Job("song-backup") as job:
        job.step("Connecting")
        dev = connect()
        sections, order = dev.read_song(job.progress("Reading the song"))
        when = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        name = name or f"Song {datetime.now().strftime('%m-%d %H:%M')}"
        path = folder("songs") / f"{when}_{slug(name)}.json"
        sloop.save_json(path, sloop.song_file(sections, order, name, dev.version))
        sd_export()
        steps, _ = sloop.song_steps(order)
        used = "".join(n for n in sloop.SECTIONS if sections[n])
        job.done(f"Saved {name}: {len(steps)} steps, sections {used or 'none'}", file=path.name)


def job_song_load(file):
    with Job("song-load") as job:
        song = sloop.load_json(file)
        sections, order = sloop.song_from(song)  # damaged files stop here, before anything is written
        job.step("Connecting")
        dev = connect()
        sloop.same_family(dev.version, song.get("firmware"))        # before anything, even the backup
        dev.check_stopped()
        before = safety_backup(dev, job, "before-song")
        dev.put_song(sections, order, job.progress("Loading the song"), firmware=song.get("firmware"))
        job.done(f"Loaded {song.get('name') or Path(file).stem}", before=before and before.name)


def dx7_cards():
    """the FM-1s to try for DX7 patches, in turn: the one chosen in Settings > Sloop, then the other (two FM-1s, one
    on SLOOP for the library and one on a firmware that takes DX7: seen 2026-11-02, a Pocket user's); [None] with one"""
    chosen = target_card()
    if chosen is None or FM1:                 # (--fm1: that FM-1 only, never another one: a linked Studio's)
        return [chosen]
    return [chosen] + [c for c in sloop.fm1_cards() if c != chosen]


def job_dx7_send(file, voice=None):
    """a DX7 bank, or one of its voices (1-32), to the FM-1's MIDI: only the two standard DX7 messages (dx7.py).
    SLOOP and Clipper answer SLOOP's INFO and don't take DX7 SysEx: not sent to them; with two FM-1s, to the first
    that isn't on them"""
    import dx7
    with Job("dx7-send") as job:
        try:
            message = dx7.to_send(file, None if voice is None else voice - 1)
            what = dx7.describe(file)
        except (OSError, dx7.DX7Error) as e:
            raise sloop.SloopError("bad", f"{Path(file).name}: {e}")
        job.step("Connecting")
        refused = None
        for card in dx7_cards():
            link = sloop.Link(card=card)
            try:
                dev = None
                try:
                    dev = sloop.Sloop(link)
                    version = dev.version
                except sloop.SloopError as e:
                    if e.code != "noreply":
                        raise
                    version = None             # (no SLOOP protocol: another firmware)
                if sloop.family(version) == "sloopdx" and voice is None and what["kind"] == "bank":
                    before = safety_backup(dev, job, "before-dx7")    # (BANK_BEGIN empties the bank at once)
                    job.step("Sending")
                    dev.write_dx_bank(b"".join(dx7.read(Path(file).read_bytes())[1]))
                    job.done(f"Loaded {Path(file).stem} into sloopDX's bank in use", before=before and before.name)
                    return
                if sloop.family(version) not in (None, "jangada", "melodee"):   # (these two take DX7 SysEx)
                    refused = refused or version
                    continue                   # (SLOOP has its own FM6 bank: the other FM-1, if there is one)
                job.step("Sending")
                link.out.send(link.mido.Message("sysex", data=list(message[1:-1])))
                time.sleep(0.5)                # (a bank is 4 KB: let it go out before the port closes)
                break
            finally:
                link.close()
        else:
            raise sloop.SloopError("family", f"{refused} doesn't take DX7 SysEx (it has its own bank, on its editor)")
        if voice is None and what["kind"] == "bank":
            job.done(f"Sent {Path(file).stem}: 32 voices (on the FM-1, pick the bank it goes to)")
        else:
            job.done(f"Sent {what['voices'][0 if voice is None else voice - 1] or 'the voice'}")


def job_dx7_read():
    """the sound a stock FM-1 plays now, as a DX7 single-voice .syx in the patches folder (with two FM-1s, the first
    on stock firmware). Only M-VAVE's stock firmware is asked (mvave.py): nothing else is sent its read command"""
    import dx7
    import mvave
    with Job("dx7-read") as job:
        job.step("Connecting")
        seen = None
        for card in dx7_cards():
            link = sloop.Link(card=card)
            try:
                ident = mvave.identity(link)
                if mvave.kind(ident) != "stock":
                    seen = seen or (ident.text if ident else None)
                    continue
                job.step("Reading the sound")
                voice = mvave.read_voice(link)
                break
            finally:
                link.close()
        else:
            raise sloop.SloopError("family", f"{seen or 'this FM-1'}: reading its sound needs M-VAVE's stock firmware")
        name = dx7.voice_name(voice).strip() or "voice"
        path = folder("patches") / f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{slug(name)}.syx"
        path.write_bytes(dx7.voice_message(voice))
        sd_export()
        job.done(f"Saved {name} ({ident.text})", file=path.name)


def job_save_project(file, source, name):
    backup = sloop.load_json(file)
    data = sloop.project_from(backup, source)
    path = folder("projects") / f"{slug(name)}.json"
    sloop.save_json(path, sloop.project_file(data, name, backup.get("firmware"), f"{Path(file).name}:{source}"))
    print("saved", path)
    return path


SLOT_SECONDS = 7.3                      # a sample slot holds ~7.4 s at 22,050 Hz
# a sample's loudest point in the slot (16-bit): SLOOP's own uploader goes to 30000, ~0.8 dB below full scale,
# which leaves the FM-1 no room when it mixes a sample with other notes and sounds: it clips
SAMPLE_LEVELS = {"full": 30000, "-3 dB": 23197, "-6 dB": 16422}


def sample_peak():
    """the box's Sample level setting (Settings > Sloop), as a peak value; -6 dB if it isn't set"""
    try:
        level = json.loads(SETTINGS.read_text()).get("sample_level", "-6 dB")
    except (OSError, ValueError):
        level = "-6 dB"
    return SAMPLE_LEVELS.get(level, SAMPLE_LEVELS["-6 dB"])


def job_load_sample(slot, name, wavs):
    if slot not in (1, 2, 3, 4):
        raise ValueError("SLOT is 1, 2, 3 or 4")
    with Job("load-sample") as job:
        # no safety backup: a sample load only replaces that one slot, and the WAV it came from stays in the
        # library. Converting first means a bad WAV stops the job before the FM-1 is touched.
        job.step("Converting")
        header, data = sloop.build_slot(name, wavs, sample_peak())
        job.step("Connecting")
        dev = connect()
        dev.require_sample_slots()
        dev.check_stopped()
        done, report = [0], job.progress("Loading sample")

        def moved(n):
            done[0] += n
            report(done[0], len(data))

        dev.write_sample_slot(slot - 1, header, data, moved)
        job.done(f"USR{slot}: {name.upper()[:8]}")


def job_flash(package):
    import fm1_install
    with Job("flash") as job:
        letters = plugged_letters()
        if len(letters) > 1:                   # mid-update the FM-1 restarts as another device: the installer
            others = " and ".join(f"FM-1 {x}" for x in letters if x != letter())   # could pick up the wrong one
            raise sloop.SloopError("two", f"One FM-1 at a time: unplug {others} first")
        job.step("Checking the package")       # (~30 s on a Zero W)
        product, image = fm1_install.load_package(package, False)   # a bad package stops here
        job.step("Connecting")
        before = None
        try:
            dev = connect()
            dev.check_stopped()
            before = safety_backup(dev, job, "before-flash")
            dev.link.close()
        except sloop.SloopError as e:
            if e.code == "stop":
                raise
            # not SLOOP's editor (Felucca, stock, the update loader): flash without a backup
        updater = fm1_install.Updater(fm1_install.MidoBackend())
        device = updater.find()
        if not device:
            raise sloop.SloopError("notfound", "FM-1 not found for the update")
        steps = {"start": "Starting update", "loader": "Update mode", "reboot": "Restarting", "done": "Done"}

        def progress(kind, arg=None):
            if kind == "write":
                job.step("Writing", arg)
            elif kind == "check":
                job.step("Checking", None)
            else:
                job.step(steps.get(kind, kind))

        try:
            updater.install(device, image, product, progress)
        except fm1_install.InstallError as e:
            raise sloop.SloopError("rc", str(e))
        job.done(f"Installed {Path(package).stem}", product=product, before=before and before.name)


def newest_firmware(releases):
    """(release, its .fwsc asset) of the newest published release that has one (Clipper's are marked
    experimental, so GitHub's "latest" can't be relied on)"""
    for release in releases:
        if release.get("draft"):
            continue
        asset = next((a for a in release.get("assets", []) if a["name"].endswith(".fwsc")), None)
        if asset:
            return release, asset
    return None, None


def job_fetch(name):
    import fm1_install
    import urllib.request                      # (here, not at the top: 0.6 s of the Pocket's start-up on a Zero W)
    if name not in FIRMWARES:
        raise ValueError(f"fetch {' or '.join(FIRMWARES)}")
    title, repo = FIRMWARES[name]
    with Job(f"fetch-{name}") as job:
        job.step("Checking GitHub")
        request = urllib.request.Request(RELEASES.format(repo), headers={"Accept": "application/vnd.github+json",
                                                                         "User-Agent": "fm1-bridge"})
        with urllib.request.urlopen(request, timeout=20) as reply:
            release, asset = newest_firmware(json.load(reply))
        if not asset:
            raise ValueError(f"no {title} firmware file on GitHub")
        target = folder("firmware") / asset["name"]
        if target.exists() and target.stat().st_size == asset["size"]:
            job.done(f"Already have {asset['name']}", file=target.name)
            return
        tmp = target.with_suffix(".part")
        with urllib.request.urlopen(asset["browser_download_url"], timeout=60) as reply, open(tmp, "wb") as out:
            total, got = asset["size"], 0
            while chunk := reply.read(65536):
                out.write(chunk)
                got += len(chunk)
                job.step("Downloading", 100.0 * got / max(total, 1))
        fm1_install.load_package(str(tmp), False)      # a damaged download never gets listed
        tmp.replace(target)
        job.done(f"Downloaded {asset['name']}", file=target.name, tag=release.get("tag_name"))


PART = re.compile(r"^(.+_fm1)-(a|b|usb\d+|u-[a-z0-9]+)\.wav$")   # a take's part: "..._fm1-b.wav", "..._fm1-u-ep136.wav"


def part_label(key):
    """"a" -> "FM-1 A", "u-ep136" -> "EP136" (a USB device, by its name), "usb0" -> "USB keys" (before v2.9)"""
    if key.startswith("u-"):
        return key[2:].upper()
    if key.startswith("usb"):
        n = int(key[3:] or 0)
        return "USB keys" + (f" {n + 1}" if n else "")
    return f"FM-1 {key.upper()}"


def recording_parts(name):
    """a take's parts (recorded with Record parts on, next to it), as file names in recording order"""
    stem = Path(name).stem
    found = [p.name for p in folder("recordings").glob(f"{stem}-*.wav") if PART.match(p.name)]
    order = {"a": 0, "b": 1}
    return sorted(found, key=lambda n: (order.get(PART.match(n).group(2), 2), n))


def delete_recording(name):
    """a take, its parts and their clip counts"""
    for n in [name] + recording_parts(name):
        path = folder("recordings") / n
        path.unlink(missing_ok=True)
        Path(str(path) + ".clips").unlink(missing_ok=True)


def recording_entry(path):
    """{name, bytes, date, seconds, clips?} for a take or a part"""
    entry = {"name": path.name, "bytes": path.stat().st_size, "date": path.stat().st_mtime}
    with open(path, "rb") as f:               # 16-bit stereo, 44.1 or 48 kHz: the byte rate is in the header
        head = f.read(44)
    rate = int.from_bytes(head[28:32], "little") if head[:4] == b"RIFF" else 0
    entry["seconds"] = max(0, entry["bytes"] - 44) // (rate or 192000)
    try:                                      # flat tops counted when it was saved (meters.clip_count)
        entry["clips"] = int(Path(str(path) + ".clips").read_text())
    except (OSError, ValueError):
        pass
    return entry


def listing():
    """{folder: [{name, bytes, date, ...}]} newest first, backups with what's in them, recordings with their
    parts (each {name, part, label, seconds, ...}) instead of beside them"""
    out = {}
    for name in FOLDERS:
        entries = []
        for path in sorted(folder(name).iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_file() or path.suffix.lower() not in SUFFIXES[name]:
                continue
            if name == "recordings" and PART.match(path.name):
                continue                      # under its take, below
            entry = {"name": path.name, "bytes": path.stat().st_size, "date": path.stat().st_mtime}
            if name == "backups":
                try:
                    data = sloop.load_json(path)
                    if data.get("format") == "fm1va-presets":
                        import baudgirl
                        entry.update(baudgirl.describe(data))
                    else:
                        entry.update(sloop.describe(data))
                except sloop.SloopError:
                    entry["damaged"] = True
            elif name == "recordings":
                entry = recording_entry(path)
                parts = [dict(recording_entry(folder(name) / n), part=PART.match(n).group(2),
                              label=part_label(PART.match(n).group(2))) for n in recording_parts(path.name)]
                if parts:
                    entry["parts"] = parts
            elif name == "x0x":
                entry.update(x0x.describe(path.read_bytes()))
            elif name == "songs":
                try:
                    song = sloop.load_json(path)
                    sections, order = sloop.song_from(song)
                    steps, loop = sloop.song_steps(order)
                    entry.update(title=song.get("name"), firmware=song.get("firmware"), steps=len(steps), loop=loop,
                                 sections="".join(n for n in sloop.SECTIONS if sections[n]))
                except sloop.SloopError:
                    entry["damaged"] = True
            elif name == "patches":
                import dx7
                try:
                    entry.update(dx7.describe(path))
                except (OSError, dx7.DX7Error):
                    entry["damaged"] = True
            elif name == "midi":
                import midifile
                try:
                    entry.update(midifile.describe(path))
                except midifile.MidiFileError as e:
                    entry.update(damaged=True, error=str(e))
            elif name == "projects":
                try:
                    project = sloop.load_json(path)
                    entry.update(firmware=project.get("firmware"), title=project.get("name"))
                except sloop.SloopError:
                    entry["damaged"] = True
            entries.append(entry)
        out[name] = entries
    return out


def identify_one(job):
    """what the FM-1 the library works on runs, noted for the screens (firmware_label)"""
    try:
        dev = connect()
    except sloop.SloopError as e:
        if e.code != "noreply":
            raise
        import mvave                           # (no SLOOP protocol: stock or Baud Girl's, by M-VAVE's handshake)
        link = sloop.Link(card=target_card())
        try:
            label = note_firmware(mvave.identity(link))
        finally:
            link.close()
        if not label:
            raise
        job.done(label)
        return
    try:
        if colour_screen() and letter() == "A":   # and FM-1 A's colours, for a screen in colour
            try:
                read_theme(dev)
            except sloop.SloopError:
                pass
        job.done(firmware_label() or str(dev.version))
    finally:
        dev.link.close()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    global FM1
    if argv[0] == "--fm1":
        if len(argv) < 3 or argv[1] not in FM1_LETTERS or len(argv[1]) != 1:
            print(f"--fm1 is {', '.join(FM1_LETTERS)}", file=sys.stderr)
            return 2
        FM1, argv = argv[1], argv[2:]
    command, args = argv[0], argv[1:]
    try:
        if command == "backup":
            job_backup(auto="--auto" in args, every="--all" in args)
        elif command == "restore" and len(args) == 1:
            job_restore(args[0])
        elif command == "load-project" and len(args) == 3:
            job_load_project(args[0], args[1], args[2])
        elif command == "save-project" and len(args) == 3:
            job_save_project(*args)
        elif command == "song-backup" and len(args) <= 1:
            job_song_backup(args[0] if args else None)
        elif command == "song-load" and len(args) == 1:
            job_song_load(args[0])
        elif command == "dx7-read" and not args:
            job_dx7_read()
        elif command == "dx7-send" and len(args) in (1, 2):
            job_dx7_send(args[0], int(args[1]) if len(args) == 2 else None)
        elif command == "load-sample" and len(args) >= 3:
            job_load_sample(int(args[0]), args[1], args[2:])
        elif command == "flash" and len(args) == 1:
            job_flash(args[0])
        elif command == "update":            # the web app's update, confirmed on the box: update.py
            import update
            with Job("update") as job:
                error = update.start()
                if error:
                    raise ValueError(error)
                job.done("Updating: the Companion restarts when it's installed")
        elif command == "fetch-sloop":
            job_fetch("sloop")
        elif command == "fetch" and len(args) == 1:
            job_fetch(args[0])
        elif command == "import-sd":
            print(json.dumps(import_sd()))
        elif command == "list":
            print(json.dumps(listing(), indent=1))
        elif command == "identify":          # every FM-1 plugged in (--fm1: that one), each noted on its own
            with Job("identify") as job:
                lines, failed = each_fm1(job, identify_one)
                if lines:
                    job.done("; ".join(lines), failed=failed)
        elif command == "info":
            dev = connect()
            print(json.dumps({**dev.info, "can_backup": dev.can_backup()}))
        else:
            print(__doc__)
            return 2
        return 0
    except (sloop.SloopError, Busy, OSError, ValueError) as e:
        print("error:", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
