"""X0X's backups (.x0b), an FM-1 running X0X's own format: read and checked before a restore, described for the
library's listing (library.py, mvave.py move them to and from the FM-1).

A backup (.x0b, X0X's firmware/src/backup.c):

  head    "X0XB", u16 version 1, u16 count 6, u32 flags (bit 0: changes not yet saved left out), u32 CRC-32 of
          the 12 bytes before
  6 records, objects 0 1 2 3 5 6 (settings, sounds, patterns 1-16, 17-32, song, knob motion; not 4, the panel's
          calibration): u16 id, u16 length, u32 CRC-32 of the payload, the payload
  tail    u32 CRC-32 of everything before

X0X's break loops (its sample slots) aren't in it.
"""
import struct
import zlib

OBJ_MAX = 3840
OBJECTS = (0, 1, 2, 3, 5, 6)
NAMES = {0: "settings", 1: "sounds", 2: "patterns 1-16", 3: "patterns 17-32", 5: "song", 6: "knob motion"}


class X0XError(Exception):
    pass


def crc32(data):
    return zlib.crc32(data) & 0xFFFFFFFF


def make_backup(now, flags=0):
    """the .x0b image of objects (id -> bytes or None)"""
    head = b"X0XB" + struct.pack("<HHI", 1, len(OBJECTS), flags)
    out = [head, struct.pack("<I", crc32(head))]
    for o in OBJECTS:
        data = now.get(o) or b""
        out.append(struct.pack("<HHI", o, len(data), crc32(data)) + data)
    image = b"".join(out)
    return image + struct.pack("<I", crc32(image))


def read_backup(image):
    """objects {id: bytes or None} from a .x0b image, everything checked first (as X0X's restore checks it)"""
    if len(image) < 16 + 8 * len(OBJECTS) + 4 or image[:4] != b"X0XB":
        raise X0XError("not an X0X backup")
    version, count, flags = struct.unpack_from("<HHI", image, 4)
    if version != 1 or count != len(OBJECTS) or struct.unpack_from("<I", image, 12)[0] != crc32(image[:12]):
        raise X0XError("an X0X backup this version can't read")
    pos, objects = 16, {}
    for want in OBJECTS:
        if pos + 8 > len(image):
            raise X0XError("damaged: cut short")
        o, length, crc = struct.unpack_from("<HHI", image, pos)
        data = image[pos + 8:pos + 8 + length]
        if o != want or length > OBJ_MAX or len(data) != length:
            raise X0XError("damaged: a part's header")
        if crc32(data) != crc:
            raise X0XError("damaged: a part's CRC-32")
        objects[o] = data if length else None
        pos += 8 + length
    if pos + 4 != len(image) or struct.unpack_from("<I", image, pos)[0] != crc32(image[:pos]):
        raise X0XError("damaged: the whole file's CRC-32")
    return objects


def describe(image):
    """{"parts": [names of what's in it]} for the listing, or {"damaged": True}"""
    try:
        objects = read_backup(image)
    except X0XError:
        return {"damaged": True}
    return {"parts": [NAMES[o] for o in OBJECTS if objects.get(o)]}
