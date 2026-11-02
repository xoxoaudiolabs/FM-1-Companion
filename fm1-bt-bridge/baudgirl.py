"""Baud Girl's FM-1+VA (closed source; baudgirl.com): its 128 presets backed up and put back over USB. Not from her
source: from what the community worked out of her web tools (jbschooley/Virtual-FM-1's Fm1Codec, mene311/fm1-pulses),
so an update of hers may change it. Not tried on an FM-1 running it here.

  read a preset    F0 43 00 7D 10 <slot> <ysum> F7
  its reply        F0 7D <bitstream-packed: 7D 50 status arg(4 LE) len(2 LE) data sum> F7; data: the DX7 packed voice
                   (128 bytes) and her settings record (59: effects, the engine marker 5A VA / A5 FM / C3 8-Bit, its
                   filter, the envelope); status 0 done, 1 out of range, 2 damaged, 3 the sequencer plays
  write a preset   F0 43 00 7D 04 <slot> <the voice unpacked, 155> <the record, 8-into-7> <ysum> F7  (231 bytes),
                   stored to flash; no reply, so each is read back and compared

ysum: the sum of (b ^ FF) over the payload, low 7 bits. Replies come over USB only. Her patterns are left out: they
can only be read at memory addresses that change from version to version."""
import base64
import queue
import time
from datetime import datetime

import dx7
import sloop  # (puts vendor/sloop on the path)
import fm1_install  # noqa: E402

FORMAT = "fm1va-presets"
SLOTS, VOICE, RECORD = 128, 128, 59
STATUS = {1: "a value out of range", 2: "damaged on the way", 3: "the sequencer plays: stop it first"}


def ysum(data):
    return sum(b ^ 0xFF for b in data) & 0x7F


def pack87(data):
    """groups of 7 bytes, each after a byte of their top bits (as sloop.pack7)"""
    return sloop.pack7(data)


def request(body):
    return [0x43, 0x00, 0x7D, *body, ysum(body)]


def parse_reply(d):
    """an FM-1+VA reply (SysEx data, no F0 / F7) -> (kind, status, arg, data) or None"""
    if not d or d[0] != 0x7D or any(b > 127 for b in d):
        return None
    buf = fm1_install.unpack7(bytes(d[1:]))
    if len(buf) < 10 or buf[0] != 0x7D:
        return None
    n = buf[7] | buf[8] << 8
    if len(buf) < 10 + n or (~sum(buf[:9 + n])) & 0xFF != buf[9 + n]:
        return None
    return buf[1], buf[2], int.from_bytes(buf[3:7], "little"), bytes(buf[9:9 + n])


def read_preset(link, slot, timeout=1.5):
    """-> (voice 128 bytes, record 59 bytes) of a stored preset"""
    while not link.raw.empty():
        link.raw.get_nowait()
    link.out.send(link.mido.Message("sysex", data=request([0x10, slot])))
    end = time.monotonic() + timeout * link.time_scale
    while (left := end - time.monotonic()) > 0:
        try:
            r = parse_reply(link.raw.get(timeout=left))
        except queue.Empty:
            break
        if not r or r[0] != 0x50:
            continue
        kind, status, arg, data = r
        if status:
            raise sloop.SloopError("stop" if status == 3 else "rc", f"preset {slot + 1}: "
                                   + STATUS.get(status, f"status {status}"))
        if arg != slot or len(data) != VOICE + RECORD:
            raise sloop.SloopError("bad", f"preset {slot + 1}: the wrong reply")
        return data[:VOICE], data[VOICE:]
    raise sloop.SloopError("noreply", f"preset {slot + 1}: no answer from the FM-1")


def write_preset(link, slot, voice, record):
    """a preset stored, then read back: the write itself isn't answered"""
    payload = list(dx7.unpack(voice)) + pack87(record)
    link.out.send(link.mido.Message("sysex", data=[0x43, 0x00, 0x7D, 0x04, slot, *payload, ysum(payload)]))
    time.sleep(0.15 * link.time_scale)        # (a flash write: give it a moment before asking)
    if read_preset(link, slot, timeout=3.0) != (bytes(voice), bytes(record)):
        raise sloop.SloopError("rc", f"preset {slot + 1}: the FM-1 didn't keep it (nothing after it was written)")


def backup(link, firmware, progress=lambda done, total: None):
    """all 128 presets as an fm1va-presets file (dict)"""
    presets = []
    for slot in range(SLOTS):
        voice, record = read_preset(link, slot)
        presets.append({"slot": slot, "voice": base64.b64encode(voice).decode(),
                        "record": base64.b64encode(record).decode()})
        progress(slot + 1, SLOTS)
    return {"format": FORMAT, "version": 1, "firmware": firmware,
            "date": datetime.now().astimezone().isoformat(timespec="seconds"), "presets": presets}


def presets_of(file):
    """an fm1va-presets file -> {slot: (voice, record)}, every preset checked"""
    if not isinstance(file, dict) or file.get("format") != FORMAT or not isinstance(file.get("presets"), list):
        raise sloop.SloopError("bad", "not an FM-1+VA presets backup")
    out = {}
    for p in file["presets"]:
        try:
            voice, record = base64.b64decode(p["voice"]), base64.b64decode(p["record"])
        except (KeyError, TypeError, ValueError):
            raise sloop.SloopError("bad", "a preset is damaged")
        if not isinstance(p.get("slot"), int) or not 0 <= p["slot"] < SLOTS or len(voice) != VOICE \
                or len(record) != RECORD or any(b > 127 for b in voice[:118]):
            raise sloop.SloopError("bad", f"preset {p.get('slot')}: damaged")
        try:
            dx7.unpack(voice)
        except dx7.DX7Error as e:
            raise sloop.SloopError("bad", f"preset {p['slot'] + 1}: {e}")
        out[p["slot"]] = (voice, record)
    return out


def restore(link, file, progress=lambda done, total: None):
    """every preset in the file back into its slot, each read back"""
    presets = presets_of(file)
    for n, (slot, (voice, record)) in enumerate(sorted(presets.items()), 1):
        write_preset(link, slot, voice, record)
        progress(n, len(presets))


def describe(file):
    """{"firmware", "made", "presets": count, "engines": {FM, VA, 8-Bit: count}} for the listing"""
    presets = presets_of(file)
    names = {0x5A: "VA", 0xA5: "FM", 0xC3: "8-Bit"}
    engines = {}
    for _, record in presets.values():
        name = names.get(record[18], "?")
        engines[name] = engines.get(name, 0) + 1
    return {"firmware": file.get("firmware"), "made": file.get("date"), "presets": len(presets), "engines": engines,
            "projects": [], "samples": []}
