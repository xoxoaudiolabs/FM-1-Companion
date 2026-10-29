"""Tests for the web app's one-click update (update.py, config/fm1-update, install.sh's update mode, Library >
Software in web.py): the versions, picking the newest release for each box, not starting while the box is busy,
the update itself with fm1-update stood in for (installed, and put back when the new version doesn't start), and
the page asking the box. No network, no root.

  python tests/test_update.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-update-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"))
(TMP / "run").mkdir()

import library  # noqa: E402
import libui  # noqa: E402
import update  # noqa: E402
import web  # noqa: E402

TAGS = ["v2.12", "v2.11", "v2.8.3", "v2.9", "studio-v1.6", "studio-v1.10", "desk-v1.1", "v3.0-beta"]


def cached(tag, which="pocket"):
    """GitHub's answer, as if asked a moment ago (no network in the tests)"""
    update.CACHE.write_text(json.dumps({"time": time.time(), "build": which, "tag": tag,
                                        "version": list(update.version(tag)) if tag else None}))


def test_versions():
    assert update.version("v2.12") == (2, 12) and update.version("studio-v1.6") == (1, 6)
    assert update.version("STUDIO 1.6") == (1, 6) and update.version("2.8.3") == (2, 8, 3)
    assert update.version("nothing") is None and update.label((2, 12)) == "v2.12"
    assert update.version("v2.9") < update.version("v2.12")          # numbers, not text
    assert update.newest_of(TAGS, "pocket") == ("v2.12", (2, 12))
    assert update.newest_of(TAGS, "studio") == ("studio-v1.10", (1, 10))
    assert update.newest_of(["desk-v1.1"], "pocket") is None


def test_busy():
    assert update.busy(status={}, job={}) is None
    assert "recording" in update.busy(status={"recording": 12}, job={})
    assert "backup" in update.busy(status={}, job={"job": "backup"})
    assert update.busy(status={}, job={"job": "update"}) is None      # (the job that starts it)
    update.write_state("installing", "Installing v2.13")
    assert "already" in update.busy(status={}, job={})
    update.STATE.unlink()


def test_check():
    was = update.build, update.installed
    try:
        update.build, update.installed = lambda: "pocket", lambda which=None: (2, 11)
        cached("v2.12")
        info = update.check()
        assert info["installed"] == "v2.11" and info["newest"] == "v2.12" and info["newer"] and not info["error"]
        cached("v2.11")
        assert not update.check()["newer"]                             # up to date
    finally:
        update.build, update.installed = was


def test_run():
    """run(): installs with fm1-update, restarts, waits for the Companion; put back when it doesn't come up"""
    calls = []
    was = (update.build, update.installed, update.helper, update.restart, update.came_back, update.busy)
    try:
        update.build, update.installed = lambda: "pocket", lambda which=None: (2, 11)
        update.busy = lambda *a, **k: None
        update.helper = lambda *args: (calls.append(("helper",) + args), (True, "Installed v2.12"))[1]
        update.restart = lambda: calls.append(("restart",))
        update.newest = lambda which=None, fresh=False: (("v2.12", (2, 12)), None)
        update.came_back = lambda within=0: True
        assert update.run() == 0 and calls == [("helper",), ("restart",)]
        assert update.read_state()["state"] == "done" and "v2.12" in update.read_state()["message"]
        calls.clear()
        update.came_back = lambda within=0: False                      # the new version doesn't start
        assert update.run() == 1 and calls == [("helper",), ("restart",), ("helper", "--back"), ("restart",)]
        state = update.read_state()
        assert state["state"] == "error" and "v2.11 was put back" in state["message"]
        calls.clear()
        update.helper = lambda *args: (calls.append(("helper",) + args), (False, "No release for this box"))[1]
        assert update.run() == 1 and calls == [("helper",)]            # didn't install: nothing restarted
        assert "Nothing was restarted" in update.read_state()["message"]
        update.installed = lambda which=None: (2, 12)
        calls.clear()
        assert update.run() == 0 and calls == [] and "up to date" in update.read_state()["message"]
    finally:
        (update.build, update.installed, update.helper, update.restart, update.came_back, update.busy) = was
        update.newest = UPDATE_NEWEST


UPDATE_NEWEST = update.newest


def test_page_asks_the_box():
    """Library > Software: the page shows the versions; Update asks the box (hold press), and the box takes it"""
    server = web.ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    was = update.build, update.installed, update.HELPER
    helper = TMP / "fm1-update"
    try:
        update.build, update.installed = lambda: "pocket", lambda which=None: (2, 11)
        cached("v2.12")
        page = urllib.request.urlopen(base + "/", timeout=10).read()
        assert b"<h2>Software</h2>" in page and b"function software(" in page
        info = json.load(urllib.request.urlopen(base + "/api/update", timeout=10))
        assert info["installed"] == "v2.11" and info["newer"] and not info["helper"]

        def ask():
            request = urllib.request.Request(base + "/api/ask", data=json.dumps({"cmd": "update"}).encode())
            try:
                return json.load(urllib.request.urlopen(request, timeout=10))
            except urllib.error.HTTPError as e:
                return json.load(e)
        assert "over SSH first" in ask()["message"]                    # no fm1-update yet: one install by hand
        helper.write_text("#!/bin/sh\n")
        update.HELPER = str(helper)
        assert ask()["ok"] and library.take_request()["args"] == ["update"]
        cached("v2.11")
        assert "up to date" in ask()["message"]
    finally:
        update.build, update.installed, update.HELPER = was
        server.shutdown()
    assert {"update", "song-load", "dx7-send"} <= set(libui.WRITES)    # the box takes them from the page


def test_scripts():
    """fm1-update takes nothing but --back and installs only what install.sh can install as an update; install.sh
    has that update mode (root for the user, nothing asked) and gives the user's files back"""
    helper = (ROOT / "fm1-bt-bridge/config/fm1-update").read_text()
    assert "REPO=xoxoaudiolabs/FM-1-Companion" in helper and '*) echo "Usage: fm1-update [--back]"' in helper
    assert "grep -q FM1_UPDATE_USER" in helper and 'cp -a "$APP" "$WORK/previous"' in helper
    install = (ROOT / "fm1-bt-bridge/install.sh").read_text()
    for needed in ('if [ -z "${FM1_UPDATE_USER:-}" ]; then', "/usr/local/sbin/fm1-update\\n", 'chown -R "$USER:"',
                   '"$DIR/update.py"', 'if [ -z "$UPDATE" ] || ! all_installed; then',
                   "as_user systemctl --user daemon-reload"):
        assert needed in install, needed
    bash = shutil.which("bash")
    if bash:
        for script in ("fm1-bt-bridge/install.sh", "fm1-bt-bridge/config/fm1-update"):
            assert subprocess.run([bash, "-n", str(ROOT / script)]).returncode == 0, script


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
