"""M-VAVE's own SysEx frames (00 59 ..., packed as a 7-bit bitstream; vendor/sloop/fm1_install.py has the same
framing for updates): who an FM-1 is, by the handshake that every firmware's updater answers, and on M-VAVE's stock
firmware only, the sound it plays now.

  handshake    F0 00 32 45 00 00 00 40 7F F7 -> 00 59 11 ..., the package id at bytes 6..32: "FM-1_015" (stock V15)
  read voice   00 59 23 len(3) [05, offset(4), 155, 0, 0] ~sum -> the reply's bytes 14.. (less the checksum): the
               voice as a DX7 single voice's 155 parameters (czietz/fm1-read-voice, tested by its author on V14, V15)

Which firmware an id is (from community research, 2026-11-02; jbschooley/Virtual-FM-1 Fm1Codec.h, charlesvestal/
fm1-x0x): FM-1_0..19 M-VAVE's stock, 20 and up Baud Girl's FM-1+VA, 8xx... FoMni and FM1 Open, 9xx... Felucca and
its forks. The read is sent to stock only: on another firmware's updater command 23 may mean something else. Not
tried on a stock FM-1 here."""
import queue
import time

import sloop  # noqa: F401  (puts vendor/sloop on the path)
import fm1_install

HS = list(fm1_install.HS_QUERY[1:-1])
READ, VOICE_SUB, VOICE_LEN = 0x23, 5, 155


def frame(cmd, payload):
    """an M-VAVE command: 00 59 cmd, the payload's length (3 bytes), the payload, its checksum; packed"""
    n = len(payload)
    body = bytes([0x00, 0x59, cmd, n & 0xFF, (n >> 8) & 0xFF, (n >> 16) & 0xFF]) + bytes(payload)
    return list(fm1_install.pack7(body + bytes([~sum(payload) & 0xFF])))


def kind(ident):
    """"stock", "baudgirl", "felucca" (and its forks), "fomni" (8xx..., FM1 Open too) or None, from an Identity"""
    if not ident or ident.model != "FM-1":
        return None
    v = ident.version
    if len(ident.text.split("_")[1]) >= 3 and str(v).startswith("9"):
        return "felucca"
    if len(ident.text.split("_")[1]) >= 3 and str(v).startswith("8"):
        return "fomni"
    return "stock" if v <= 19 else "baudgirl" if v < 700 else None   # (her V102: FM-1_102 likely; 700: Skiff's dev)


def ask(link, data, parse, timeout=1.5):
    """send one frame on link (sloop.Link) and wait for the first reply parse() takes (not None)"""
    while not link.raw.empty():
        link.raw.get_nowait()
    link.out.send(link.mido.Message("sysex", data=data))
    end = time.monotonic() + timeout * link.time_scale
    while (left := end - time.monotonic()) > 0:
        try:
            got = link.raw.get(timeout=left)
        except queue.Empty:
            break
        found = parse(got)
        if found is not None:
            return found
    return None


def identity(link, tries=2):
    """the FM-1's Identity (fm1_install), or None if it doesn't answer the handshake"""
    for _ in range(tries):
        ident = ask(link, HS, lambda d: fm1_install.parse_identity(bytes([0xF0, *d, 0xF7])))
        if ident:
            return ident
    return None


def read_voice(link):
    """the voice a stock FM-1 plays now: 155 bytes (a DX7 voice's parameters), checked"""
    def parse(d):
        u = fm1_install.unpack7(bytes(d))
        if len(u) < 15 or u[:3] != bytes([0x00, 0x59, READ]):
            return None
        return u[0x0E:-1]
    voice = ask(link, frame(READ, [VOICE_SUB, 0, 0, 0, 0, VOICE_LEN, 0, 0]), parse, timeout=2.0)
    if voice is None:
        raise sloop.SloopError("noreply", "the FM-1 didn't send its sound")
    if len(voice) != VOICE_LEN or any(b > 127 for b in voice):
        raise sloop.SloopError("bad", "the FM-1's sound came back damaged")
    return bytes(voice)


# ---------------------------------------------------------------- X0X's project backup (charlesvestal/fm1-x0x)
# Its tools/x0x_backup.py and firmware/src/backup.c: in these frames too. Backup: the host sends 42 "X0XB"; X0X
# streams 42 frames (u32 offset, then up to 128 bytes of the .x0b) and ends with 43 (u32 length, CRC-32, status,
# flags: bit 0 changes not saved yet left out). It plays on meanwhile. Restore: the host sends 41 (u32 length,
# CRC-32); X0X reads the file from us with the updater's read requests (30), checks every part and the whole, asks
# on its screen RESTORE FROM USB? (SEL yes, HOME no; 60 s), and answers with the address it reads: C0000000 done,
# C1000000 asking, CF0000xx failed (10 playing, 11 HOME). Refused while it plays. Not tried here.

X0X_RESTORE, X0X_BACKUP, X0X_END = 0x41, 0x42, 0x43
X0X_OK, X0X_ASK, X0X_FAIL = 0xC0000000, 0xC1000000, 0xCF000000
X0X_PLAYING, X0X_DECLINED = 10, 11
X0X_ERRORS = {1: "the file's size", 2: "the transfer", 3: "the file's head", 4: "a part's header",
              5: "a part's CRC-32", 6: "the whole file's CRC-32", 7: "a flash erase", 8: "a flash write",
              9: "the read-back", 12: "writing the headers (it finishes when switched on again)"}


def parse_frame(d):
    """an M-VAVE frame (SysEx data, no F0 / F7) -> (cmd, body) or None"""
    u = fm1_install.unpack7(bytes(d))
    if len(u) < 7 or u[:2] != b"\x00\x59":
        return None
    n = u[3] | u[4] << 8 | u[5] << 16
    if n + 7 != len(u) or ~sum(u[6:6 + n]) & 0xFF != u[6 + n]:
        return None
    return u[2], u[6:6 + n]


def x0x_backup(link, progress=lambda done, total: None):
    """X0X's project as a .x0b image -> (image, flags), checked against its end frame"""
    import struct
    import zlib
    while not link.raw.empty():
        link.raw.get_nowait()
    link.out.send(link.mido.Message("sysex", data=frame(X0X_BACKUP, b"X0XB")))
    got, wait = bytearray(), 3.0
    while True:
        try:
            d = link.raw.get(timeout=wait * link.time_scale)
        except queue.Empty:
            raise sloop.SloopError("noreply", "X0X stopped sending" if got else "X0X didn't answer (an X0X without backup?)")
        f = parse_frame(d)
        if not f:
            continue
        cmd, body = f
        if cmd == X0X_BACKUP and len(body) >= 4:
            if struct.unpack_from("<I", body)[0] != len(got):
                raise sloop.SloopError("rc", "a piece of X0X's backup went missing: try again")
            got += body[4:]
            wait = 10.0
            progress(len(got), max(len(got), 1))
        elif cmd == X0X_END and len(body) >= 10:
            n, crc, status, flags = struct.unpack_from("<IIBB", body)
            if status:
                raise sloop.SloopError("rc", f"X0X couldn't read its flash (status {status})")
            if n != len(got) or crc != zlib.crc32(got) & 0xFFFFFFFF:
                raise sloop.SloopError("rc", "X0X's backup arrived damaged: try again")
            return bytes(got), flags


def x0x_restore(link, image, progress=lambda done, total: None, asking=lambda: None):
    """a .x0b (checked by the caller) onto X0X: it pulls the file, then asks on its screen. -> 0 restored, else its
    failure code (X0X_PLAYING, X0X_DECLINED, X0X_ERRORS)"""
    import struct
    import zlib
    while not link.raw.empty():
        link.raw.get_nowait()
    link.out.send(link.mido.Message("sysex", data=frame(X0X_RESTORE, struct.pack("<II", len(image),
                                                                                  zlib.crc32(image) & 0xFFFFFFFF))))
    wait = 3.0
    while True:
        try:
            d = link.raw.get(timeout=wait * link.time_scale)
        except queue.Empty:
            raise sloop.SloopError("noreply", "X0X stopped asking: nothing changed" if wait > 3 else
                                   "X0X didn't answer (an X0X without restore?)")
        r = fm1_install.parse_request(bytes([0xF0, *d, 0xF7]))
        if not r:
            continue
        fl, addr, n = r
        wait = 10.0
        if addr & 0xFF000000 in (X0X_OK, X0X_ASK, X0X_FAIL):
            link.out.send(link.mido.Message("sysex", data=list(fm1_install.response(addr, b"success\0", fl)[1:-1])))
            if addr == X0X_ASK:
                asking()
                wait = 75.0                   # (its question waits 60 s for SEL or HOME)
                continue
            return 0 if addr == X0X_OK else (addr & 0xFFFF) or 99
        if n > fm1_install.MAXDATA or addr >= len(image):
            raise sloop.SloopError("rc", "X0X asked for more than the backup holds")
        data = image[addr:addr + n]
        link.out.send(link.mido.Message("sysex", data=list(fm1_install.response(addr, data + bytes(n - len(data)),
                                                                                 fl)[1:-1])))
        progress(min(addr + n, len(image)), len(image))
