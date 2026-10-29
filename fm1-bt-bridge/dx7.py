"""Yamaha DX7 patches for FM-1 firmwares that take them: .syx files read, voices named, a bank's voices unpacked to
single voices, and the two standard DX7 SysEx messages made to send.

  a 32-voice bank   F0 43 0n 09 20 00, 4096 bytes (32 voices of 128, packed), checksum, F7: 4104 bytes
  a single voice    F0 43 0n 00 01 1B, 155 bytes (one parameter each), checksum, F7: 163 bytes

The checksum is the low 7 bits of minus the data's sum. What a firmware does with them (from community research,
not tried here yet): M-VAVE's stock firmware asks on its own screen which bank a bank dump replaces, and puts a single
voice on the selected preset; Baud Girl's FM-1+VA asked "Replace Bank A?" for a bank dump until FM-1_079, which takes
no bank dump; firmwares that take only single voices get each voice of a bank on its own. SLOOP and Clipper (isod89's)
don't take DX7 SysEx: the library doesn't send it to them. Nothing else is ever sent: no M-VAVE updater messages."""
from pathlib import Path

BANK_HEAD = bytes([0xF0, 0x43, 0x00, 0x09, 0x20, 0x00])
VOICE_HEAD = bytes([0xF0, 0x43, 0x00, 0x00, 0x01, 0x1B])
BANK_SIZE, VOICE_SIZE = 4104, 163
VOICES = 32


class DX7Error(ValueError):
    pass


def checksum(data):
    return (-sum(data)) & 0x7F


def bank_message(voices, channel=0):
    """32 packed voices (128 bytes each) -> a bank dump"""
    data = b"".join(voices)
    if len(voices) != VOICES or len(data) != VOICES * 128:
        raise DX7Error("a bank is 32 voices")
    return bytes([0xF0, 0x43, channel & 15, 0x09, 0x20, 0x00]) + data + bytes([checksum(data), 0xF7])


def voice_message(voice, channel=0):
    """an unpacked voice (155 bytes) -> a single-voice dump"""
    if len(voice) != 155:
        raise DX7Error("a voice is 155 bytes")
    return bytes([0xF0, 0x43, channel & 15, 0x00, 0x01, 0x1B]) + bytes(voice) + bytes([checksum(voice), 0xF7])


def messages(raw):
    """the SysEx messages in a file's bytes (a .syx can hold several)"""
    out, start = [], None
    for i, b in enumerate(raw):
        if b == 0xF0:
            start = i
        elif b == 0xF7 and start is not None:
            out.append(raw[start:i + 1])
            start = None
    return out


def read(raw):
    """a .syx's bytes -> ("bank", [32 packed voices]) or ("voice", unpacked voice), checked"""
    for m in messages(raw):
        if len(m) == BANK_SIZE and m[1] == 0x43 and m[3:6] == bytes([0x09, 0x20, 0x00]):
            data = m[6:6 + 4096]
            if checksum(data) != m[-2]:
                raise DX7Error("the bank's checksum is wrong: damaged")
            return "bank", [data[i * 128:(i + 1) * 128] for i in range(VOICES)]
        if len(m) == VOICE_SIZE and m[1] == 0x43 and m[3:6] == bytes([0x00, 0x01, 0x1B]):
            data = m[6:6 + 155]
            if checksum(data) != m[-2]:
                raise DX7Error("the voice's checksum is wrong: damaged")
            return "voice", data
    raise DX7Error("not a DX7 bank or voice")


def name(text):
    return bytes(b if 32 <= b < 127 else 32 for b in text).decode("ascii").rstrip()


def packed_name(packed):
    return name(packed[118:128])


def voice_name(voice):
    return name(voice[145:155])


def unpack(packed):
    """a bank's packed voice (128 bytes) -> the single-voice form (155 bytes), as a DX7 does on a voice load"""
    if len(packed) != 128:
        raise DX7Error("a packed voice is 128 bytes")
    p, out = packed, []
    for op in range(6):                          # operator 6 first, 17 bytes each
        o = p[op * 17:(op + 1) * 17]
        out += list(o[0:11])                     # EG rates and levels, break point, left and right depth
        out += [o[11] & 3, (o[11] >> 2) & 3]     # left and right curve
        out += [o[12] & 7, o[13] & 3, (o[13] >> 2) & 7, o[14]]   # rate scaling, amp mod sens, velocity, level
        out += [o[15] & 1, (o[15] >> 1) & 31, o[16], (o[12] >> 3) & 15]   # osc mode, coarse, fine, detune
    out += list(p[102:110])                      # pitch EG rates and levels
    out += [p[110] & 31, p[111] & 7, (p[111] >> 3) & 1]           # algorithm, feedback, osc key sync
    out += list(p[112:116])                      # LFO speed, delay, pitch mod depth, amp mod depth
    out += [p[116] & 1, (p[116] >> 1) & 7, (p[116] >> 4) & 7]     # LFO sync, wave, pitch mod sensitivity
    out += [p[117]] + list(p[118:128])           # transpose, name
    return bytes(b & 0x7F for b in out)


def pack(voice):
    """the single-voice form (155 bytes) -> a bank's packed voice (128 bytes): unpack's inverse"""
    if len(voice) != 155:
        raise DX7Error("a voice is 155 bytes")
    v, out = voice, []
    for op in range(6):
        o = v[op * 21:(op + 1) * 21]
        out += list(o[0:11])
        out += [(o[11] & 3) | (o[12] & 3) << 2, (o[13] & 7) | (o[20] & 15) << 3, (o[14] & 3) | (o[15] & 7) << 2,
                o[16], (o[17] & 1) | (o[18] & 31) << 1, o[19]]
    g = v[126:]
    out += list(g[0:8]) + [g[8] & 31, (g[9] & 7) | (g[10] & 1) << 3] + list(g[11:15])
    out += [(g[15] & 1) | (g[16] & 7) << 1 | (g[17] & 7) << 4, g[18]] + list(g[19:29])
    return bytes(b & 0x7F for b in out)


def describe(path):
    """{"kind": "bank" / "voice", "voices": [names]} of a .syx file"""
    kind, data = read(Path(path).read_bytes())
    if kind == "bank":
        return {"kind": "bank", "voices": [packed_name(v) for v in data]}
    return {"kind": "voice", "voices": [voice_name(data)]}


def to_send(path, voice=None, channel=0):
    """what to send for a .syx: the whole bank, or one voice (0-31 of a bank; a voice file: itself) as a single
    voice"""
    kind, data = read(Path(path).read_bytes())
    if kind == "voice":
        return voice_message(data, channel)
    if voice is None:
        return bank_message(data, channel)
    if not 0 <= voice < VOICES:
        raise DX7Error("a bank's voices are 1-32")
    return voice_message(unpack(data[voice]), channel)
