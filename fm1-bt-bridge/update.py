#!/usr/bin/env python3
"""The web app's one-click update: the newest FM-1 Companion release for this box, from the project's GitHub
(xoxoaudiolabs/FM-1-Companion: tags v2.x for the Pocket, studio-v1.x for the Studio).

What's yours stays as it is: an update replaces the Companion's code (~/.local/share/fm1-bridge) and its system
files, never the settings and pairings (~/.config/fm1-bridge), the library (~/fm1-library: backups, projects,
songs, samples, recordings, kits, patches) or the Studio apps' own saves. It won't start while a recording or a
library job (a backup, a load, a firmware install) is running.

The web page asks for it (Library > Software); the box asks for the hold-press, as for anything that writes to
the FM-1, then runs `library.py update`, which starts `update.py run` as a systemd unit of its own (it outlives
the Companion's restart). That asks /usr/local/sbin/fm1-update (root, no password: install.sh's sudoers) to
install the release with its own install.sh, restarts the Companion and waits for it: if it doesn't come back,
the code from before is put back (fm1-update --back) and started again.

  python3 update.py check     the installed version and the newest, as JSON
  python3 update.py run       update now (what the box starts)

Python's standard library only.
"""
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import library  # noqa: E402

REPO = "xoxoaudiolabs/FM-1-Companion"
TAGS = f"https://api.github.com/repos/{REPO}/tags?per_page=100"
NOTES = f"https://github.com/{REPO}/blob/main/docs/CHANGELOG.md"
HELPER = "/usr/local/sbin/fm1-update"
STATE = library.RUNTIME / "fm1-update.json"     # where an update is up to, for the web page (and the box)
CACHE = library.RUNTIME / "fm1-update-newest.json"
LOG = Path.home() / ".cache" / "fm1-bridge" / "update.log"
CACHE_FOR = 600                 # s: GitHub answers 60 unauthenticated asks an hour
BACK_WITHIN = 120               # s: the Companion's status has to come back within this after the restart


def build():
    """"pocket" (a Pi Zero) or "studio", as install.sh tells them apart"""
    try:
        model = Path("/proc/device-tree/model").read_text().replace("\0", "")
    except OSError:
        model = ""
    return "pocket" if "Zero" in model else "studio"


def version(text):
    """"v2.12", "studio-v1.6", "STUDIO 1.6", "2.8.3" -> (2, 12) ...; None if there's no version in it"""
    m = re.search(r"(\d+(?:\.\d+)+)", text or "")
    return tuple(int(n) for n in m.group(1).split(".")) if m else None


def label(v):
    return "v" + ".".join(map(str, v)) if v else "?"


def installed(which=None):
    """the version installed here: the Pocket's device.POCKET_VERSION, the Studio's deskboot.VERSION"""
    if (which or build()) == "pocket":
        import device
        return version(device.POCKET_VERSION)
    import deskboot
    return version(deskboot.VERSION)


def newest_of(tags, which):
    """the newest release tag of this build among GitHub's tags -> (tag, version) or None"""
    pattern = re.compile(r"^v(\d+(?:\.\d+)+)$" if which == "pocket" else r"^studio-v(\d+(?:\.\d+)+)$")
    found = [(version(t), t) for t in tags if pattern.match(t)]
    if not found:
        return None
    v, tag = max(found)
    return tag, v


def newest(which=None, fresh=False):
    """the newest release for this box, asked of GitHub (kept CACHE_FOR s) -> (tag, version), or None, and an
    error message when GitHub couldn't be asked"""
    which = which or build()
    if not fresh:
        try:
            cached = json.loads(CACHE.read_text())
            if time.time() - cached["time"] < CACHE_FOR and cached["build"] == which:
                return (cached["tag"], tuple(cached["version"])) if cached["tag"] else None, None
        except (OSError, ValueError, KeyError, TypeError):
            pass
    try:
        request = urllib.request.Request(TAGS, headers={"Accept": "application/vnd.github+json",
                                                        "User-Agent": "fm1-companion"})
        with urllib.request.urlopen(request, timeout=10) as reply:
            tags = [t["name"] for t in json.load(reply)]
    except (OSError, ValueError, KeyError, TypeError) as e:
        return None, f"couldn't ask GitHub ({str(e)[:60]}): is the box online?"
    found = newest_of(tags, which)
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"time": time.time(), "build": which, "tag": found and found[0],
                                     "version": found and list(found[1])}))
    except OSError:
        pass
    return found, None


def read_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def write_state(state, message, **extra):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(dict(extra, state=state, message=message, time=time.time())))
    log(f"{state}: {message}")


def log(line):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line.rstrip() + "\n")
    except OSError:
        pass


def busy(status=None, job=None):
    """why an update can't start now (it restarts the Companion), or None"""
    status = library.read_status() if status is None else status
    if status and status.get("recording") is not None:
        return "a recording is running: stop it first"
    job = library.running() if job is None else job
    if job and job.get("job") != "update":
        return f"the {job.get('job', 'library')} job is still running"
    if read_state().get("state") in ("installing", "restarting"):
        return "an update is already running"
    return None


def check(fresh=False):
    """for the web page: the installed version, the newest, whether there's one to install, and how the last
    update went"""
    which = build()
    have = installed(which)
    found, error = newest(which, fresh)
    newer = bool(found and have and found[1] > have)
    return {"build": which, "installed": label(have), "newest": found and label(found[1]),
            "tag": found and found[0], "newer": newer, "error": error, "notes": NOTES,
            "helper": Path(HELPER).exists(), "last": read_state(), "busy": busy()}


def start():
    """from `library.py update` (once the box has its hold-press): run() as a unit of its own, so the
    Companion's restart doesn't stop it -> an error message, or None"""
    why = busy()
    if why:
        return why
    if not Path(HELPER).exists():
        return "this box needs one update over SSH first (install.sh) for the web app to update it"
    command = [sys.executable, str(Path(__file__).resolve()), "run"]
    if shutil.which("systemd-run"):
        command = ["systemd-run", "--user", "--collect", "--quiet", f"--unit=fm1-update-{int(time.time())}",
                   *command]
    write_state("installing", "Starting the update", started=time.time())
    try:
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        write_state("error", str(e))
        return str(e)
    return None


def helper(*args):
    """fm1-update as root (sudo, no password) -> (ok, its last line)"""
    try:
        done = subprocess.run(["sudo", "-n", HELPER, *args], capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    for line in (done.stdout + done.stderr).splitlines():
        log("  " + line)
    lines = [line for line in (done.stdout + done.stderr).splitlines() if line.strip()]
    return done.returncode == 0, lines[-1] if lines else ""


def came_back(within=BACK_WITHIN):
    """after the restart: the Companion running and writing its status again"""
    end = time.monotonic() + within
    time.sleep(5)
    while time.monotonic() < end:
        active = subprocess.run(["systemctl", "--user", "is-active", "fm1-bridge"], capture_output=True,
                                text=True).stdout.strip() == "active"
        status = library.read_status()
        if active and status and status.get("time", 0) > time.time() - 5:
            return True
        time.sleep(3)
    return False


def restart():
    subprocess.run(["systemctl", "--user", "restart", "fm1-bridge", "fm1-web"], capture_output=True, timeout=120)


def run():
    """the update itself (its own systemd unit): install, restart, check it came back, else go back"""
    which = build()
    have = installed(which)
    found, error = newest(which, fresh=True)
    if error or not found:
        write_state("error", error or "no release found for this box")
        return 1
    if have and found[1] <= have:
        write_state("done", f"Already up to date ({label(have)})")
        return 0
    why = busy()
    if why and "update is already" not in why:
        write_state("error", why)
        return 1
    write_state("installing", f"Installing {label(found[1])} (several minutes on a Pi Zero)",
                started=time.time(), to=label(found[1]), before=label(have))
    ok, last = helper()
    if not ok:
        write_state("error", f"The install didn't finish: {last[:100].rstrip('.')}. Nothing was restarted.",
                    before=label(have))
        return 1
    write_state("restarting", "Restarting the Companion", to=label(found[1]), before=label(have))
    restart()
    if came_back():
        write_state("done", f"Updated to {label(found[1])}", to=label(found[1]), before=label(have))
        return 0
    back, last = helper("--back")
    restart()
    write_state("error", f"{label(found[1])} didn't start, so {label(have)} was put back"
                + ("" if back else f" (that failed too: {last[:60]}; install over SSH)"), before=label(have))
    return 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["check"]:
        print(json.dumps(check(fresh=True), indent=1))
        return 0
    if argv == ["run"]:
        return run()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
