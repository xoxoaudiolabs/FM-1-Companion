"""X0X's project on the Studio (X0X for the FM-1 Companion Studio): backups in X0X's own .x0b format, so a backup
made here restores onto an FM-1 running X0X (its backup page or tools/x0x_backup.py) and the other way round.

The Studio's X0X keeps what an FM-1's X0X keeps in its flash in one file, store.bin (studio/x0x_studio.c):

  u32 magic "X00S", u32 objects (7), u32 bytes per object (3840), i32 length[7], i32 length before[7],
  the objects [7][3840], the copies before them [7][3840]      (little-endian; length -1: none)

A backup (.x0b, X0X's firmware/src/backup.c):

  head    "X0XB", u16 version 1, u16 count 6, u32 flags (bit 0: changes not yet saved left out), u32 CRC-32 of
          the 12 bytes before
  6 records, objects 0 1 2 3 5 6 (settings, sounds, patterns 1-16, 17-32, song, knob motion; not 4, the panel's
          calibration): u16 id, u16 length, u32 CRC-32 of the payload, the payload
  tail    u32 CRC-32 of everything before

X0X's break loops (its sample slots) are in neither: the Studio's X0X has none yet.
"""
import struct
import zlib
from pathlib import Path

STATE = Path.home() / ".local" / "share" / "x0x-companion-studio" / "store.bin"
STATE_MAGIC, NOBJ, OBJ_MAX = 0x53303058, 7, 3840
OBJECTS = (0, 1, 2, 3, 5, 6)
NAMES = {0: "settings", 1: "sounds", 2: "patterns 1-16", 3: "patterns 17-32", 5: "song", 6: "knob motion"}


class X0XError(Exception):
    pass


def crc32(data):
    return zlib.crc32(data) & 0xFFFFFFFF


def read_state(path=STATE):
    """(objects {id: bytes or None}, before {id: bytes or None}) from store.bin; empty when there's none yet"""
    path = Path(path)
    if not path.exists():
        return {}, {}
    raw = path.read_bytes()
    head = 12 + 8 * NOBJ
    if len(raw) < head:
        raise X0XError(f"{path.name}: too short")
    magic, nobj, size = struct.unpack_from("<3I", raw)
    if magic != STATE_MAGIC or nobj != NOBJ or size != OBJ_MAX or len(raw) != head + 2 * NOBJ * OBJ_MAX:
        raise X0XError(f"{path.name}: not X0X's store")
    lens = struct.unpack_from(f"<{NOBJ}i", raw, 12)
    plens = struct.unpack_from(f"<{NOBJ}i", raw, 12 + 4 * NOBJ)
    now, before = {}, {}
    for o in range(NOBJ):
        at, pat = head + o * OBJ_MAX, head + (NOBJ + o) * OBJ_MAX
        now[o] = raw[at:at + lens[o]] if 0 <= lens[o] <= OBJ_MAX else None
        before[o] = raw[pat:pat + plens[o]] if 0 <= plens[o] <= OBJ_MAX else None
    return now, before


def write_state(now, before, path=STATE):
    """store.bin from objects (id -> bytes or None), written whole to a new file then put in place"""
    path = Path(path)
    body = [struct.pack("<3I", STATE_MAGIC, NOBJ, OBJ_MAX)]
    lens = [len(now[o]) if now.get(o) is not None else -1 for o in range(NOBJ)]
    plens = [len(before[o]) if before.get(o) is not None else -1 for o in range(NOBJ)]
    body.append(struct.pack(f"<{NOBJ}i", *lens))
    body.append(struct.pack(f"<{NOBJ}i", *plens))
    for objs in (now, before):
        for o in range(NOBJ):
            body.append((objs.get(o) or b"").ljust(OBJ_MAX, b"\0"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(b"".join(body))
    tmp.replace(path)


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


def backup(path, state=STATE):
    """the Studio's X0X project (what it has saved) into a .x0b file"""
    now, _ = read_state(state)
    if not any(now.get(o) for o in OBJECTS):
        raise X0XError("X0X on the Studio has nothing saved yet")
    Path(path).write_bytes(make_backup(now))
    return path


def restore(path, state=STATE):
    """a .x0b's project into the Studio's X0X (it must not be running): each object replaced, the one before kept
    as X0X keeps it, the panel's calibration left as it is"""
    objects = read_backup(Path(path).read_bytes())
    now, before = read_state(state)
    for o in OBJECTS:
        before[o] = now.get(o)
        now[o] = objects[o]
    write_state(now, before, state)


def describe(image):
    """{"parts": [names of what's in it]} for the listing, or {"damaged": True}"""
    try:
        objects = read_backup(image)
    except X0XError:
        return {"damaged": True}
    return {"parts": [NAMES[o] for o in OBJECTS if objects.get(o)]}
