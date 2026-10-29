#!/usr/bin/env python3
"""The FM-1 Companion's web page, http://fm1bridge.local over Wi-Fi or Ethernet.

Five tabs: Status (the box's live status, and the settings you change while playing: metronome, tempo,
clock, arp, chord, volume, audio rate, Start/Stop, recording, the Pocket's Studio link), MIDI (the routes as a
grid, each route's settings, the four presets), Library (backups, projects, songs, DX7 patches, samples,
firmware, software updates), Editor (the sample editor) and Recordings (listen in the browser, download, edit as
a sample, delete). It looks like xoxoaudiolabs.com.

The same page (PAGE) is XOXO Studio's web app too: its status says "box": "xoxo-studio", and the page then leaves
out the FM-1's parts and shows a Studio tab (XO-4, kits, the DJ decks and their music) from the fields it sends.

Settings go to the box as commands (library.queue_command; the box applies them like the joystick).
Anything that writes to the FM-1's data (restore, loads, firmware) is handed to the box and waits for a
confirmation there (hold the joystick press), never just a click on the network.

Phones can add it to the home screen as an app (manifest.webmanifest and icons/, the same as the demo on
xoxoaudiolabs.com/app/).

Python's standard library only. Port: $FM1_WEB_PORT (default 80; install.sh lets the user's services use it).
"""
import json
import os
import re
import shutil
import sys
import urllib.parse
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blemidi  # noqa: E402
import library  # noqa: E402
import update  # noqa: E402
import sampler  # noqa: E402
import sloop  # noqa: E402

MAX_UPLOAD = 50 * 1024 * 1024
EDITABLE = ("recordings", "samples")    # what the sample editor opens
TARGETS = {"working": "the working project", "A": "project A", "B": "project B", "C": "project C",
           "D": "project D"}
ICONS = Path(__file__).resolve().parent / "icons"    # the home-screen icons, for installing the page as an app
MANIFEST = {"name": "FM-1 Companion", "short_name": "FM-1", "start_url": "/", "scope": "/", "display": "standalone",
            "background_color": "#0b0b0b", "theme_color": "#0b0b0b",
            "icons": [{"src": "/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
                      {"src": "/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
                       "purpose": "maskable"}]}


def safe_path(folder, name):
    """a file in the library, or None: one of its folders, a plain name, the right kind of file"""
    if folder not in library.FOLDERS or not isinstance(name, str):
        return None
    base = Path(name).name
    if base != name or base.startswith(".") or Path(base).suffix.lower() not in library.SUFFIXES[folder]:
        return None
    return library.folder(folder) / base


def check_command(c):
    """a command for the box from the page -> the command to queue; ValueError says what's wrong"""
    if not isinstance(c, dict):
        raise ValueError("not a command")
    cmd = c.get("cmd")
    if cmd == "set":
        key, value = c.get("key"), c.get("value")
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        ok = {"metronome": isinstance(value, bool), "arp_on": isinstance(value, bool),
              "chord_on": isinstance(value, bool), "bpm": number and 30 <= value <= 300,
              "clock_mode": value in ("follow", "box"), "click": value in ("low", "mid", "high"),
              "audio_rate": value in (44100, 48000),
              "studio_link": isinstance(value, bool), "link_audio": isinstance(value, bool),   # the Pocket's Studio link
              "auto_backup": not isinstance(value, bool) and value in ("off", "boot", 2, 5, 10, 30),
              "output": value in ("both", "speaker", "phones"),
              "theme": isinstance(value, str) and len(value) <= 24,          # the box checks it against its list
              "volume": number and int(value) == value and 0 <= value <= 100}.get(key)
        if isinstance(key, str) and re.fullmatch(r"mix_(a|b|usb|u-[a-z0-9]+)", key):
            ok = number and int(value) == value and 0 <= value <= 200
        if isinstance(key, str) and re.fullmatch(r"input_u-[a-z0-9]+", key):
            ok = True
        if not ok:
            raise ValueError(f"bad setting {key!r}")
        return {"cmd": cmd, "key": key, "value": value}
    if cmd in ("transport", "record"):
        if c.get("value") not in ("start", "stop"):
            raise ValueError("start or stop")
        return {"cmd": cmd, "value": c["value"]}
    if cmd == "speaker":
        if c.get("value") not in ("connect", "disconnect"):
            raise ValueError("connect or disconnect")
        return {"cmd": cmd, "value": c["value"]}
    if cmd == "routes":
        return {"cmd": cmd, "routes": blemidi.clean_routes(c.get("routes"))}
    if cmd == "preset":
        name = c.get("name")
        if c.get("slot") not in ("1", "2", "3", "4") or c.get("action") not in ("load", "save", "clear") \
                or (name is not None and (not isinstance(name, str) or len(name) > 16)):
            raise ValueError("bad preset")
        return {"cmd": cmd, "slot": c["slot"], "action": c["action"], "name": name}
    raise ValueError(f"unknown command {cmd!r}")


def byte_range(header, size):
    """an HTTP Range header ("bytes=START-END", one range) -> (start, end inclusive), or None"""
    if not header or not header.startswith("bytes=") or "," in header:
        return None
    first, _, last = header[6:].partition("-")
    try:
        if first:
            start, end = int(first), int(last) if last else size - 1
        else:                                  # "bytes=-N": the last N bytes
            start, end = max(0, size - int(last)), size - 1
    except ValueError:
        return None
    return (start, min(end, size - 1)) if 0 <= start <= end and start < size else None


def check_upload(folder, path):
    """the uploaded file is what it claims to be; -> an error message, or None"""
    try:
        if folder == "firmware":
            import fm1_install
            fm1_install.load_package(str(path), False)
        elif folder == "backups":
            sloop.objects_of(sloop.load_json(path))
        elif folder == "projects":
            sloop.project_from(sloop.load_json(path))
        elif folder == "samples":
            import sampleio
            rate, samples = sampleio.read_any_wav(path)
            if not samples:
                return "no audio in that WAV"
    except SystemExit as e:                     # fm1_install reports a bad package this way
        return str(e) or "not a firmware package"
    except Exception as e:
        return str(e)[:120] or "not a valid file"
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "fm1-bridge"

    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text", "application/json")) else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def body(self, limit=1 << 20):
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise ValueError("too large")
        return self.rfile.read(length)

    def fail(self, message, code=400):
        self.send(code, {"ok": False, "message": message})

    # ---- GET
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(url.query))
        if url.path == "/":
            self.send(200, PAGE, "text/html")
        elif url.path == "/manifest.webmanifest":           # so a phone can add the page to its home screen
            self.send(200, json.dumps(MANIFEST).encode(), "application/manifest+json")
        elif url.path.startswith("/icons/"):
            path = ICONS / url.path[len("/icons/"):]
            if path.parent != ICONS or path.suffix != ".png" or not path.is_file():
                return self.fail("not found", 404)
            self.send(200, path.read_bytes(), "image/png")
        elif url.path == "/api/update":                    # Library > Software: installed, newest
            self.send(200, update.check(fresh=query.get("fresh") == "1"))
        elif url.path == "/api/library":
            self.send(200, library.listing())
        elif url.path == "/api/status":
            status = library.read_status()
            self.send(200, status if status else {"offline": True})
        elif url.path == "/api/state":
            state = library.read_state() or {}
            if state.get("state") == "running" and not library.running():
                state["state"] = "error"                       # it died without saying
            state["waiting"] = library.REQUEST.exists()
            self.send(200, state)
        elif url.path.startswith("/files/"):
            _, _, folder, name = url.path.split("/", 3)
            path = safe_path(folder, urllib.parse.unquote(name))
            if not path or not path.is_file():
                return self.fail("no such file", 404)
            ctype = {"samples": "audio/wav", "recordings": "audio/wav",
                     "firmware": "application/octet-stream"}.get(folder, "application/json")
            self.send_file(path, ctype, inline=query.get("inline") == "1")
        elif url.path == "/api/edit-info":            # what the sample editor opens a take or sample with
            folder = query.get("folder", "")
            path = safe_path(folder, query.get("file", "")) if folder in EDITABLE else None
            if not path or not path.is_file():
                return self.fail("no such file", 404)
            try:
                self.send(200, dict(sampler.info(path), level=library.sample_peak() / 32768))
            except (OSError, ValueError, EOFError, wave.Error) as e:
                self.fail(str(e))
        elif url.path == "/api/project":
            path = safe_path("backups", query.get("backup", ""))
            source = query.get("source", "")
            if not path or not path.is_file() or source not in TARGETS:
                return self.fail("no such project", 404)
            try:
                backup = sloop.load_json(path)
                data = sloop.project_from(backup, source)
            except sloop.SloopError as e:
                return self.fail(str(e))
            name = f"{path.stem}_{source}"
            body = json.dumps(sloop.project_file(data, name, backup.get("firmware"), f"{path.name}:{source}"))
            self.send(200, body.encode(), "application/json",
                      {"Content-Disposition": f'attachment; filename="{name}.json"'})
        else:
            self.fail("not found", 404)

    # ---- POST
    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        query = dict(urllib.parse.parse_qsl(url.query))
        try:
            if url.path == "/api/upload":
                return self.upload(query.get("folder", ""), query.get("name", ""))
            request = json.loads(self.body() or b"{}")
        except (ValueError, OSError) as e:
            return self.fail(str(e))
        if url.path == "/api/run":
            command = request.get("cmd")
            if command == "import-sd":
                try:
                    copied = library.import_sd()
                except OSError as e:
                    return self.fail(str(e))
                return self.send(200, {"ok": True, "message": f"{len(copied)} new file(s) from the SD card"})
            jobs = {"backup": ["backup"], "fetch-sloop": ["fetch", "sloop"], "fetch-clipper": ["fetch", "clipper"],
                    "song-backup": ["song-backup"]}
            if command not in jobs:
                return self.fail("unknown command")
            error = library.spawn(jobs[command])
            return self.send(200, {"ok": not error, "message": error or "started"})
        if url.path == "/api/ask":
            return self.ask(request)
        if url.path == "/api/save-sample":
            return self.save_sample(request)
        if url.path == "/api/command":
            try:
                command = check_command(request)
            except (ValueError, TypeError, AttributeError) as e:   # whatever arrives: a 400, never a crash
                return self.fail(str(e)[:120] or "bad command")
            if not library.read_status():
                return self.fail("the box isn't answering", 503)
            library.queue_command(command)
            return self.send(200, {"ok": True, "message": "sent"})
        if url.path == "/api/delete":
            path = safe_path(request.get("folder"), request.get("name"))
            if not path or not path.is_file():
                return self.fail("no such file", 404)
            if request.get("folder") == "recordings":
                library.delete_recording(path.name)                   # with its parts and clip counts
            else:
                path.unlink()
            return self.send(200, {"ok": True, "message": f"deleted {path.name}"})
        self.fail("not found", 404)

    def send_file(self, path, ctype, inline=False):
        """a file in pieces (a long recording is bigger than the Zero W's memory would like); a Range request
        gets just that part, so the browser's audio player can start at once and skip around"""
        size = path.stat().st_size
        part = byte_range(self.headers.get("Range"), size)
        start, end = part or (0, size - 1)
        self.send_response(206 if part else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        if part:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Disposition", f'{"inline" if inline else "attachment"}; filename="{path.name}"')
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(256 * 1024, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):   # the player stopped or skipped
                    return
                left -= len(chunk)

    def upload(self, folder, name):
        path = safe_path(folder, name) if folder != "recordings" else None
        if not path:
            try:                              # read what was sent first: an unread upload resets the connection,
                self.body(MAX_UPLOAD)          # and the browser shows that instead of the reason
            except (ValueError, OSError):
                pass
            return self.fail("that kind of file doesn't go there")
        data = self.body(MAX_UPLOAD)
        tmp = path.with_name("." + path.name + ".part")
        tmp.write_bytes(data)
        error = check_upload(folder, tmp)
        if error:
            tmp.unlink(missing_ok=True)
            return self.fail(f"{name}: {error}")
        tmp.replace(path)
        self.send(200, {"ok": True, "message": f"uploaded {path.name}"})

    def save_sample(self, r):
        """the sample editor's Save: a recording or a sample, edited, into the samples folder as a new file
        (nothing on the FM-1 changes, so no confirmation on the box; Load sample does that)"""
        folder = r.get("folder", "recordings")
        path = safe_path(folder, r.get("file")) if folder in EDITABLE else None
        if not path or not path.is_file():
            return self.fail("no such file")
        try:
            start, end = float(r["start"]), float(r["end"])
            if not 0 <= start < end:
                raise ValueError("the start must come before the end")
            fades = {k: min(2.0, max(0.0, float(r.get(k) or 0))) for k in ("fade_in", "fade_out")}
            note = sampler.parse_note(r.get("note"))
            name = str(r.get("name") or sampler.default_name(path))
            out = sampler.save(path, name, note, start, end, normalize=bool(r.get("normalize", True)),
                               reverse=bool(r.get("reverse")), **fades)
        except (KeyError, TypeError, ValueError, OSError, EOFError, wave.Error) as e:
            return self.fail(str(e)[:120] or "bad edit")
        self.send(200, {"ok": True, "message": f"Saved {out.name} to the samples", "name": out.name})

    def ask(self, r):
        """a write to the FM-1: handed to the box, which asks for a hold-press there"""
        command = r.get("cmd")
        if library.running():
            return self.fail("a library job is running")
        if command == "restore":
            path = safe_path("backups", r.get("file"))
            if not path or not path.is_file():
                return self.fail("no such backup")
            library.ask_box(["restore", str(path)], "Restore?", [path.name[:16], "replaces the FM-1's data"])
        elif command == "load-project":
            folder, target, source = r.get("folder"), r.get("target"), r.get("source") or "-"
            path = safe_path(folder if folder in ("backups", "projects") else "", r.get("file"))
            if not path or not path.is_file() or target not in TARGETS:
                return self.fail("pick a project and where it goes")
            library.ask_box(["load-project", str(path), source, target], "Load project?",
                            [f"{path.stem[:14]} {source if source != '-' else ''}".strip(), f"into {TARGETS[target]}"])
        elif command == "dx7-send":
            path, voice = safe_path("patches", r.get("file")), r.get("voice")
            if not path or not path.is_file() or not (voice is None or (isinstance(voice, int) and 1 <= voice <= 32)):
                return self.fail("pick a .syx and a voice")
            library.ask_box(["dx7-send", str(path)] + ([] if voice is None else [str(voice)]), "Send to FM-1?",
                            [path.stem[:16], "all 32 voices" if voice is None else f"voice {voice}"])
        elif command == "update":                 # the newest release: confirmed on the box, it restarts
            info = update.check()
            if info["busy"]:
                return self.fail(info["busy"])
            if not info["helper"]:
                return self.fail("this box needs one update over SSH first (install.sh)")
            if not info["newer"]:
                return self.fail(info["error"] or f"already up to date ({info['installed']})")
            library.ask_box(["update"], "Update?", [f"{info['installed']} > {info['newest']}", "restarts; files kept"])
        elif command == "load-song":
            path = safe_path("songs", r.get("file"))
            if not path or not path.is_file():
                return self.fail("no such song")
            library.ask_box(["song-load", str(path)], "Load song?", [path.stem[:16], "replaces sections A-D"])
        elif command == "load-sample":
            paths = [safe_path("samples", n) for n in r.get("files") or []]
            slot, name = r.get("slot"), (r.get("name") or "")[:8]
            if not paths or None in paths or not all(p.is_file() for p in paths) or slot not in (1, 2, 3, 4):
                return self.fail("pick WAV files and a slot")
            name = name or paths[0].stem[:8]
            library.ask_box(["load-sample", str(slot), name, *map(str, paths)], "Load sample?",
                            [f"{name} ({len(paths)} file{'s' if len(paths) > 1 else ''})", f"into USR{slot}"])
        elif command == "flash":
            path = safe_path("firmware", r.get("file"))
            if not path or not path.is_file():
                return self.fail("no such firmware")
            warning = "Experimental: see its README" if sloop.family(path.name) == "clipper" else "Keep the FM-1 plugged in"
            library.ask_box(["flash", str(path)], "Install?", [path.stem[:20], warning])
        else:
            return self.fail("unknown command")
        self.send(200, {"ok": True, "message": "Confirm on the box: hold the joystick press for 2 seconds"})


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0b0b0b">
<title>FM-1 Companion</title>
<link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/icons/icon-192.png"><link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="FM-1"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<style>
/* xoxoaudiolabs.com's look: near-black, off-white, one signal colour, square edges. The box is often offline, so the
   fonts are the site's (Anton, IBM Plex Mono) when the phone has them, else close ones it already has. */
:root{color-scheme:dark;--bg:#0b0b0b;--soft:#161615;--ink:#f2f0eb;--dim:#8a8780;--line:#2a2a28;--edge:#3d3d3a;--accent:#ff3b1f;--on:#f2f0eb;--bad:#ff3b1f;--rec:#ff3b1f;
  --display:Anton,Impact,Haettenschweiler,"Avenir Next Condensed","Arial Narrow",sans-serif-condensed,sans-serif;
  --mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,"Roboto Mono","Liberation Mono",monospace}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 var(--mono);-webkit-font-smoothing:antialiased;padding-bottom:calc(66px + env(safe-area-inset-bottom))}
h1,h2,.big,.recbtn{font-family:var(--display);font-weight:700;font-synthesis:none;text-transform:uppercase;letter-spacing:.02em}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding-top:env(safe-area-inset-top)}
header .in{max-width:1040px;margin:0 auto;display:flex;align-items:center;gap:8px;padding:12px 16px}
header h1{font-size:24px;line-height:1;margin:0;flex:1;white-space:nowrap}header h1 i{font-style:normal;color:var(--dim);padding:0 .08em}
.pill{font:600 11px/1 var(--mono);text-transform:uppercase;letter-spacing:.14em;padding:6px 8px;border:1px solid var(--edge);color:var(--dim);white-space:nowrap}
.pill.live{color:var(--ink);border-color:var(--ink)}.pill.live:before{content:"";display:inline-block;width:7px;height:7px;background:var(--accent);margin-right:7px;vertical-align:0}
.pill.off{color:var(--bad);border-color:var(--bad)}.pill.rec{background:var(--rec);border-color:var(--rec);color:var(--bg);animation:blink 1.2s steps(2) infinite}
@keyframes blink{50%{opacity:.55}}
main{max-width:1040px;margin:0 auto;padding:20px 16px 24px}
.tab{display:none}.tab.shown{display:block}
nav{position:fixed;bottom:0;left:0;right:0;z-index:6;display:flex;justify-content:center;background:var(--bg);border-top:1px solid var(--line);padding-bottom:env(safe-area-inset-bottom)}
nav button{flex:1;max-width:200px;min-height:0;border:0;background:none;color:var(--dim);padding:9px 2px 8px;font:600 10px/1.2 var(--mono);text-transform:uppercase;letter-spacing:.12em}
nav button:hover{color:var(--ink)}nav button.shown{background:var(--ink);color:var(--bg)}nav svg{display:block;margin:0 auto 4px;width:22px;height:22px}
section{border-top:2px solid var(--ink);padding:12px 0 22px;margin:0;scroll-margin-top:64px}
h2{font-size:24px;line-height:1;margin:2px 0 14px}
.label,.k{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.14em;color:var(--dim)}
.group{margin:28px 0 10px}.group:first-child{margin-top:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:0 32px}
.line{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:46px;border-top:1px solid var(--line);padding:6px 0}
.line:first-of-type{border-top:0}.line .v{font-weight:600;text-align:right}
button,select,input[type=text],input[type=number]{font:inherit;font-size:13px;border-radius:0;border:1px solid var(--edge);background:var(--soft);color:var(--ink);padding:8px 12px;min-height:40px}
button{cursor:pointer;background:transparent;font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.08em}
button:hover{border-color:var(--ink)}button.primary{background:var(--ink);border-color:var(--ink);color:var(--bg)}button.primary:hover{background:var(--accent);border-color:var(--accent)}
button.danger{color:var(--bad)}button.danger:hover{border-color:var(--bad)}button:disabled{opacity:.4;cursor:default}
select{-webkit-appearance:none;appearance:none;padding-right:30px;background:var(--soft) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0h10L5 6z' fill='%238a8780'/%3E%3C/svg%3E") no-repeat right 10px center}
input[type=number]{width:76px;text-align:center}input[type=checkbox]{accent-color:var(--accent)}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.seg{display:inline-flex;border:1px solid var(--edge)}
.seg button{border:0;border-left:1px solid var(--edge);min-width:64px}.seg button:first-child{border-left:0}.seg button.on{background:var(--ink);color:var(--bg)}
.sw{position:relative;width:50px;height:28px;flex:none}.sw input{opacity:0;width:0;height:0}
.sw span{position:absolute;inset:0;background:var(--soft);border:1px solid var(--edge);transition:.15s;cursor:pointer}
.sw span:before{content:"";position:absolute;width:20px;height:20px;left:3px;top:3px;background:var(--dim);transition:.15s}
.sw input:checked+span{background:var(--ink);border-color:var(--ink)}.sw input:checked+span:before{background:var(--bg);transform:translateX(21px)}
.sw input:focus-visible+span{outline:2px solid var(--accent);outline-offset:2px}
.big{font-size:76px;line-height:.9}.big .unit{font-size:22px;color:var(--dim);margin-left:8px}
.dim{color:var(--dim)}.small{font-size:12px}
input[type=range]{-webkit-appearance:none;appearance:none;width:100%;height:32px;background:transparent;margin:0}
input[type=range]::-webkit-slider-runnable-track{height:4px;background:var(--line)}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:14px;height:24px;margin-top:-10px;background:var(--ink);border:0}
input[type=range]::-moz-range-track{height:4px;background:var(--line)}input[type=range]::-moz-range-progress{height:4px;background:var(--dim)}
input[type=range]::-moz-range-thumb{width:14px;height:24px;background:var(--ink);border:0;border-radius:0}
input[type=range]:disabled{opacity:.4}
.recbtn{width:100%;font-size:26px;line-height:1;padding:18px;border:2px solid var(--rec);color:var(--rec);background:transparent}
.recbtn:hover{border-color:var(--rec);background:#ff3b1f1a}.recbtn.on{background:var(--rec);color:var(--bg)}
.item{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;justify-content:space-between;padding:12px 0;border-top:1px solid var(--line)}
.item:first-of-type{border-top:0}.name{font-weight:600;word-break:break-word}.meta{color:var(--dim);font-size:12px}
.empty{color:var(--dim);margin:4px 0}.bar{height:4px;background:var(--line);overflow:hidden;margin-top:10px}
.bar div{height:100%;background:var(--accent);width:0;transition:width .3s}
.job{border:1px solid var(--edge);padding:10px 12px}
audio{width:100%;height:40px;margin-top:8px}
label.file{display:inline-block}label.file input{display:none}
.patgrid{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:4px;margin:6px 0 10px}.patgrid button{min-width:0;padding:10px 0}
.patgrid button.on{background:var(--ink);border-color:var(--ink);color:var(--bg)}.patgrid button.queued{outline:2px solid var(--accent);outline-offset:2px}
.patgrid button.empty{color:var(--dim);border-color:var(--line)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 20px}.chips button{min-height:34px;padding:6px 10px;font-size:11px}
.chips b{color:var(--dim);font-weight:600;margin-left:6px}
.mxwrap{overflow-x:auto;margin:0 -16px;padding:0 16px 4px}
table.mx{border-collapse:collapse}table.mx th{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:var(--dim);text-align:left;padding:6px;white-space:nowrap}
table.mx td{padding:3px}table.mx td button{width:100%;min-width:76px}table.mx td.self{color:var(--line);text-align:center}
table.mx td button.on{background:var(--ink);border-color:var(--ink);color:var(--bg)}
table.mx td button.sel{outline:2px solid var(--accent);outline-offset:2px}
.midi{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:0 32px}.midi .wide{grid-column:1/-1}
.chgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}.chgrid label{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:.1em}
.chgrid select{width:100%;padding:6px 26px 6px 8px;min-height:36px}
#toast{position:fixed;left:50%;bottom:calc(78px + env(safe-area-inset-bottom));transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:10px 16px;font-size:13px;font-weight:600;opacity:0;transition:opacity .2s;pointer-events:none;max-width:90%;text-align:center}
#toast.shown{opacity:1}
.banner{border:1px solid var(--bad);padding:10px 12px;margin:0 0 16px}
#sed-wave{width:100%;height:200px;display:block;background:var(--soft);border:1px solid var(--line);touch-action:none;cursor:ew-resize}
.sedgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px 12px;margin:14px 0}
.sedgrid label{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:var(--dim);display:flex;flex-direction:column;gap:4px}
.sedgrid input,.sedgrid select{width:100%;text-transform:none;letter-spacing:0;font-weight:400}.warn{color:var(--bad)}
details summary{cursor:pointer}
@media (max-width:899px){.midi{grid-template-columns:minmax(0,1fr)}}
@media (max-width:420px){header h1{font-size:20px}.big{font-size:64px}nav button{letter-spacing:.06em}}
</style></head><body>
<header><div class="in"><h1 id="title">FM-1<i>//</i>Companion</h1><span id="recpill" class="pill rec" hidden>REC</span><span id="pill" class="pill">…</span></div></header>
<main>

<!-- ======================= STATUS ======================= -->
<div class="tab" id="tab-status">
<div id="offline" class="banner" hidden>The box isn't answering: it may be starting, or its bridge stopped. Settings will work again when it's back.</div>
<div class="grid">
<section><h2>Clock</h2>
  <div class="row" style="justify-content:space-between;align-items:flex-end;margin-bottom:8px"><div><div class="big"><span id="s-bpm">–</span><span class="unit">BPM</span></div><div class="dim small" id="s-src" style="margin-top:6px"></div></div>
    <div class="seg" id="s-mode"><button data-v="follow">Follow</button><button data-v="box">Box</button></div></div>
  <div class="line"><span class="k">Box tempo</span><div class="row"><button onclick="bump(-1)" aria-label="Slower">−</button><input type="number" id="s-tempo" min="30" max="300"><button onclick="bump(1)" aria-label="Faster">+</button></div></div>
  <div class="line"><span class="k">Transport</span><div class="row"><button class="primary" onclick="cmd({cmd:'transport',value:'start'})">▶ Start</button><button onclick="cmd({cmd:'transport',value:'stop'})">■ Stop</button></div></div>
  <div class="line"><span class="k">Metronome</span><label class="sw"><input type="checkbox" id="s-metro"><span></span></label></div>
  <div class="line"><span class="k">Click level</span><div class="seg" id="s-click"><button data-v="low">Low</button><button data-v="mid">Mid</button><button data-v="high">High</button></div></div>
</section>
<section><h2>Audio</h2>
  <div class="line" id="s-batline" hidden><span class="k">Battery</span><span class="v" id="s-bat">–</span></div>
  <div class="line" id="s-fm1line"><span class="k">FM-1</span><span class="v" id="s-fm1">–</span></div>
  <div class="line" id="s-srcline" hidden><span class="k">Sources</span><span class="v" id="s-src-in">–</span></div>
  <div class="line"><span class="k">Speaker</span><div class="row" style="justify-content:flex-end"><span class="v" id="s-spk">–</span><button id="s-spkbtn" onclick="speaker()" hidden>Connect</button></div></div>
  <div class="line" id="s-pocketline" hidden><span class="k">Pocket</span><span class="v" id="s-pocket">–</span></div>
  <div class="line" id="s-outline" hidden><span class="k">Output</span><div class="seg" id="s-out"><button data-v="speaker">Speaker</button><button data-v="phones">Jack</button><button data-v="both">Both</button></div></div>
  <div class="line" style="display:block"><div class="row" style="justify-content:space-between"><span class="k">Volume</span><b id="s-volv">–</b></div>
    <input type="range" id="s-vol" min="0" max="100" step="2" aria-label="Volume"></div>
  <div id="s-mix"></div>
  <div class="line"><span class="k">Audio rate</span><div class="seg" id="s-rate"><button data-v="44100">44.1</button><button data-v="48000">48 kHz</button></div></div>
</section>
<section id="s-link" hidden><h2>Studio link</h2>
  <div class="line"><span class="k">Link</span><label class="sw"><input type="checkbox" id="s-lon"><span></span></label></div>
  <div class="line"><span class="k">Studio</span><span class="v" id="s-lstudio">–</span></div>
  <div class="line"><span class="k">Link audio</span><label class="sw"><input type="checkbox" id="s-laudio"><span></span></label></div>
  <div class="line"><span class="k">Audio</span><span class="v" id="s-lsend">–</span></div>
  <p class="dim small" style="margin:6px 0 0">Links this Pocket to an XOXO Studio on the same network: its MIDI, and its sound when Link audio is on.</p>
</section>
<section><h2>Record</h2>
  <button class="recbtn" id="s-rec" onclick="toggleRec()">● Record</button>
  <p class="dim small" style="margin:10px 0 0" id="s-recnote">Records the FM-1 on the box (a WAV at the FM-1's own rate). Takes are in the Recordings tab.</p>
</section>
<section><h2>Keyboard</h2>
  <div class="line"><span><span class="k">Arp</span> <span class="dim small" id="s-arpd"></span></span><label class="sw"><input type="checkbox" id="s-arp"><span></span></label></div>
  <div class="line"><span><span class="k">Chord</span> <span class="dim small" id="s-chordd"></span></span><label class="sw"><input type="checkbox" id="s-chord"><span></span></label></div>
  <div class="line"><span class="k">MIDI device</span><span class="v" id="s-midi">–</span></div>
  <div class="line"><span class="k">USB keys</span><span class="v" id="s-usbkeys">–</span></div>
  <p class="dim small" style="margin:6px 0 0" id="s-kbnote">Pattern, rate and chord type: MIDI tab, Bluetooth → FM-1.</p>
</section>
<section id="s-box" hidden><h2>Box</h2>
  <div class="line" id="s-themeline" hidden><span class="k">Screen theme</span><select id="s-theme" onchange="set('theme', this.value)"></select></div>
  <div class="line" id="s-autoline"><span class="k">Auto backup</span><select id="s-auto" onchange="set('auto_backup', /^\d+$/.test(this.value) ? +this.value : this.value)">
    <option value="off">off</option><option value="boot">at start</option><option value="2">every 2 min</option><option value="5">every 5 min</option><option value="10">every 10 min</option><option value="30">every 30 min</option></select></div>
  <p class="dim small" style="margin:6px 0 0">Auto backups go to Library → Backups.</p>
</section>
</div>
</div>

<!-- ======================= STUDIO ======================= -->
<div class="tab" id="tab-studio">
<div class="grid">
<section><h2>XO-4</h2>
  <div class="line"><span class="k">Pattern</span><span class="v" id="x-state">–</span></div>
  <div class="patgrid" id="x-pats"></div>
  <div class="line"><span class="k">Transport</span><button class="primary" id="x-play" onclick="cmd({cmd:'xo4',action:'play'})">▶ Play</button></div>
  <div class="line"><span><span class="k">MIDI in</span><br><span class="dim small">notes from the MIDI routes play its pads</span></span><label class="sw"><input type="checkbox" id="x-midiin"><span></span></label></div>
  <div class="line"><span class="k">SYN 1 sound</span><select id="x-s1" onchange="xo4Sound(1, this.value)"></select></div>
  <div class="line"><span class="k">SYN 2 sound</span><select id="x-s2" onchange="xo4Sound(2, this.value)"></select></div>
  <p class="dim small" style="margin:6px 0 0">While it plays, a pattern starts on the next bar. Steps are made on the Studio's screen.</p>
</section>
<section><h2>Kit</h2>
  <div class="line"><span class="k">Loaded</span><span class="v" id="k-cur">–</span></div>
  <div id="k-list"></div>
</section>
<section><h2>DJ decks</h2><div id="d-decks"></div></section>
<section><h2>DJ music</h2><p class="meta" style="margin:-6px 0 6px">The Studio DJ Music folder. A track added here shows on the DECKS screen; press SCAN there for its tempo and key.</p>
<div id="music"></div>
<div class="row" style="margin-top:8px"><label class="file"><input type="file" accept=".mp3,.flac,.wav,.aif,.aiff,.ogg,.m4a" multiple onchange="upload('music',this)"><button onclick="this.previousElementSibling.click()">Add music…</button></label></div></section>
</div>
</div>

<!-- ======================= MIDI ======================= -->
<div class="tab" id="tab-midi">
<div class="midi">
<section><h2>Routes</h2>
  <p class="dim small" style="margin:-6px 0 12px">Filled: the route passes MIDI. Tap a route to edit it; tap it again to switch it on or off.</p>
  <div class="mxwrap"><table class="mx" id="mx"></table></div>
</section>
<section id="editor"><h2 id="ed-title">Route</h2><div id="ed"></div><p class="dim small" id="ed-saved" style="margin:8px 0 0"></p></section>
<section class="wide"><h2>Presets</h2><div id="presets"></div></section>
</div>
</div>

<!-- ======================= LIBRARY ======================= -->
<div class="tab" id="tab-library">
<div class="chips" id="libnav"><button onclick="jump('lib-backups')">Backups<b id="n-backups"></b></button><button onclick="jump('lib-projects')">Projects<b id="n-projects"></b></button><button onclick="jump('lib-songs')">Songs<b id="n-songs"></b></button><button onclick="jump('lib-patches')">DX7<b id="n-patches"></b></button><button onclick="jump('lib-samples')">Samples<b id="n-samples"></b></button><button onclick="jump('lib-firmware')">Firmware<b id="n-firmware"></b></button><button onclick="jump('lib-software')">Software</button></div>
<section id="lib-now"><h2>Now</h2><div class="job"><div id="job" class="meta">Nothing running.</div><div class="bar" id="barwrap" hidden><div id="bar"></div></div></div>
<div class="row" style="margin-top:12px"><button class="primary" onclick="run('backup')">Back up now</button>
<button onclick="run('fetch-sloop')">Get SLOOP update</button><button onclick="run('fetch-clipper')" title="isod89's synthesizer firmware, experimental">Get Clipper (exp.)</button><button onclick="run('import-sd')">Import SD card</button></div>
<p class="meta" style="margin:12px 0 0">Anything that writes to the FM-1 asks for a confirmation on the box: hold the joystick press for 2 seconds. Restores, projects, songs and firmware back the FM-1 up first; a sample only replaces its slot.</p></section>

<p class="label group" id="g-fm1">On the FM-1</p>
<section id="lib-backups"><h2>Backups</h2><div id="backups"></div>
<div class="row" style="margin-top:8px"><label class="file"><input type="file" accept=".json" onchange="upload('backups',this)"><button onclick="this.previousElementSibling.click()">Upload a backup…</button></label></div></section>

<section id="lib-projects"><h2>Projects</h2><p class="meta" style="margin:0 0 6px">Load a project into the FM-1, from a project file or from any backup.</p>
<div id="projects"></div>
<div class="row" style="margin-top:8px"><label class="file"><input type="file" accept=".json" onchange="upload('projects',this)"><button onclick="this.previousElementSibling.click()">Upload a project…</button></label></div></section>

<section id="lib-songs"><h2>Songs</h2><p class="meta" style="margin:0 0 6px">A SLOOP song (2.5+): its four sections (projects A-D) and the song order, in one file. Loading one replaces sections A-D and the song order; the FM-1's other settings stay as they are.</p>
<div id="songs"></div>
<div class="row" style="margin-top:8px"><button class="primary" onclick="run('song-backup')">Back up song</button><label class="file"><input type="file" accept=".json" onchange="upload('songs',this)"><button onclick="this.previousElementSibling.click()">Upload a song…</button></label></div></section>

<section id="lib-patches"><h2>DX7 patches</h2><p class="meta" style="margin:0 0 6px">Yamaha DX7 banks (.syx, 32 voices) and single voices, for FM-1 firmwares that take them (by others' research: M-VAVE's own, and Baud Girl's FM-1+VA before FM-1_079): a whole bank (the FM-1 asks where it goes) or one voice. Not for SLOOP or Clipper, which have their own patches. <i>Not tried on an FM-1 yet.</i></p>
<div id="patches"></div>
<div class="row" style="margin-top:8px"><label class="file"><input type="file" accept=".syx" onchange="upload('patches',this)"><button onclick="this.previousElementSibling.click()">Upload a .syx…</button></label></div></section>

<section id="lib-samples"><h2>Samples</h2><p class="meta" style="margin:0 0 6px" id="smp-pads" hidden>WAVs for the pads (on the box: PADS → EDIT → a pad → SAMPLE). A note in the name, e.g. <i>bass_C2.wav</i>, is its root note.</p><p class="meta" style="margin:0 0 6px" id="smp-fm1">Tick one or more WAVs (each becomes a key zone, root note from the name, e.g. <i>bass_C2.wav</i>), then load them into a slot. A slot holds about 7 seconds.</p>
<div id="samples"></div>
<div class="row" style="margin-top:8px"><label class="file"><input type="file" accept=".wav" multiple onchange="upload('samples',this)"><button onclick="this.previousElementSibling.click()">Upload WAVs…</button></label>
<span class="row fm1only"><input type="text" id="sname" placeholder="name (8 letters)" maxlength="8" size="12"><select id="sslot"><option value="1">USR1</option><option value="2">USR2</option><option value="3">USR3</option><option value="4">USR4</option></select>
<button class="primary" onclick="loadSamples()">Load ticked into slot</button></span><button id="smp-sd" onclick="run('import-sd')" hidden>Import SD card</button></div></section>

<p class="label group" id="g-fw">Firmware and software</p>
<section id="lib-firmware"><h2>Firmware</h2><p class="meta" style="margin:0 0 6px">SLOOP (groovebox) and Clipper (synthesizer, experimental) are both isod89's. Backups, projects and samples belong to the firmware they came from: a SLOOP backup can't be restored onto Clipper, and Clipper has wavetables instead of sample slots.</p><div id="firmware"></div>
<div class="row" style="margin-top:8px"><label class="file"><input type="file" accept=".fwsc" onchange="upload('firmware',this)"><button onclick="this.previousElementSibling.click()">Upload a .fwsc…</button></label></div></section>
<section id="lib-software"><h2>Software</h2><p class="meta" style="margin:0 0 6px">Updates come from the project's GitHub. Everything you've saved stays as it is: settings, pairings, backups, projects, songs, samples, recordings. The box asks you to confirm, then installs (several minutes on a Pi Zero) and restarts; if the new version doesn't start, it goes back to this one.</p>
<div id="software" class="job meta">Checking…</div>
<div class="row" style="margin-top:12px"><button onclick="software(true)">Check again</button><button class="primary" id="sw-update" onclick="ask({cmd:'update'})" hidden>Update…</button><a id="sw-notes" target="_blank" rel="noopener" hidden><button>What's new</button></a></div></section>
</div>

<!-- ======================= RECORDINGS ======================= -->
<div class="tab" id="tab-recordings">
<section><h2>Record</h2><button class="recbtn" id="r-rec" onclick="toggleRec()">● Record</button></section>
<section><h2>Takes</h2><p class="meta" style="margin:-6px 0 6px">Listen here, download, or <i>edit as sample</i>: trim it, fade it, set its note, and save it to the samples.</p>
<div id="recordings"></div></section>
</div>

<!-- ======================= SAMPLE EDITOR ======================= -->
<div class="tab" id="tab-editor">
<section><h2>Edit</h2><p class="meta" style="margin:-6px 0 10px">Make a sample from a recording, or edit one that's already in the samples. Saving always makes a new file.</p>
  <div class="row"><select id="sed-pick" style="flex:1;min-width:0"></select><button class="primary" onclick="sedPicked()">Open</button></div></section>
<section id="sed" hidden><h2>Sample editor <span class="dim small" id="sed-take" style="font-family:var(--mono);text-transform:none;letter-spacing:0"></span></h2>
  <canvas id="sed-wave"></canvas>
  <div class="row" style="margin-top:8px"><span class="k">Zoom</span><input type="range" id="sed-zoom" min="1" max="40" value="1" style="flex:1" aria-label="Zoom"></div>
  <div class="sedgrid">
    <label>Start (s)<input type="number" id="sed-start" step="0.01" min="0"></label>
    <label>End (s)<input type="number" id="sed-end" step="0.01" min="0"></label>
    <label>Fade in (ms)<input type="number" id="sed-fi" step="10" min="0" max="2000" value="0"></label>
    <label>Fade out (ms)<input type="number" id="sed-fo" step="10" min="0" max="2000" value="10"></label>
    <label>Root note<select id="sed-note"></select></label>
    <label>Name<input type="text" id="sed-name" maxlength="24"></label>
  </div>
  <div class="row"><label class="row small"><input type="checkbox" id="sed-norm" checked style="width:20px;height:20px"> Normalize to the Sample level</label>
    <label class="row small"><input type="checkbox" id="sed-rev" style="width:20px;height:20px"> Reverse</label></div>
  <p class="small" id="sed-len" style="margin:10px 0"></p>
  <div class="row"><button onclick="sedPlay()">▶ Play selection</button><button class="primary" onclick="sedSave()">Save to samples</button><button onclick="sedClose()">Close</button></div>
  <p class="dim small" style="margin:10px 0 0">Drag on the waveform to move the nearer marker. Saved samples go to Library → Samples, ready to load into a slot (on the box: Sloop → Load sample).</p>
</section>
</div>
</main>

<nav>
<button data-tab="status"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>Status</button>
<button data-tab="studio" hidden><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>Studio</button>
<button data-tab="midi"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="14"/><path d="M8 5v8M12 5v8M16 5v8"/></svg>MIDI</button>
<button data-tab="library"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h6v16H4zM14 4l6 2-4 14-6-2z"/></svg>Library</button>
<button data-tab="editor"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h2M7 8v8M11 5v14M15 9v6M19 11v2"/></svg>Editor</button>
<button data-tab="recordings"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3" fill="currentColor"/></svg>Recordings</button>
</nav>
<div id="toast"></div>
<script>
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const q = (s) => esc(JSON.stringify(s));            // a JS string literal inside an onclick attribute
const when = (t) => new Date(t * 1000).toLocaleString([], {month:"short", day:"numeric", hour:"2-digit", minute:"2-digit"});
const fw = (s) => esc((s || "?").split(" ").pop());
const mins = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
let lib = {backups:[], projects:[], samples:[], firmware:[], recordings:[], songs:[], patches:[]};
let st = null;                                     // the box's status
let tab = "status";
// one page for every box: the FM-1 Companion (Pocket, Studio) and XOXO Studio, which has no FM-1 ("box" in its status)
const xoxo = () => !!st && st.box === "xoxo-studio";
let shownBox = null;
function applyBox() {
  const x = xoxo(), studio = !!(st && !st.offline && (st.xo4 || st.kits || st.decks));
  const key = `${x}${studio}`;
  if (key === shownBox) return;
  shownBox = key;
  $("title").innerHTML = x ? "XOXO<i>//</i>Studio" : "FM-1<i>//</i>Companion";
  document.title = x ? "XOXO Studio" : "FM-1 Companion";
  document.querySelector('nav button[data-tab="studio"]').hidden = !studio;
  for (const id of ["libnav", "lib-now", "g-fm1", "lib-backups", "lib-projects", "lib-songs", "lib-patches", "g-fw", "lib-firmware", "lib-software", "smp-fm1"]) $(id).hidden = x;
  for (const id of ["smp-pads", "smp-sd"]) $(id).hidden = !x;
  document.querySelectorAll(".fm1only").forEach((e) => e.hidden = x);
  $("s-recnote").textContent = x ? "Records what the Studio plays (a WAV). Takes are in the Recordings tab."
    : "Records the FM-1 on the box (a WAV at the FM-1's own rate). Takes are in the Recordings tab.";
  $("s-kbnote").textContent = x ? "Arp and Chord switch every keyboard route to your MIDI gear; pattern, rate and chord type: MIDI tab, on a route."
    : "Pattern, rate and chord type: MIDI tab, Bluetooth → FM-1.";
  if (tab === "studio" && !studio) show("status");
  if (tab === "library") refresh();
}

// ---------------------------------------------------------------- basics
let toastTimer;
function toast(msg, ok = true) { const t = $("toast"); t.textContent = msg; t.style.color = ok ? "" : "var(--bad)"; t.classList.add("shown"); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("shown"), 2600); }
async function post(url, body, quiet) {
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)}).catch(() => null);
  const j = r ? await r.json().catch(() => ({ok:false, message:r.statusText})) : {ok:false, message:"no connection"};
  if (!quiet || !j.ok) toast(j.message, j.ok);
  return j;
}
const cmd = (c, quiet = true) => post("/api/command", c, quiet).then((j) => { setTimeout(status, 450); return j; });
const set = (key, value) => cmd({cmd:"set", key, value});
function show(name) {
  tab = name; location.hash = name;
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("shown", t.id === "tab-" + name));
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("shown", b.dataset.tab === name));
  if (name === "library" || name === "recordings" || name === "editor" || name === "studio") refresh();
  if (name === "midi") { renderMatrix(); renderEditor(); renderPresets(); }
  status();
}
document.querySelectorAll("nav button").forEach((b) => b.onclick = () => show(b.dataset.tab));
function seg(id, value, onpick) {                  // a segmented control: highlight and click handler
  const el = $(id);
  el.querySelectorAll("button").forEach((b) => { b.classList.toggle("on", String(value) === b.dataset.v); b.onclick = () => onpick(b.dataset.v); });
}

// ---------------------------------------------------------------- status tab
let volTimer, tempoTimer, editingUntil = 0;
function renderStatus() {
  const off = !st || st.offline;
  $("offline").hidden = !off;
  $("pill").textContent = off ? "offline" : st.live ? "LIVE" : "idle";
  $("pill").className = "pill " + (off ? "off" : st.live ? "live" : "");
  const rec = !off && st.recording != null;
  $("recpill").hidden = !rec; if (rec) $("recpill").textContent = "REC " + mins(st.recording);
  for (const id of ["s-rec", "r-rec"]) { $(id).classList.toggle("on", rec); $(id).textContent = rec ? `■ Stop recording  ${mins(st.recording)}` : "● Record"; $(id).disabled = off; }
  if (off) return;
  const s = st.settings;
  applyBox();
  $("s-fm1line").hidden = xoxo(); $("s-fm1").textContent = st.fm1 || "not found";
  $("s-srcline").hidden = !st.sources; $("s-src-in").textContent = (st.sources || []).join(", ") || "none";
  $("s-pocketline").hidden = !st.pocket;
  if (st.pocket) $("s-pocket").textContent = "linked over " + (st.pocket === "cable" ? "the cable" : "the network") + " · POCKET in the mixer";
  const bat = !st.offline && st.battery;
  $("s-batline").hidden = !bat;
  if (bat) $("s-bat").textContent = `${bat.percent}%` + (bat.plugged ? " · charging" : "");
  $("s-spk").textContent = (st.speaker || (st.connecting ? "connecting…" : (st.speaker_name ? st.speaker_name + " (off)" : "none")))
    + (st.speaker && st.speaker_battery != null ? ` · battery ${st.speaker_battery}%` : "");
  if (Date.now() > editingUntil) { if (st.volume != null) $("s-vol").value = st.volume; $("s-tempo").value = s.bpm; }
  $("s-volv").textContent = st.volume != null ? st.volume + "%" : "–"; $("s-vol").disabled = st.volume == null;
  renderMixer(st);
  seg("s-rate", s.audio_rate, (v) => set("audio_rate", +v));
  const c = st.clock;
  $("s-bpm").textContent = c ? c.bpm : "–";
  $("s-src").textContent = c ? `${c.playing ? "▶ playing" : "stopped"} · ${c.source === "box" ? "box clock" : "from " + c.source}` : (s.clock_mode === "follow" ? "following: no clock coming in" : "");
  seg("s-mode", s.clock_mode, (v) => set("clock_mode", v));
  $("s-metro").checked = s.metronome; $("s-metro").onchange = (e) => set("metronome", e.target.checked);
  seg("s-click", s.click, (v) => set("click", v));
  $("s-arp").checked = s.arp_on; $("s-arp").onchange = (e) => set("arp_on", e.target.checked);
  $("s-chord").checked = s.chord_on; $("s-chord").onchange = (e) => set("chord_on", e.target.checked);
  $("s-arpd").textContent = `${s.arp} ${s.arp_rate}`; $("s-chordd").textContent = s.chord;
  $("s-midi").textContent = st.midi.error ? "Bluetooth error" : !st.midi.enabled ? "off" : (st.midi.peer || "waiting");
  $("s-usbkeys").textContent = (st.midi.controllers || []).join(", ") || "none";
  renderLink(st.link);
  $("s-spkbtn").hidden = !st.speaker_saved; $("s-spkbtn").textContent = st.speaker || st.connecting ? "Disconnect" : "Connect";
  $("s-outline").hidden = !st.jack; if (st.jack) seg("s-out", s.output, (v) => set("output", v));
  const th = st.theme; $("s-themeline").hidden = !th;
  if (th && document.activeElement !== $("s-theme")) $("s-theme").innerHTML = opt(th.choices, th.value, (x) => x === "follow" ? "FM-1 A" : x);
  $("s-autoline").hidden = s.auto_backup == null; $("s-box").hidden = !th && s.auto_backup == null;   // a box from before these
  if (s.auto_backup != null && document.activeElement !== $("s-auto")) $("s-auto").value = String(s.auto_backup);
}
const speaker = () => cmd({cmd:"speaker", value: st && (st.speaker || st.connecting) ? "disconnect" : "connect"}, false);
function renderLink(l) {                           // the Pocket's Studio link (null on the Studio)
  $("s-link").hidden = !l;
  if (!l) return;
  $("s-lon").checked = l.on; $("s-lon").onchange = (e) => set("studio_link", e.target.checked);
  $("s-laudio").checked = l.audio; $("s-laudio").onchange = (e) => set("link_audio", e.target.checked);
  $("s-lstudio").textContent = !l.on ? "off" : l.studio ? `${l.studio} · ${l.cable ? "cable" : "Wi-Fi"}` : (l.error || "looking…");
  $("s-lsend").textContent = !l.on || !l.audio ? "off" : l.sending ? "going to the Studio" : "not going yet";
}
// the mixer: a level for each sound source while there's more than one (FM-1 A and B, a USB keyboard's synth)
// a source with more than two channels (an audio interface) shows which pair it takes; tap it for the next
let shownMix = "", mixUntil = 0, mixTimer;
function renderMixer(st) {
  const m = st.mixer, keys = m ? m.map((c) => c.key + c.label + (c.input || "")).join() : "";
  if (keys !== shownMix) {
    shownMix = keys;
    $("s-mix").innerHTML = !m ? "" : `<div class="line"><span class="k">Mixer</span></div>` + m.map((c) =>
      `<div class="line" style="display:block"><div class="row" style="justify-content:space-between"><span class="k">${esc(c.label)}${c.input ? ` <button onclick="set('input_${c.key}', true)">${esc(c.input)}</button>` : ""}</span><b id="mx-${c.key}v"></b></div>
       <input type="range" id="mx-${c.key}" min="0" max="200" step="5" oninput="mixSet('${c.key}', this.value)"></div>`).join("");
  }
  if (!m || Date.now() < mixUntil) return;
  for (const c of m) { $(`mx-${c.key}`).value = c.level; $(`mx-${c.key}v`).textContent = c.level + "%"; }
}
function mixSet(k, v) {
  mixUntil = Date.now() + 2500; $(`mx-${k}v`).textContent = v + "%";
  clearTimeout(mixTimer); mixTimer = setTimeout(() => set(`mix_${k}`, +v), 250);
}
$("s-vol").oninput = (e) => { editingUntil = Date.now() + 2500; $("s-volv").textContent = e.target.value + "%"; clearTimeout(volTimer); volTimer = setTimeout(() => set("volume", +e.target.value), 250); };
$("s-tempo").onchange = (e) => { const v = Math.max(30, Math.min(300, Math.round(+e.target.value || 120))); e.target.value = v; set("bpm", v); };
function bump(d) { editingUntil = Date.now() + 2500; const el = $("s-tempo"); el.value = Math.max(30, Math.min(300, (+el.value || 120) + d)); clearTimeout(tempoTimer); tempoTimer = setTimeout(() => set("bpm", +el.value), 350); }
function toggleRec() { cmd({cmd:"record", value: st && st.recording != null ? "stop" : "start"}, false).then(() => setTimeout(refresh, 900)); }

// ---------------------------------------------------------------- Studio tab (XOXO Studio)
let shownKits = "", music = [];
function renderStudio() {
  const x = st && !st.offline && st.xo4;
  if (x) {
    $("x-state").textContent = `${x.pattern}${x.queued ? " → " + x.queued + " next bar" : ""} · ${x.playing ? "playing" : "stopped"}`;
    $("x-pats").innerHTML = "ABCDEFGH".split("").map((p) => `<button class="${p === x.pattern ? "on" : ""} ${p === x.queued ? "queued" : ""} ${(x.used || []).includes(p) ? "" : "empty"}" onclick="cmd({cmd:'xo4',action:'pattern',value:${q(p)}})">${p}</button>`).join("");
    $("x-play").textContent = x.playing ? "■ Stop" : "▶ Play"; $("x-play").className = x.playing ? "" : "primary";
    $("x-midiin").checked = x.midi_in; $("x-midiin").onchange = (e) => cmd({cmd:"xo4", action:"midi_in", value:e.target.checked});
    for (const t of [1, 2]) {
      const el = $("x-s" + t), v = x.sounds[t - 1];
      if (document.activeElement === el) continue;          // (not under a finger)
      el.innerHTML = opt(v === "CUSTOM" ? ["CUSTOM", ...x.choices] : x.choices, v, (n) => n === "CUSTOM" ? "custom (from the SOUND page)" : n);
    }
  }
  const k = st && !st.offline && st.kits;
  if (k) {
    $("k-cur").textContent = k.current;
    const key = JSON.stringify(k);
    if (key !== shownKits) { shownKits = key; $("k-list").innerHTML = k.list.map((n) => `<div class="item"><span class="name">${esc(n.replace(/-/g, " "))}</span><button onclick="cmd({cmd:'kit', name:${q(n)}}, false)">Load</button></div>`).join("") || `<p class="empty">No kits saved.</p>`; }
  }
  const d = st && !st.offline ? st.decks : null;
  $("d-decks").innerHTML = !d ? `<p class="empty">The decks aren't running: open DECKS on the Studio.</p>` : d.map((x, i) => `<div class="item"><div><div class="name">${"AB"[i]} · ${esc(x.title || "empty")}</div>
    <div class="meta">${x.artist ? esc(x.artist) + " · " : ""}${x.bpm ? Number(x.bpm).toFixed(1) + " BPM" : ""}${x.camelot ? " · " + esc(x.camelot) : ""}</div></div>
    <div class="row"><span class="pill ${x.playing ? "live" : ""}">${x.playing ? "playing" : "paused"}</span>${x.fx ? `<span class="pill ${x.fx_on ? "rec" : ""}">${esc(x.fx)}${x.fx_on ? " on" : ""}</span>` : ""}</div></div>`).join("");
}
function renderMusic() {
  $("music").innerHTML = music.length ? music.map((m) => `<div class="item"><div><div class="name">${esc(m.title)}</div>
    <div class="meta">${m.artist ? esc(m.artist) + " · " : ""}${m.bpm ? Math.round(m.bpm) + " BPM · " : ""}${m.camelot ? esc(m.camelot) + " · " : ""}${(m.bytes / 1048576).toFixed(1)} MB${m.top ? "" : " · in " + esc(m.name.slice(0, m.name.lastIndexOf("/")))}</div></div>
    ${m.top ? `<button class="danger" onclick="del('music',${q(m.name)})">Delete</button>` : ""}</div>`).join("")
    : `<p class="empty">No music yet: add MP3, FLAC or WAV files.</p>`;
}
function xo4Sound(track, v) { if (v !== "CUSTOM") cmd({cmd:"xo4", action:"sound", track, value:v}); }

// ---------------------------------------------------------------- MIDI tab
// FM-1 B's row and column only while a second FM-1 is plugged in (then the first is FM-1 A)
// NET (network MIDI: a DAW on a computer, the desk box) only while a computer is connected
const ALL_SOURCES = {"BT":"Bluetooth", "USB":"USB keys", "NET":"Network", "FM-1":"FM-1", "FM-1 B":"FM-1 B", "XO4":"XO-4", "Box":"Box clock"}, ALL_DESTS = ["FM-1", "FM-1 B", "BT", "USB", "NET", "SMP"];
let twoFm1 = false, netOn = false, padsOn = false, SOURCES = {}, DESTS = [];
// the Studio: each USB MIDI device its own row and column ("U:" + its name), as st.matrix lists them
let matrixKey = "";
const devName = (k) => k.startsWith("U:") ? k.slice(2) : null;
function setFm1s(two, net = netOn, pads = padsOn, matrix = null) {
  twoFm1 = two; netOn = net; padsOn = pads;
  const shown = (k) => (two || k !== "FM-1 B") && (net || k !== "NET") && (pads || k !== "SMP") && k !== "XO4";   // (XO-4: in st.matrix)
  const label = (k) => devName(k) || (two && k === "FM-1" ? "FM-1 A" : ALL_SOURCES[k] || k);
  const srcs = matrix ? matrix.sources : Object.keys(ALL_SOURCES).filter(shown);
  SOURCES = Object.fromEntries(srcs.map((k) => [k, label(k)]));
  DESTS = matrix ? matrix.dests : ALL_DESTS.filter(shown);
  const [s, d] = sel.split(">");
  if (!(s in SOURCES) || !DESTS.includes(d)) {
    const first = Object.keys(SOURCES)[0];
    sel = "BT" in SOURCES && DESTS.includes("FM-1") ? "BT>FM-1" : `${first}>${DESTS.find((x) => x !== first)}`;
  }
}
const destName = (d) => devName(d) || (d === "BT" ? "Bluetooth" : d === "NET" ? "Network" : d === "SMP" ? "Sampler" : twoFm1 && d === "FM-1" ? "FM-1 A" : d);
const CHORDS = ["oct","5th","maj","min","7","maj7","m7"], ARPS = ["up","down","updown","played","random"], RATES = ["1/4","1/8","1/8T","1/16"];
let routes = null, sel = "BT>FM-1", routesDirtyUntil = 0, saveTimer;
setFm1s(false);
function renderMatrix() {
  if (!routes) { $("mx").innerHTML = `<tr><td class="dim">Waiting for the box…</td></tr>`; return; }
  $("mx").innerHTML = `<tr><th></th>${DESTS.map((d) => `<th>to ${destName(d)}</th>`).join("")}</tr>` +
    Object.keys(SOURCES).map((s) => `<tr><th>${SOURCES[s]}</th>${DESTS.map((d) => {
      const key = `${s}>${d}`;
      if (s === d) return `<td class="self">–</td>`;
      const r = routes[key];
      return `<td><button class="${r.on ? "on" : ""} ${key === sel ? "sel" : ""}" onclick="pick(${q(key)})">${r.on ? "on" : "off"}</button></td>`;
    }).join("")}</tr>`).join("");
}
function pick(key) {
  if (key === sel) { routes[key].on = !routes[key].on; saveRoutes(); }   // tapping the selected route switches it
  sel = key; renderMatrix(); renderEditor();
}
const opt = (list, v, label = (x) => x) => list.map((x) => `<option value="${esc(x)}" ${String(x) === String(v) ? "selected" : ""}>${esc(label(x))}</option>`).join("");
const sw = (field, on) => `<label class="sw"><input type="checkbox" ${on ? "checked" : ""} onchange="edit(${q(field)}, this.checked)"><span></span></label>`;
function renderEditor() {
  if (!routes) return;
  const r = routes[sel], [s, d] = sel.split(">");
  $("ed-title").textContent = `${SOURCES[s]} → ${destName(d)}`;
  let h = `<div class="line"><span class="k">Route</span>${sw("on", r.on)}</div>`;
  if (s !== "Box") {
    const ch = r.channels, mode = ch === "same" ? "same" : Array.isArray(ch) ? "custom" : "all";
    h += `<div class="line"><span class="k">Channels</span><div class="row"><select onchange="chMode(this.value)">${opt(["same","all","custom"], mode, (x) => ({same:"same", all:"all to one", custom:"custom table"})[x])}</select>
      ${mode === "all" ? `<select onchange="edit('channels', +this.value)">${opt([...Array(16).keys()], ch, (x) => "ch " + (x + 1))}</select>` : ""}</div></div>`;
    if (mode === "custom") h += `<div class="chgrid" style="margin:4px 0 10px">${ch.map((o, i) => `<div><label>in ${i + 1}</label><select onchange="chSet(${i}, this.value)">${opt(["off", ...Array(16).keys()], o == null ? "off" : o, (x) => x === "off" ? "off" : "ch " + (x + 1))}</select></div>`).join("")}</div>`;
    h += `<div class="line"><span class="k">Transpose</span><div class="row"><button onclick="edit('transpose', Math.max(-24, routes[sel].transpose - 1))">−</button><b style="min-width:42px;text-align:center">${r.transpose > 0 ? "+" : ""}${r.transpose}</b><button onclick="edit('transpose', Math.min(24, routes[sel].transpose + 1))">+</button></div></div>
      <div class="line"><span class="k">Velocity</span><div class="row"><select onchange="edit('velocity', this.value)">${opt(["normal","soft","hard","fixed"], r.velocity)}</select>
      ${r.velocity === "fixed" ? `<input type="number" min="1" max="127" value="${r.fixed}" onchange="edit('fixed', Math.max(1, Math.min(127, Math.round(+this.value || 100))))">` : ""}</div></div>
      <div class="line"><span class="k">Drop clock</span>${sw("drop_clock", r.drop_clock)}</div>
      <div class="line"><span class="k">Drop aftertouch</span>${sw("drop_aftertouch", r.drop_aftertouch)}</div>
      <div class="line"><span class="k">Drop pitch-bend</span>${sw("drop_bend", r.drop_bend)}</div>
      <div class="line"><span class="k">Chord</span><div class="row"><select onchange="edit('chord', this.value)">${opt(CHORDS, r.chord)}</select>${sw("chord_on", r.chord_on)}</div></div>
      <div class="line"><span class="k">Arp</span><div class="row"><select onchange="edit('arp', this.value)">${opt(ARPS, r.arp)}</select>
        <select onchange="edit('arp_rate', this.value)">${opt(RATES, r.arp_rate)}</select>
        <select onchange="edit('arp_octaves', +this.value)">${opt([1,2,3], r.arp_octaves, (x) => x + " oct")}</select>${sw("arp_on", r.arp_on)}</div></div>`;
  } else h += `<p class="dim small">The box's clock and Start/Stop go here when it's on (Clock: Box).</p>`;
  $("ed").innerHTML = h;
}
function edit(field, value) { routes[sel][field] = value; saveRoutes(); renderMatrix(); renderEditor(); }
function chMode(m) { edit("channels", m === "same" ? "same" : m === "all" ? 0 : [...Array(16).keys()]); }
function chSet(i, v) { routes[sel].channels[i] = v === "off" ? null : +v; saveRoutes(); }
function saveRoutes() {
  routesDirtyUntil = Date.now() + 3000; shownRoutes = JSON.stringify(routes); $("ed-saved").textContent = "Saving…";
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => { const j = await cmd({cmd:"routes", routes}); $("ed-saved").textContent = j.ok ? "Saved on the box." : j.message; }, 300);
}
function renderPresets() {
  const p = (st && st.presets) || {};
  $("presets").innerHTML = ["1","2","3","4"].map((slot) => { const x = p[slot];
    return `<div class="item"><div style="flex:1;min-width:180px"><input type="text" id="pn${slot}" maxlength="16" placeholder="Preset ${slot}" value="${esc(x && x.name || "")}" style="width:100%">
      <div class="meta">${x ? "saved " + when(x.saved) : "empty"}</div></div>
      <div class="row">${x ? `<button class="primary" onclick="preset(${q(slot)}, 'load')">Load</button>` : ""}<button onclick="preset(${q(slot)}, 'save')">Save here</button>${x ? `<button class="danger" onclick="preset(${q(slot)}, 'clear')">Clear</button>` : ""}</div></div>`; }).join("");
}
function preset(slot, action) {
  if (action === "clear" && !confirm(`Clear preset ${slot}?`)) return;
  const name = $("pn" + slot).value.trim() || `preset ${slot}`;
  cmd({cmd:"preset", slot, action, name: action === "save" ? $("pn" + slot).value.trim() : null}).then((j) => {
    routesDirtyUntil = 0; shownRoutes = ""; shownPresets = "";
    if (j.ok) toast({load: `Loaded ${name}`, save: `Saved as ${name}`, clear: `Preset ${slot} cleared`}[action]);
  });
}

// ---------------------------------------------------------------- library and recordings
const run = (c) => post("/api/run", {cmd:c}).then(() => { refresh(); setTimeout(update, 300); });
const ask = (body) => post("/api/ask", body).then(() => setTimeout(update, 300));
async function del(folder, name) { if (confirm(`Delete ${name}?`)) { await post("/api/delete", {folder, name}); refresh(); } }
async function upload(folder, input) {
  for (const f of input.files) {
    toast(`Uploading ${f.name}…`);
    const r = await fetch(`/api/upload?folder=${folder}&name=${encodeURIComponent(f.name)}`, {method:"POST", body:f});
    const j = await r.json().catch(() => ({ok:false, message:r.statusText}));
    toast(j.message, j.ok);
  }
  input.value = ""; refresh();
}
function targetSelect(id) {
  return `<select id="${id}">${["working","A","B","C","D"].map((t) => `<option value="${t}">${t === "working" ? "working project" : "project " + t}</option>`).join("")}</select>`;
}
const jump = (id) => $(id).scrollIntoView({behavior:"smooth", block:"start"});   // the Library's chips
function renderLibrary() {
  for (const k of ["backups", "projects", "samples", "firmware", "recordings", "songs", "patches"]) lib[k] = lib[k] || [];
  for (const k of ["backups", "songs", "patches", "samples", "firmware"]) $("n-" + k).textContent = (lib[k] || []).length || "";
  $("n-projects").textContent = lib.projects.length + lib.backups.reduce((n, b) => n + (b.projects || []).length, 0) || "";
  $("backups").innerHTML = lib.backups.length ? lib.backups.map((b) => `<div class="item"><div><div class="name">${when(b.date)}</div>
    <div class="meta">${fw(b.firmware)} · projects ${esc((b.projects || []).join(" ") || "none")} · samples ${esc((b.samples || []).join(" ") || "none")}${b.name.includes("_auto") ? " · auto" : ""}</div></div>
    <div class="row"><a href="/files/backups/${encodeURIComponent(b.name)}" download><button>Download</button></a>
    <button onclick="ask({cmd:'restore', file:${q(b.name)}})">Restore…</button><button class="danger" onclick="del('backups',${q(b.name)})">Delete</button></div></div>`).join("")
    : `<p class="empty">No backups yet.</p>`;
  const fromBackups = lib.backups.flatMap((b) => (b.projects || []).map((p) => ({folder:"backups", file:b.name, source:p, label:`Project ${p}`, meta:`${when(b.date)} backup · ${fw(b.firmware)}`})));
  const files = lib.projects.map((p) => ({folder:"projects", file:p.name, source:"-", label:p.title || p.name, meta:`project file · ${fw(p.firmware)}`}));
  const all = [...files, ...fromBackups];
  $("projects").innerHTML = all.length ? all.map((p, i) => `<div class="item"><div><div class="name">${esc(p.label)}</div><div class="meta">${p.meta}</div></div>
    <div class="row">${targetSelect("t" + i)}<button onclick="ask({cmd:'load-project', folder:${q(p.folder)}, file:${q(p.file)}, source:${q(p.source)}, target:$('t${i}').value})">Load…</button>
    ${p.folder === "backups" ? `<a href="/api/project?backup=${encodeURIComponent(p.file)}&source=${p.source}" download><button>Download</button></a>` : `<a href="/files/projects/${encodeURIComponent(p.file)}" download><button>Download</button></a><button class="danger" onclick="del('projects',${q(p.file)})">Delete</button>`}</div></div>`).join("")
    : `<p class="empty">No projects yet: make a backup, or upload a project file.</p>`;
  const patches = lib.patches || [];
  $("patches").innerHTML = patches.length ? patches.map((p, i) => `<div class="item"><div><div class="name">${esc(p.name)}</div>
    <div class="meta">${p.damaged ? "damaged" : p.kind === "bank" ? "bank · " + esc((p.voices || []).filter(Boolean).slice(0, 6).join(", ")) + "…" : "voice · " + esc((p.voices || [""])[0])}</div></div>
    <div class="row">${p.damaged ? "" : p.kind === "bank" ? `<select id="v${i}"><option value="">whole bank</option>${(p.voices || []).map((v, k) => `<option value="${k + 1}">${k + 1} ${esc(v)}</option>`).join("")}</select>
    <button onclick="ask({cmd:'dx7-send', file:${q(p.name)}, voice:$('v${i}').value ? +$('v${i}').value : null})">Send…</button>` : `<button onclick="ask({cmd:'dx7-send', file:${q(p.name)}, voice:null})">Send…</button>`}
    <a href="/files/patches/${encodeURIComponent(p.name)}" download><button>Download</button></a><button class="danger" onclick="del('patches',${q(p.name)})">Delete</button></div></div>`).join("")
    : `<p class="empty">No DX7 patches yet: upload a .syx.</p>`;
  const songs = lib.songs || [];
  $("songs").innerHTML = songs.length ? songs.map((s) => `<div class="item"><div><div class="name">${esc(s.title || s.name)}</div>
    <div class="meta">${when(s.date)} · ${fw(s.firmware)} · sections ${esc(s.sections || "none")} · ${s.steps || 0} steps${s.loop ? ", loops" : ""}${s.damaged ? " · damaged" : ""}</div></div>
    <div class="row">${s.damaged ? "" : `<button onclick="ask({cmd:'load-song', file:${q(s.name)}})">Load…</button>`}<a href="/files/songs/${encodeURIComponent(s.name)}" download><button>Download</button></a>
    <button class="danger" onclick="del('songs',${q(s.name)})">Delete</button></div></div>`).join("")
    : `<p class="empty">No songs yet: Back up song saves the one on the FM-1.</p>`;
  $("samples").innerHTML = lib.samples.length ? lib.samples.map((s) => `<div class="item"><label class="row">${xoxo() ? "" : `<input type="checkbox" class="pick" value="${esc(s.name)}" style="width:22px;height:22px">`}<span class="name">${esc(s.name)}</span></label>
    <div class="row"><span class="meta">${(s.bytes / 1024).toFixed(0)} KB</span><button onclick="sedOpen('samples', ${q(s.name)})">Edit…</button><button class="danger" onclick="del('samples',${q(s.name)})">Delete</button></div></div>`).join("")
    : `<p class="empty">No WAV files yet.</p>`;
  $("firmware").innerHTML = lib.firmware.length ? lib.firmware.map((f) => `<div class="item"><div><div class="name">${esc(f.name)}</div><div class="meta">${when(f.date)}</div></div>
    <div class="row"><button onclick="ask({cmd:'flash', file:${q(f.name)}})">Install…</button><button class="danger" onclick="del('firmware',${q(f.name)})">Delete</button></div></div>`).join("")
    : `<p class="empty">No firmware yet: Get SLOOP update or Get Clipper, or upload a .fwsc.</p>`;
  $("recordings").innerHTML = lib.recordings.length ? lib.recordings.map((r, i) => `<div class="item" style="display:block"><div class="row" style="justify-content:space-between"><div><div class="name">${when(r.date)}</div>
    <div class="meta">${mins(r.seconds)} · ${(r.bytes / 1048576).toFixed(1)} MB${r.clips >= 5 ? ` · <span class="warn" title="The FM-1 clipped before the box got the sound: set its USB to master and turn it down, or lower its track levels">clipped ${r.clips}×</span>` : ""}</div></div>
    <a href="/files/recordings/${encodeURIComponent(r.name)}" download><button>Download</button></a></div>
    <audio controls preload="none" src="/files/recordings/${encodeURIComponent(r.name)}?inline=1"></audio>
    <div class="row" style="margin-top:6px"><button onclick="sedOpen('recordings', ${q(r.name)})">Edit as sample…</button>
    <button class="danger" onclick="del('recordings',${q(r.name)})">Delete</button></div>
    ${(r.parts || []).length ? `<details style="margin-top:8px"><summary class="meta">Parts: each source on its own (${r.parts.length})</summary>${r.parts.map((p) => `
      <div class="row" style="justify-content:space-between;margin-top:6px"><span class="name">${esc(p.label)}${p.clips >= 5 ? ` <span class="warn">clipped ${p.clips}×</span>` : ""}</span>
      <div class="row"><button onclick="sedOpen('recordings', ${q(p.name)})">Edit…</button><a href="/files/recordings/${encodeURIComponent(p.name)}" download><button>Download</button></a></div></div>
      <audio controls preload="none" src="/files/recordings/${encodeURIComponent(p.name)}?inline=1"></audio>`).join("")}</details>` : ""}</div>`).join("")
    : `<p class="empty">No recordings yet: press Record above, or on the box press on any meter screen.</p>`;
  const pick = $("sed-pick"), was = pick.value;
  pick.innerHTML = (lib.recordings.length ? `<optgroup label="Recordings">${lib.recordings.map((r) => `<option value="recordings/${esc(r.name)}">${when(r.date)} · ${mins(r.seconds)}</option>`
      + (r.parts || []).map((p) => `<option value="recordings/${esc(p.name)}">  ${when(r.date)} · ${esc(p.label)}</option>`).join("")).join("")}</optgroup>` : "")
    + (lib.samples.length ? `<optgroup label="Samples">${lib.samples.map((x) => `<option value="samples/${esc(x.name)}">${esc(x.name)}</option>`).join("")}</optgroup>` : "")
    || `<option value="">No recordings or samples yet</option>`;
  if ([...pick.options].some((o) => o.value === was)) pick.value = was;
}
function loadSamples() {
  const files = [...document.querySelectorAll(".pick:checked")].map((c) => c.value);
  if (!files.length) return toast("Tick at least one WAV", false);
  ask({cmd:"load-sample", files, slot:+$("sslot").value, name:$("sname").value});
}

// ---------------------------------------------------------------- sample editor
// The take is decoded here, so the waveform, zoom and preview run on the phone; Save sends the settings and
// the box makes the file with the same sums the preview uses (sampler.py).
let sed = null, actx = null, sedSrc = null;
const NOTE_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"];
const noteName = (n) => NOTE_NAMES[n % 12] + (Math.floor(n / 12) - 1);
const num = (id) => parseFloat($(id).value) || 0;
function sedPicked() { const v = $("sed-pick").value; if (v) sedOpen(v.slice(0, v.indexOf("/")), v.slice(v.indexOf("/") + 1)); }
async function sedOpen(folder, file) {
  if (tab !== "editor") show("editor");
  $("sed").hidden = false; $("sed-take").textContent = "loading…"; $("sed").scrollIntoView({behavior:"smooth", block:"start"});
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    const [info, data] = await Promise.all([fetch(`/api/edit-info?folder=${folder}&file=${encodeURIComponent(file)}`).then((r) => r.json()),
                                            fetch(`/files/${folder}/${encodeURIComponent(file)}?inline=1`).then((r) => r.arrayBuffer())]);
    if (info.ok === false) throw new Error(info.message);
    const buf = await actx.decodeAudioData(data);
    const mono = new Float32Array(buf.length);
    for (let c = 0; c < buf.numberOfChannels; c++) { const d = buf.getChannelData(c); for (let i = 0; i < d.length; i++) mono[i] += d[i] / buf.numberOfChannels; }
    sed = {folder, file, info, rate: buf.sampleRate, mono, seconds: buf.length / buf.sampleRate, drag: null};
  } catch (e) { toast("Can't open it: " + e.message, false); return sedClose(); }
  const i = sed.info;
  $("sed-take").textContent = i.name; $("sed-name").value = i.name;
  $("sed-start").value = i.start; $("sed-end").value = i.end; $("sed-start").max = $("sed-end").max = sed.seconds;
  $("sed-fi").value = 0; $("sed-fo").value = 10; $("sed-norm").checked = true; $("sed-rev").checked = false; $("sed-zoom").value = 1;
  let opts = `<option value="">none (plays as C4)</option>`;
  for (let n = 24; n <= 96; n++) opts += `<option value="${noteName(n)}">${noteName(n)}${noteName(n) === i.note ? " (found)" : ""}</option>`;
  $("sed-note").innerHTML = opts; $("sed-note").value = i.note || "";
  sedDraw();
}
function sedClose() { sedStop(); sed = null; $("sed").hidden = true; }
function sedStop() { if (sedSrc) { try { sedSrc.stop(); } catch (e) {} sedSrc = null; } }
function sedView() {                                // [from, to] seconds shown: the selection's middle, zoomed
  if (sed.drag && sed.view) return sed.view;        // held still while a marker is dragged
  const z = +$("sed-zoom").value, span = sed.seconds / z, mid = (num("sed-start") + num("sed-end")) / 2;
  const from = Math.min(Math.max(0, mid - span / 2), sed.seconds - span);
  return [from, from + span];
}
function sedDraw() {
  if (!sed) return;
  const cv = $("sed-wave"), dpr = window.devicePixelRatio || 1, w = cv.width = cv.clientWidth * dpr, h = cv.height = cv.clientHeight * dpr;
  const g = cv.getContext("2d"), css = getComputedStyle(document.body);
  const [from, to] = sedView(), x = (t) => (t - from) / (to - from) * w;
  const s = num("sed-start"), e = num("sed-end"), fi = num("sed-fi") / 1000, fo = num("sed-fo") / 1000;
  g.fillStyle = css.getPropertyValue("--accent"); g.globalAlpha = .16; g.fillRect(x(s), 0, x(e) - x(s), h); g.globalAlpha = 1;
  const a0 = Math.floor(from * sed.rate), per = (to - from) * sed.rate / w;
  let peak = 1e-9; for (let i = 0; i < sed.mono.length; i += 64) peak = Math.max(peak, Math.abs(sed.mono[i]));
  g.strokeStyle = css.getPropertyValue("--ink"); g.lineWidth = Math.max(1, dpr * .8); g.beginPath();
  for (let px = 0; px < w; px++) {
    let lo = 0, hi = 0; const a = a0 + Math.floor(px * per), b = Math.min(sed.mono.length, a0 + Math.floor((px + 1) * per) + 1);
    for (let i = a; i < b; i++) { const v = sed.mono[i]; if (v < lo) lo = v; if (v > hi) hi = v; }
    g.moveTo(px + .5, h / 2 - hi / peak * h * .46); g.lineTo(px + .5, h / 2 - lo / peak * h * .46 + 1);
  }
  g.stroke();
  g.strokeStyle = css.getPropertyValue("--accent"); g.lineWidth = 2 * dpr; g.beginPath();   // the fades
  g.moveTo(x(s), h); g.lineTo(x(s + fi), 4 * dpr); g.lineTo(x(e - fo), 4 * dpr); g.lineTo(x(e), h); g.stroke();
  for (const t of [s, e]) { g.fillRect(x(t) - dpr, 0, 2 * dpr, h); }
  const len = e - s, slot = sed.info.slot_seconds;
  $("sed-len").innerHTML = `${len.toFixed(2)} s selected` + (len > slot ? ` <span class="warn">· longer than a SLOOP slot holds (${slot} s): it won't fit until it's trimmed</span>` : "");
}
function sedTime(ev) { const r = $("sed-wave").getBoundingClientRect(), [from, to] = sedView(); return from + (ev.clientX - r.left) / r.width * (to - from); }
function sedSet(which, t) {
  const s = num("sed-start"), e = num("sed-end");
  t = Math.round(Math.min(sed.seconds, Math.max(0, t)) * 1000) / 1000;
  if (which === "start") $("sed-start").value = Math.min(t, e - .02); else $("sed-end").value = Math.max(t, s + .02);
  sedDraw();
}
$("sed-wave").addEventListener("pointerdown", (ev) => {
  if (!sed) return;
  const t = sedTime(ev); sed.drag = Math.abs(t - num("sed-start")) < Math.abs(t - num("sed-end")) ? "start" : "end";
  sed.view = null; sed.view = sedView(); $("sed-wave").setPointerCapture(ev.pointerId); sedSet(sed.drag, t);
});
$("sed-wave").addEventListener("pointermove", (ev) => { if (sed && sed.drag) sedSet(sed.drag, sedTime(ev)); });
$("sed-wave").addEventListener("pointerup", () => { if (sed) { sed.drag = sed.view = null; sedDraw(); } });
for (const id of ["sed-start", "sed-end", "sed-fi", "sed-fo", "sed-zoom"]) $(id).addEventListener("input", sedDraw);
window.addEventListener("resize", sedDraw);
function sedPlay() {                                // the edit as it will be saved, played on this phone
  if (!sed) return;
  sedStop(); actx.resume();
  const a = Math.floor(num("sed-start") * sed.rate), b = Math.min(sed.mono.length, Math.floor(num("sed-end") * sed.rate));
  if (b - a < sed.rate * .02) return toast("The selection is too short", false);
  const y = sed.mono.slice(a, b); if ($("sed-rev").checked) y.reverse();
  const fi = Math.min(y.length, Math.floor(num("sed-fi") / 1000 * sed.rate)), fo = Math.min(y.length, Math.floor(num("sed-fo") / 1000 * sed.rate));
  for (let i = 0; i < fi; i++) y[i] *= i / fi;
  for (let i = 0; i < fo; i++) y[y.length - 1 - i] *= i / fo;
  if ($("sed-norm").checked) { let p = 0; for (const v of y) p = Math.max(p, Math.abs(v)); if (p) { const k = sed.info.level / p; for (let i = 0; i < y.length; i++) y[i] *= k; } }
  const buf = actx.createBuffer(1, y.length, sed.rate); buf.copyToChannel(y, 0);
  sedSrc = actx.createBufferSource(); sedSrc.buffer = buf; sedSrc.connect(actx.destination); sedSrc.start();
}
async function sedSave() {
  if (!sed) return;
  const j = await post("/api/save-sample", {folder: sed.folder, file: sed.file, start: num("sed-start"), end: num("sed-end"),
    fade_in: num("sed-fi") / 1000, fade_out: num("sed-fo") / 1000, normalize: $("sed-norm").checked,
    reverse: $("sed-rev").checked, note: $("sed-note").value, name: $("sed-name").value});
  if (j.ok) refresh();
}

// ---------------------------------------------------------------- polling
let last = "";
async function update() {                          // the library job, as before
  if (xoxo()) return false;                        // (XOXO Studio has none)
  const s = await fetch("/api/state").then((r) => r.json()).catch(() => ({}));
  const running = s.state === "running";
  $("job").innerHTML = s.waiting ? "Waiting for the confirmation on the box…"
    : running ? `${esc(s.job)}: ${esc(s.step)}${s.percent != null ? " " + Math.round(s.percent) + "%" : ""}`
    : s.state ? `Last: ${esc(s.job)} <span style="color:var(${s.state === "done" ? "--on" : "--bad"})">${esc(s.state === "done" ? "done" : "failed")}</span>: ${esc(s.message)}` : "Nothing running.";
  $("barwrap").hidden = !running || s.percent == null; $("bar").style.width = (s.percent || 0) + "%";
  const key = `${s.state}${s.finished}`;
  if (key !== last) { last = key; refresh(); }
  return running || s.waiting;
}
let shownRoutes = "", shownPresets = "";
async function status() {
  st = await fetch("/api/status").then((r) => r.json()).catch(() => ({offline:true}));
  renderStatus();
  if (tab === "studio") renderStudio();
  if (st.offline) return;
  // redraw the MIDI tab only when the box's routes or presets changed: a redraw closes an open dropdown,
  // and the presets' name fields mustn't change under your fingers
  const r = JSON.stringify(st.routes), p = JSON.stringify(st.presets || {});
  const net = !!(st.midi.net && st.midi.net.length);
  const mk = JSON.stringify(st.matrix || null);
  if (!!st.midi.usb_b !== twoFm1 || net !== netOn || !!st.midi.pads !== padsOn || mk !== matrixKey) { matrixKey = mk; setFm1s(!!st.midi.usb_b, net, !!st.midi.pads, st.matrix || null); shownRoutes = ""; }
  if (r !== shownRoutes && Date.now() > routesDirtyUntil) { routes = JSON.parse(r); shownRoutes = r; renderMatrix(); renderEditor(); }
  if (p !== shownPresets && !String(document.activeElement && document.activeElement.id).startsWith("pn")) { shownPresets = p; renderPresets(); }
}
async function refresh() {
  lib = await fetch("/api/library").then((r) => r.json()).catch(() => lib); renderLibrary();
  if (tab === "library" && st && !st.offline && !xoxo()) software();
  if (tab === "studio") { music = await fetch("/api/music").then((r) => r.json()).catch(() => music); renderMusic(); }
}
async function software(fresh) {                   // Library > Software: the installed version, the newest, the last update
  const u = await fetch("/api/update" + (fresh ? "?fresh=1" : "")).then((r) => r.json()).catch(() => null);
  if (!u) { $("software").textContent = "Couldn't ask the box."; return; }
  const last = u.last && u.last.state ? `<br>Last update: ${esc(u.last.message)}${u.last.time ? " (" + when(u.last.time) + ")" : ""}` : "";
  const running = u.last && (u.last.state === "installing" || u.last.state === "restarting");
  $("software").innerHTML = `Installed: <b>${esc(u.installed)}</b> (${u.build === "pocket" ? "Pocket" : "Studio"})<br>`
    + (u.error ? esc(u.error) : u.newer ? `Newest: <b>${esc(u.newest)}</b>, ready to install` : `Up to date${u.newest ? " (newest: " + esc(u.newest) + ")" : ""}`)
    + (!u.helper ? "<br>This box needs one update over SSH first (install.sh) before it can update itself." : "")
    + (u.busy && !running ? `<br>Can't update now: ${esc(u.busy)}` : "") + last;
  $("sw-update").hidden = !(u.newer && u.helper) || running;
  $("sw-notes").hidden = !u.newest; $("sw-notes").href = u.notes;
  if (running) setTimeout(software, 3000);
}
async function pollJobs() { setTimeout(pollJobs, (await update()) ? 700 : 3000); }
async function pollStatus() { if (!document.hidden && (tab === "status" || tab === "studio" || tab === "midi" || tab === "recordings")) await status(); setTimeout(pollStatus, 1000); }
show((location.hash || "#status").slice(1).replace(/[^a-z]/g, "") || "status");
pollJobs(); pollStatus();
</script></body></html>
"""


def main():
    port = int(os.environ.get("FM1_WEB_PORT", "80"))
    ThreadingHTTPServer(("", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
