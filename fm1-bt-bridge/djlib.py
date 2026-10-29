#!/usr/bin/env python3
"""The Studio's DJ music: ~/fm1-library/Studio DJ Music. Each track's title, artist, BPM and key, from its tags when
it has them (Serato's analysis among them: its BPM, key and hot cues), detected from the sound when it doesn't;
kept in a cache beside the music (.studio-dj.json) so a track is looked at once.

  djlib.py scan [--redetect]       every track in the folder (new and changed ones; --redetect: detect them all)
  djlib.py list                    the folder as JSON
  djlib.py usb                     the USB drives' filesystems, mounted if they aren't

A USB drive is music too: its filesystems mounted read-only by udisks when plugged in (/media/<user>/<label>; a
polkit rule lets the bridge's user do it, install.sh): pulled out without an eject, nothing on it is hurt (an NTFS
drive pulled out of a read-write mount is left "dirty", and isn't mounted read-write again till Windows checks it).
The whole drive is its folder; its cache is kept in the Studio's music folder (.usb/<its UUID>.json).

Decoding: libsndfile (MP3, FLAC, Ogg, WAV, AIFF: the Studio has it, for PipeWire), through ctypes; ffmpeg where
there's no libsndfile (a computer, for the tests).

BPM: an onset strength envelope (spectral flux of a short-time spectrum), its autocorrelation, the strongest
period between 60 and 200 BPM with a gentle preference for 85-175 (and a choice between a tempo and its double or
half by which one the envelope's comb fits better), refined on a multiple of the beat for a finer reading. Key: the
spectrum's peaks between 65 Hz and 1 kHz (not the drums' noise between them), corrected for the track's tuning,
folded onto the 12 pitch classes frame by frame (each frame weighted alike), matched against major and minor
profiles shaped for electronic music (the tonic, the fifth, the third and the scale: what dance tracks lean on);
reported as "Am" / "C#" and in Camelot ("8A"). On 37 Serato-analysed tracks (dubstep around 140 BPM): the key the
same as Serato's on 26, the same or a neighbour on the Camelot wheel on 31."""
import base64
import ctypes
import ctypes.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

LIBRARY = Path(os.environ.get("FM1_LIBRARY", Path.home() / "fm1-library"))
MUSIC = LIBRARY / "Studio DJ Music"
CACHE = ".studio-dj.json"
CONTROLLERS = ".studio-dj-controllers.json"    # beside the music: each controller's map, learned on the DECKS screen
AUDIO = (".mp3", ".flac", ".wav", ".aif", ".aiff", ".ogg") + \
    ((".m4a",) if shutil.which(os.environ.get("FFMPEG") or "ffmpeg") else ())   # (AAC: ffmpeg's, not libsndfile's)
MOUNTABLE = ("vfat", "exfat", "ntfs", "ntfs3", "ext4", "ext3", "ext2", "hfsplus")
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#", "Cb": "B", "Fb": "E", "E#": "F", "B#": "C"}
MAJOR = [1.0, 0.0, 0.6, 0.0, 0.8, 0.6, 0.0, 0.9, 0.0, 0.6, 0.0, 0.4]   # the tonic, fifth, third, then the scale
MINOR = [1.0, 0.0, 0.6, 0.9, 0.0, 0.6, 0.0, 0.9, 0.6, 0.0, 0.6, 0.0]
# Camelot: the circle of fifths, 1-12, A minor / B major
CAMELOT_MAJOR = {"B": 1, "F#": 2, "C#": 3, "G#": 4, "D#": 5, "A#": 6, "F": 7, "C": 8, "G": 9, "D": 10, "A": 11, "E": 12}
CAMELOT_MINOR = {"G#": 1, "D#": 2, "A#": 3, "F": 4, "C": 5, "G": 6, "D": 7, "A": 8, "E": 9, "B": 10, "F#": 11, "C#": 12}
# Open Key (as some tags write it: "9m", "1d"): 1d = C major, 1m = A minor, a fifth up each step
OPEN_MAJOR = ["C", "G", "D", "A", "E", "B", "F#", "C#", "G#", "D#", "A#", "F"]
OPEN_MINOR = ["A", "E", "B", "F#", "C#", "G#", "D#", "A#", "F", "C", "G", "D"]


# ---------------------------------------------------------------- tags

def _text(data):
    """an ID3 text frame's body -> str"""
    if not data:
        return ""
    enc, raw = data[0], data[1:]
    try:
        if enc == 0:
            s = raw.decode("latin-1")
        elif enc == 1:
            s = raw.decode("utf-16")
        elif enc == 2:
            s = raw.decode("utf-16-be")
        else:
            s = raw.decode("utf-8")
    except UnicodeDecodeError:
        s = raw.decode("latin-1", "replace")
    return s.split("\0")[0].strip()


def _syncsafe(b):
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def id3_frames(path):
    """{frame id: [bodies]} from an MP3's ID3v2 tag (v2.3 / v2.4)"""
    with open(path, "rb") as f:
        head = f.read(10)
        if len(head) < 10 or head[:3] != b"ID3":
            return {}
        ver, flags, size = head[3], head[5], _syncsafe(head[6:10])
        data = f.read(size)
    if flags & 0x80:                          # unsynchronised (rare): undo it
        data = data.replace(b"\xff\x00", b"\xff")
    pos, frames = 0, {}
    if flags & 0x40 and len(data) >= 4:       # an extended header: skipped
        pos = _syncsafe(data[:4]) if ver == 4 else struct.unpack(">I", data[:4])[0] + 4
    while pos + 10 <= len(data):
        fid = data[pos:pos + 4]
        if not re.fullmatch(rb"[A-Z0-9]{4}", fid):
            break
        n = _syncsafe(data[pos + 4:pos + 8]) if ver == 4 else struct.unpack(">I", data[pos + 4:pos + 8])[0]
        frames.setdefault(fid.decode(), []).append(data[pos + 10:pos + 10 + n])
        pos += 10 + n
    return frames


def geob(frames):
    """{description: data} of the GEOB frames (Serato's: "Serato Autotags", "Serato Markers2", ...)"""
    out = {}
    for body in frames.get("GEOB", []):
        try:
            rest = body[1:]
            _mime, rest = rest.split(b"\0", 1)
            _name, rest = rest.split(b"\0", 1)
            desc, rest = rest.split(b"\0", 1)
            out[desc.decode("latin-1")] = rest
        except ValueError:
            continue
    return out


def serato_cues(markers2):
    """Serato Markers2 -> [{"index", "ms", "color", "name"}] (its hot cues)"""
    if not markers2 or markers2[:2] != b"\x01\x01":
        return []
    text = markers2[2:].split(b"\0")[0].replace(b"\n", b"")
    try:
        raw = base64.b64decode(text + b"=" * (-len(text) % 4))
    except ValueError:
        return []
    pos, cues = 2, []
    while pos < len(raw):
        end = raw.find(b"\0", pos)
        if end < 0 or end + 5 > len(raw):
            break
        kind, n = raw[pos:end], struct.unpack(">I", raw[end + 1:end + 5])[0]
        body = raw[end + 5:end + 5 + n]
        if kind == b"CUE" and len(body) >= 13:
            name = body[12:].split(b"\0")[0].decode("utf-8", "replace")
            cues.append({"index": body[1], "ms": struct.unpack(">I", body[2:6])[0],
                         "color": "#%02x%02x%02x" % tuple(body[7:10]), "name": name})
        pos = end + 5 + n
    return sorted(cues, key=lambda c: c["index"])


def serato_beatgrid(blob):
    """Serato BeatGrid -> (the first beat in seconds, BPM) or None: markers of a float32 position each, the last one
    with the BPM after it (a constant tempo: one marker)"""
    if not blob or len(blob) < 14 or blob[:2] != b"\x01\x00":
        return None
    count = struct.unpack(">I", blob[2:6])[0]
    if count < 1 or len(blob) < 6 + 8 * count:
        return None
    first = struct.unpack(">f", blob[6:10])[0]
    bpm = struct.unpack(">f", blob[6 + 8 * (count - 1) + 4:6 + 8 * count])[0]
    return (round(first, 3), round(bpm, 2)) if 0 <= first < 3600 and 30 < bpm < 300 else None


def norm_key(text):
    """"Am", "A min", "C#", "Db", "9m" (Open Key), "8A" (Camelot) -> "Am" / "C#", or None"""
    t = (text or "").strip().replace("♯", "#").replace("♭", "b")
    m = re.fullmatch(r"(\d{1,2})([dmAB])", t)
    if m:
        n = int(m.group(1))
        if not 1 <= n <= 12:
            return None
        if m.group(2) in "dm":
            return OPEN_MAJOR[n - 1] if m.group(2) == "d" else OPEN_MINOR[n - 1] + "m"
        inv = {v: k for k, v in (CAMELOT_MINOR if m.group(2) == "A" else CAMELOT_MAJOR).items()}
        return inv[n] + ("m" if m.group(2) == "A" else "")
    m = re.fullmatch(r"([A-Ga-g])([#b]?)\s*(m|min|minor|maj|major)?", t)
    if not m:
        return None
    root = m.group(1).upper() + m.group(2)
    root = FLATS.get(root, root)
    if root not in NAMES:
        return None
    return root + ("m" if (m.group(3) or "").startswith("m") and m.group(3) not in ("maj", "major") else "")


def camelot(key):
    if not key:
        return None
    if key.endswith("m"):
        return f"{CAMELOT_MINOR[key[:-1]]}A"
    return f"{CAMELOT_MAJOR[key]}B"


def read_tags(path):
    """{"title", "artist", "bpm", "key", "cues"} from a track's tags (MP3 ID3 and Serato's)"""
    out = {"title": None, "artist": None, "bpm": None, "key": None, "cues": [], "first_beat": None}
    if Path(path).suffix.lower() != ".mp3":
        return out
    try:
        frames = id3_frames(path)
    except OSError:
        return out
    t = lambda fid: _text(frames[fid][0]) if fid in frames else ""   # noqa: E731
    out["title"], out["artist"] = t("TIT2") or None, t("TPE1") or None
    bpm = t("TBPM")
    blobs = geob(frames)
    auto = blobs.get("Serato Autotags", b"")
    if auto[:2] == b"\x01\x01":               # Serato's own analysis: "140.00\0gain\0..."
        bpm = auto[2:].split(b"\0")[0].decode("ascii", "replace") or bpm
    try:
        out["bpm"] = round(float(bpm), 2) if bpm and 30 <= float(bpm) <= 300 else None
    except ValueError:
        pass
    out["key"] = norm_key(t("TKEY"))
    out["cues"] = serato_cues(blobs.get("Serato Markers2"))
    grid = serato_beatgrid(blobs.get("Serato BeatGrid"))
    if grid:                                  # Serato's grid: where its first beat is (and its BPM, if none yet)
        out["first_beat"] = grid[0]
        out["bpm"] = out["bpm"] or grid[1]
    return out


# ---------------------------------------------------------------- decoding

class _SFInfo(ctypes.Structure):
    _fields_ = [("frames", ctypes.c_int64), ("samplerate", ctypes.c_int), ("channels", ctypes.c_int),
                ("format", ctypes.c_int), ("sections", ctypes.c_int), ("seekable", ctypes.c_int)]


def _sndfile():
    name = ctypes.util.find_library("sndfile")
    if not name:
        return None
    lib = ctypes.CDLL(name)
    lib.sf_open.restype = ctypes.c_void_p
    lib.sf_open.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(_SFInfo)]
    lib.sf_readf_float.restype = ctypes.c_int64
    lib.sf_readf_float.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int64]
    lib.sf_close.argtypes = [ctypes.c_void_p]
    return lib


def decode(path):
    """(int16 numpy array [frames, channels], sample rate) of a whole track. Decoded as floats: a loud master goes
    past full scale (dubstep: up to ~1.1x), and libsndfile's own 16-bit conversion wraps those peaks around (a
    crunch at every one); here a track over full scale is turned down as a whole just enough to fit"""
    import numpy as np
    lib = _sndfile()
    if lib is not None:
        info = _SFInfo()
        f = lib.sf_open(str(path).encode(), 0x10, ctypes.byref(info))        # SFM_READ
        if f:
            try:
                chunks, block = [], 1 << 16
                while True:
                    buf = np.empty((block, info.channels), np.float32)
                    n = lib.sf_readf_float(f, buf.ctypes.data, block)
                    if n <= 0:
                        break
                    chunks.append(buf[:n])
            finally:
                lib.sf_close(f)
            if chunks:
                peak = max(float(np.abs(c).max()) for c in chunks)
                scale = 32767.0 * min(1.0, 0.999 / peak) if peak > 0 else 32767.0
                out = np.empty((sum(len(c) for c in chunks), info.channels), np.int16)
                at = 0
                while chunks:                    # (each chunk freed as it's converted: half the memory)
                    c = chunks.pop(0)
                    out[at:at + len(c)] = np.round(c * scale)
                    at += len(c)
                return out, info.samplerate
    exe = os.environ.get("FFMPEG") or "ffmpeg"     # (no libsndfile: a computer's ffmpeg)
    raw = subprocess.run([exe, "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "2", "-ar", "44100", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).reshape(-1, 2), 44100


# ---------------------------------------------------------------- detection

def _mono(audio, rate, want=11025):
    """float32 mono at about `want` Hz (by averaging whole samples: no filter needed for what's looked at)"""
    import numpy as np
    x = audio.astype(np.float32).mean(axis=1) / 32768.0
    step = max(1, int(round(rate / want)))
    n = len(x) // step * step
    return x[:n].reshape(-1, step).mean(axis=1), rate / step


def _spectrogram(x, n_fft, hop):
    """|STFT| [frames, bins] float32, a chunk of frames at a time (a whole track at once: hundreds of MB, more than
    a Pi 3 has to spare)"""
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view
    frames = 1 + (len(x) - n_fft) // hop
    if frames < 1:
        return np.zeros((0, n_fft // 2 + 1), np.float32)
    view = sliding_window_view(x.astype(np.float32), n_fft)[::hop][:frames]     # (no copy)
    win = np.hanning(n_fft).astype(np.float32)
    out = np.empty((frames, n_fft // 2 + 1), np.float32)
    step = max(1, (1 << 22) // n_fft)        # ~16 MB of frames a chunk
    for i in range(0, frames, step):
        out[i:i + step] = np.abs(np.fft.rfft(view[i:i + step] * win, axis=1))
    return out


def _onsets(x, sr, hop=128, n_fft=1024):
    """(spectral flux of the whole spectrum, of the part below 150 Hz): how much louder each frame got, a chunk of
    frames at a time (never the whole track's spectrum in memory)"""
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view
    frames = 1 + (len(x) - n_fft) // hop
    if frames < 2:
        return np.zeros(0, np.float32), np.zeros(0, np.float32)
    view = sliding_window_view(x.astype(np.float32), n_fft)[::hop][:frames]
    win = np.hanning(n_fft).astype(np.float32)
    low = np.fft.rfftfreq(n_fft, 1 / sr) < 150
    flux, lowflux, prev = [], [], None
    for i in range(0, frames, 4096):
        mag = np.log1p(np.abs(np.fft.rfft(view[i:i + 4096] * win, axis=1)) * 10)
        if prev is not None:
            mag = np.concatenate([prev, mag])
        d = np.maximum(np.diff(mag, axis=0), 0)
        flux.append(d.sum(axis=1))
        lowflux.append(d[:, low].sum(axis=1))
        prev = mag[-1:]
    return np.concatenate(flux), np.concatenate(lowflux)


def detect_bpm(x, sr, phase=False):
    """-> BPM (one decimal), or None; phase: (BPM, the first beat in seconds)"""
    import numpy as np
    hop = 128
    flux, low = _onsets(x, sr, hop)
    if len(flux) < 200:
        return None
    flux = flux - np.convolve(flux, np.ones(16) / 16, mode="same")    # the local mean taken off: the beats
    flux = np.maximum(flux, 0)
    fps = sr / hop
    n = len(flux)
    f = np.fft.rfft(flux - flux.mean(), 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    lags = np.arange(n)
    bpms = 60.0 * fps / np.maximum(lags, 1)
    ok = (bpms >= 60) & (bpms <= 200)
    if not ok.any():
        return None
    score = np.where(ok, ac, -np.inf)
    # a comb: a period's multiples count too (a tempo, not just a repeat)
    comb = score.copy()
    for k in (2, 3, 4):
        idx = np.minimum(lags * k, n - 1)
        comb = comb + np.where(ok, ac[idx] * (0.5 / (k - 1)), 0)
    pref = np.exp(-0.5 * (np.log2(np.maximum(bpms, 1) / 128.0) / 0.9) ** 2)   # gentle: 85-175 most likely
    best = int(np.argmax(np.where(ok, comb * pref, -np.inf)))
    if bpms[best] < 90 and 2 * (best // 2) > 0 and ac[best // 2] > 0.5 * ac[best]:
        best = best // 2 if ac[best // 2] >= ac[best // 2 + 1] else best // 2 + 1   # half time: the beat is twice
    lag = float(best)
    for k in (1, 4, 8):                       # refined on the k-th beat's peak: k times finer
        c = int(round(lag * k))
        if not 2 <= c < n - 2:
            break
        c = max(range(c - 2, c + 3), key=lambda i: ac[i])
        a, b, e = ac[c - 1], ac[c], ac[c + 1]
        d = (a - e) / (2 * (a - 2 * b + e)) if (a - 2 * b + e) else 0.0
        lag = (c + max(-0.5, min(0.5, d))) / k
    bpm = round(60.0 * fps / lag, 1)
    if not phase:
        return bpm
    # where the beats fall: the kick drum's onsets (below 150 Hz), the offset whose comb catches the most, to a
    # fraction of a frame; +22 ms: the lean measured against Serato's beatgrids on 36 tracks (after it, within
    # 15 ms of Serato's on 22 of them: a grid in the tags is better, and is used before this)
    period = 60.0 * fps / bpm
    hits = np.array([low[np.minimum(np.round(np.arange(o, n - 1, period)).astype(int), n - 1)].sum()
                     for o in range(int(period))])
    b = int(np.argmax(hits))
    a, c = hits[b - 1], hits[(b + 1) % len(hits)]
    d = (a - c) / (2 * (a - 2 * hits[b] + c)) if (a - 2 * hits[b] + c) else 0.0
    first = (b + max(-0.5, min(0.5, d))) * hop / sr + 512 / sr + 0.022
    return bpm, round(first % (60.0 / bpm), 3)


def detect_key(x, sr):
    """-> "Am" / "C#", or None"""
    import numpy as np
    n_fft, hop = 8192, 2048
    spec = _spectrogram(x, n_fft, hop)
    if not len(spec):
        return None
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    band = np.where((freqs >= 65) & (freqs <= 1000))[0]
    S = spec[:, band]
    peak = np.zeros_like(S, bool)             # each frame's peaks: louder than both neighbours and twice the median
    peak[:, 1:-1] = (S[:, 1:-1] > S[:, :-2]) & (S[:, 1:-1] > S[:, 2:]) &         (S[:, 1:-1] > 2 * np.median(S, axis=1, keepdims=True))
    cents = 1200 * np.log2(freqs[band] / 440.0)
    hist, edges = np.histogram(((cents + 50) % 100) - 50, bins=20, range=(-50, 50), weights=(S * peak).sum(axis=0))
    tune = (edges[np.argmax(hist)] + edges[np.argmax(hist) + 1]) / 2    # the track's tuning, in cents from 440
    semis = (cents - tune) / 100.0 + 9        # (440 Hz = A = pitch class 9)
    near = np.round(semis).astype(int) % 12
    weight = np.cos(np.pi * (semis - np.round(semis))) ** 2
    energy = np.sqrt(S) * peak * weight[None, :]
    frames = np.stack([energy[:, near == k].sum(axis=1) for k in range(12)], axis=1)
    top = frames.max(axis=1, keepdims=True)
    chroma = np.where(top > 0, frames / np.maximum(top, 1e-9), 0).mean(axis=0)
    if chroma.sum() <= 0:
        return None
    best, key = -2.0, None
    for root in range(12):
        for profile, minor in ((MAJOR, False), (MINOR, True)):
            r = np.corrcoef(chroma, np.roll(profile, root))[0, 1]
            if r > best:
                best, key = r, NAMES[root] + ("m" if minor else "")
    return key


def analyse(path):
    """{"seconds", "bpm", "first_beat", "key"} detected from the sound"""
    audio, rate = decode(path)
    x, sr = _mono(audio, rate)
    beat = detect_bpm(x, sr, phase=True)
    bpm, first = beat if beat else (None, None)
    return {"seconds": round(len(audio) / rate, 1), "bpm": bpm, "first_beat": first, "key": detect_key(x, sr)}


# ---------------------------------------------------------------- the folder

def tracks(folder=MUSIC):
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for top, dirs, files in os.walk(folder):    # (hidden folders skipped: a drive's .Trashes, .Spotlight-V100)
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "System Volume Information")
        out += [Path(top) / f for f in files if Path(f).suffix.lower() in AUDIO and not f.startswith(".")]
    return sorted(out)


def listing(folder, cache_file=None):
    """{rel: entry} of every track in folder: the cache's entry where the scan has looked at it, its file name for
    a title (no BPM, no key) where it hasn't yet"""
    cache = load_cache(folder, cache_file)
    out = {}
    for path in tracks(folder):
        rel = str(path.relative_to(folder))
        out[rel] = cache.get(rel) or {"title": path.stem, "artist": ""}
    return out


def load_cache(folder=MUSIC, cache_file=None):
    try:
        return json.loads((cache_file or folder / CACHE).read_text())
    except (OSError, ValueError):
        return {}


def scan(folder=MUSIC, redetect=False, progress=lambda done, total, name: None, cache_file=None):
    """every track's entry, the cache updated: from its tags, detected where they lack BPM or key (detected values
    kept apart: "bpm_detected", "key_detected", so the tags' win and both can be compared)"""
    cache_file = cache_file or folder / CACHE
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache(folder, cache_file)
    out, files = {}, tracks(folder)
    for i, path in enumerate(files):
        rel = str(path.relative_to(folder))
        st = path.stat()
        entry = cache.get(rel)
        if entry and entry.get("size") == st.st_size and entry.get("mtime") == int(st.st_mtime) and not redetect:
            out[rel] = entry
            continue
        progress(i, len(files), rel)
        tags = read_tags(path)
        entry = {"size": st.st_size, "mtime": int(st.st_mtime), **tags,
                 "title": tags["title"] or path.stem, "artist": tags["artist"] or ""}
        if redetect or not tags["bpm"] or not tags["key"] or tags["first_beat"] is None:
            try:
                found = analyse(path)
            except (OSError, subprocess.CalledProcessError, ValueError) as e:
                entry["error"] = str(e)[:80]
                found = {}
            entry["seconds"] = found.get("seconds")
            entry["bpm_detected"], entry["key_detected"] = found.get("bpm"), found.get("key")
            entry["bpm"] = entry["bpm"] or found.get("bpm")
            if entry.get("first_beat") is None:
                entry["first_beat"] = found.get("first_beat")
            entry["key"] = entry["key"] or found.get("key")
        entry["camelot"] = camelot(entry["key"])
        out[rel] = entry
        tmp = cache_file.with_name(cache_file.name + ".tmp")   # written as it goes: a long scan cut short
        tmp.write_text(json.dumps(out, indent=1))                # keeps what it did
        tmp.replace(cache_file)
    cache_file.write_text(json.dumps(out, indent=1))
    return out


# ---------------------------------------------------------------- USB drives

def port_base(name):
    """a MIDI port's name without ALSA's client:port numbers on its end (they can change from boot to boot)"""
    return re.sub(r"\s+\d+:\d+$", "", name)


def learned(folder=None):
    """{controller's port name: [binding, ...]}: the controllers given a map by MIDI learn (decks.py)"""
    try:
        data = json.loads(((folder or MUSIC) / CONTROLLERS).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def usb_volumes(tree=None):
    """[{"path", "label", "uuid", "mountpoint"}]: the filesystems on USB drives (lsblk: a disk's TRAN is "usb", a
    partition's parent disk is its PKNAME; a list or a tree, as lsblk's version gives it; a drive with no partitions
    is its own filesystem)"""
    if tree is None:
        try:
            tree = json.loads(subprocess.run(["lsblk", "-J", "-p", "-o", "PATH,PKNAME,FSTYPE,LABEL,UUID,MOUNTPOINT,TRAN"],
                                             capture_output=True, text=True, timeout=5).stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            return []
    devices, todo = [], list(tree.get("blockdevices") or [])
    while todo:                                # (a tree flattened: each child knows its disk)
        dev = todo.pop(0)
        kids = dev.get("children") or []
        for kid in kids:
            kid.setdefault("pkname", dev.get("path"))
        devices.append(dev)
        todo[:0] = kids
    usb = {dev.get("path") for dev in devices if dev.get("tran") == "usb"}
    return [{"path": dev["path"], "label": dev.get("label") or "", "uuid": dev["uuid"],
             "mountpoint": dev.get("mountpoint")}
            for dev in devices
            if (dev.get("path") in usb or dev.get("pkname") in usb) and dev.get("fstype") in MOUNTABLE
            and dev.get("uuid")]


def mount(path):
    """a USB filesystem mounted read-only by udisks (as the bridge's user, no password: the polkit rule) -> True if
    it was"""
    try:
        return subprocess.run(["udisksctl", "mount", "--no-user-interaction", "-o", "ro", "-b", path],
                              capture_output=True, text=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def usb_music(tried=None):
    """[{"name", "folder", "uuid"}]: each USB drive's filesystem, mounted if it isn't (tried: the paths a mount
    failed on, {path: False}, so one isn't tried again until it's plugged in again; one that mounted isn't kept,
    so pulled out and back in between two looks it's mounted again)"""
    tried = {} if tried is None else tried
    volumes = usb_volumes()
    for gone in set(tried) - {v["path"] for v in volumes}:
        del tried[gone]
    if any(not v["mountpoint"] and v["path"] not in tried for v in volumes):
        for v in volumes:
            if not v["mountpoint"] and v["path"] not in tried and not mount(v["path"]):
                tried[v["path"]] = False
        volumes = usb_volumes()
    return [{"name": v["label"] or v["uuid"], "folder": Path(v["mountpoint"]), "uuid": v["uuid"]}
            for v in volumes if v["mountpoint"]]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["scan"]:
        scan(redetect="--redetect" in argv, progress=lambda i, n, name: print(f"{i + 1}/{n} {name}", flush=True))
        return 0
    if argv[:1] == ["list"]:
        print(json.dumps(load_cache(), indent=1))
        return 0
    if argv[:1] == ["usb"]:
        tried = {}
        for drive in usb_music(tried):
            print(f"{drive['name']}  {drive['folder']}  {len(tracks(drive['folder']))} tracks")
        for path, ok in tried.items():
            if not ok:
                print(f"{path}: couldn't mount it (the polkit rule: install.sh)")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
