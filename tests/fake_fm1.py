"""A pretend FM-1 running SLOOP, for testing the bridge's library without hardware.

It answers SLOOP's editor protocol the way firmware/src/editor.c does for the commands the bridge uses (INFO,
BK_LIST / BK_GET / BK_PUT, SMP_*, LIVE op 0) and looks like mido to sloop.Link: pass it as Link(mido=fake).
"""
import struct
import zlib

import mido

import sloop

HDR = list(sloop.HDR)


def project(fmt=6, fill=0, size=4096):
    """a project object: "FUN<fmt>" magic (stored low byte first) and some content"""
    return bytes([0x30 + fmt]) + b"NUF" + bytes((fill + i) & 0xFF for i in range(size - 4))


def sample_slot(name="TEST", n=3000):
    """a valid user sample slot object: 480-byte header padded to 512, then data"""
    data = bytes((i * 7) & 0xFF for i in range(n))
    hdr = struct.pack("<IHBB8sII8x", 0x504D5346, 1, 1, 0, name.encode().ljust(8, b"\0"), len(data), zlib.crc32(data))
    return hdr.ljust(512, b"\0") + data


class Port:
    def __init__(self, device, callback=None):
        self.device, self.callback, self.closed = device, callback, False

    def send(self, msg):
        self.device.handle(list(msg.data))

    def close(self):
        self.closed = True


class FakeFM1:
    def __init__(self, version="SLOOP 2.7.1", proto=12, pcount=71):
        self.version, self.proto, self.pcount = version, proto, pcount
        self.playing = False
        self.objects = {0: project(6, 1), 1: b"PER3" + bytes(200), 2: project(6, 2), 3: b"", 4: b"", 5: project(6, 5),
                        6: b"UPB1" + bytes(3000), 7: b"", 8: bytes(27 * 128), 9: b"DSU1" + bytes(1460),
                        32: sample_slot("KICK"), 33: b"", 34: b"", 35: b""}
        self.input, self.snapshot, self.put = None, None, None
        self.smp_open, self.smp_data = {}, {}
        self.requests, self.drop_every, self.lose_reply_every, self.mute = 0, 0, 0, False

    # mido's module interface
    Message = mido.Message

    def get_input_names(self):
        return ["Midi Through:Midi Through Port-0 14:0", "Felucca:Felucca MIDI 1 24:0"]

    get_output_names = get_input_names

    def open_input(self, name, callback=None):
        self.input = Port(self, callback)
        return self.input

    def open_output(self, name):
        return Port(self)

    # the firmware
    def reply(self, cmd, args):
        if not self.mute:
            self.input.callback(mido.Message("sysex", data=HDR + [cmd] + [a & 0x7F for a in args]))

    def handle(self, data):
        if data[:3] != HDR:
            return
        self.requests += 1
        if self.drop_every and self.requests % self.drop_every == 0:
            return                                   # a lost frame: the bridge must retry
        cmd, a = data[3], data[4:]
        # carried out, but the reply is lost (the harder case: the device moved on)
        self.mute = bool(self.lose_reply_every and self.requests % self.lose_reply_every == 0)
        handler = getattr(self, f"cmd_{cmd}", None)
        if handler:
            handler(a)
        self.mute = False

    def cmd_1(self, a):                               # INFO
        out = [*self.version.encode(), 0, 2, self.pcount, 45, 64, self.pcount - 8, *b"ANALOG", 0, *b"FM6", 0, 4]
        if self.proto:
            out.append(self.proto)
        self.reply(1, out)

    def cmd_77(self, a):                              # LIVE op 0: flags bit 0 = playing
        self.reply(77, [a[0], int(self.playing), 0] + [0] * 47)

    def listed(self):
        return [i for i in sorted(self.objects) if not (i in (10, 11) and not self.objects[i])]

    def cmd_34(self, a):                              # BK_LIST
        self.snapshot, self.put = {i: self.objects[i] for i in self.listed()}, None
        out = [0, len(self.snapshot)]
        for i, d in self.snapshot.items():
            out += [i, *sloop.u35(len(d)), *sloop.u35(zlib.crc32(d))]
        self.reply(34, out)

    def cmd_35(self, a):                              # BK_GET
        obj, off, count = a[0], sum(a[1 + k] << (7 * k) for k in range(5)), a[6] | (a[7] << 7)
        d = (self.snapshot or {}).get(obj)
        rc = 1 if d is None or not count or count > 256 or off + count > len(d) else 5 if self.snapshot is None else 0
        out = [obj, rc, *sloop.u35(off), 0 if rc else count & 127, 0 if rc else count >> 7]
        if not rc:
            out += sloop.pack7(d[off:off + count])
        self.reply(35, out)

    def cmd_36(self, a):                              # BK_PUT
        op, obj, rc = a[0], a[1], 1
        if op == 0 and obj <= 11:
            length, crc = (sum(a[s + k] << (7 * k) for k in range(5)) for s in (2, 7))
            if obj >= 2 or length:
                self.put, self.snapshot, rc = {"id": obj, "len": length, "crc": crc, "data": bytearray()}, None, 0
            if obj in (10, 11) and self.proto < 11:
                rc = 5                                  # an older device doesn't know it
        elif not self.put or self.put["id"] != obj:
            rc = 5
        elif op == 1 and sum(a[2 + k] << (7 * k) for k in range(5)) == len(self.put["data"]):
            chunk = sloop.unpack7(a[7:])
            if chunk and len(self.put["data"]) + len(chunk) <= self.put["len"]:
                self.put["data"] += chunk
                rc = 0
        elif op == 2:
            d, p = bytes(self.put["data"]), self.put
            self.put = None
            if len(d) != p["len"] or zlib.crc32(d) != p["crc"]:
                rc = 2
            elif obj in (0, 2, 3, 4, 5) and d and sloop.project_format(d) == 0:
                rc = 2
            elif self.playing and obj in (0, 1, 2, 3, 4, 5, 6, 7):
                rc = 3
            else:
                self.objects[obj], rc = d, 0
        self.reply(36, [op, obj, rc])

    def cmd_11(self, a):                              # SMP_BEGIN
        self.smp_open[a[0]], self.smp_data[a[0]] = True, bytearray()
        self.objects[32 + a[0]] = b""
        self.reply(11, [a[0], 0])

    def cmd_14(self, a):                              # SMP_ERASE
        self.objects[32 + a[0]] = b""
        self.reply(14, [a[0], 0])

    def cmd_12(self, a):                              # SMP_WRITE
        slot, off = a[0], a[1] | (a[2] << 7) | (a[3] << 14)
        rc = 4 if not self.smp_open.get(slot) else 1 if off != 512 + len(self.smp_data[slot]) else 0
        if not rc:
            self.smp_data[slot] += sloop.unpack7(a[4:])
        self.reply(12, [slot, a[1], a[2], a[3], rc])

    def cmd_13(self, a):                              # SMP_END
        slot, hdr = a[0], sloop.unpack7(a[1:])
        data = bytes(self.smp_data.get(slot, b""))
        magic, _, _, _, _, length, crc = struct.unpack_from("<IHBB8sII", hdr)
        rc = 2 if magic != 0x504D5346 else 1 if length != len(data) else 3 if crc != zlib.crc32(data) else 0
        if not rc:
            self.objects[32 + slot] = hdr[:480].ljust(512, b"\0") + data
            self.smp_open[slot] = False
        self.reply(13, [slot, rc])

    def cmd_15(self, a):                              # SMP_INFO
        out = [4, 80]
        for k in range(4):
            d = self.objects[32 + k]
            out += [d[6] if d else 0, *(d[8:16].rstrip(b"\0") if d else b""), 0, (len(d) - 512) // 1024 if d else 0]
        self.reply(15, out)


class FakeFelucca(FakeFM1):
    """Felucca 1.x as its EDITOR_PROTOCOL.md (v7) and fm1backup.js say: INFO ends with CHAIN_ROWS and tagged blocks
    ("42 01 3": backup read and restore), the full backup is 65-67 (LIST answers "1, rc, count", objects 0-9 and the
    samples 32-34), and 34-38 and 77 are other commands: anything sent there is kept in `wrong`."""

    def __init__(self, version="FELUCCA v1.9.0", caps=3):
        super().__init__(version=version, proto=0, pcount=114)
        self.caps, self.wrong = caps, []
        self.objects = {0: project(0x11, 1, 3840), 1: b"FST1" + bytes(300), 2: project(0x11, 2, 3840), 3: b"",
                        4: b"", 5: project(0x11, 5, 3840), 6: b"UPB2" + bytes(2000), 7: b"", 8: b"",
                        9: b"UPF6" + bytes(3724), 32: sample_slot("KICK"), 33: b"", 34: b""}

    def cmd_1(self, a):                               # INFO: NTRK, CHAIN_ROWS, then the tags
        out = [*self.version.encode(), 0, 2, self.pcount, 45, 64, 106, *b"ANALOG", 0, *b"FM6", 0, 4, 16,
               0x55, 1, 31, 0x4D, 1, 64, 1]
        if self.caps:
            out += [0x42, 1, self.caps]
        self.reply(1, out + [0x46, 1, 8, 0, 0x53, 1, 3])

    def other(self, a, cmd):                          # UI_STATE ... FAV_SET, FM6B_LIST: not the backup's
        self.wrong.append(cmd)

    cmd_34 = lambda self, a: self.other(a, 34)        # noqa: E731
    cmd_35 = lambda self, a: self.other(a, 35)        # noqa: E731
    cmd_36 = lambda self, a: self.other(a, 36)        # noqa: E731
    cmd_77 = lambda self, a: self.other(a, 77)        # noqa: E731

    def listed(self):
        return [i for i in sorted(self.objects)]

    def cmd_65(self, a):                              # BACKUP_LIST: it stops the transport itself
        if not self.caps & 1:
            return
        self.playing = False
        self.snapshot, self.put = {i: self.objects[i] for i in self.listed()}, None
        out = [1, 0, len(self.snapshot)]
        for i, d in self.snapshot.items():
            out += [i, *sloop.u35(len(d)), *sloop.u35(zlib.crc32(d))]
        self.reply(65, out)

    def cmd_66(self, a):                              # BACKUP_GET: rc 3 while it plays
        obj, off, count = a[0], sum(a[1 + k] << (7 * k) for k in range(5)), a[6] | (a[7] << 7)
        d = (self.snapshot or {}).get(obj)
        rc = 3 if self.playing else 1 if d is None or not count or count > 256 or off + count > len(d) else \
            5 if self.snapshot is None else 0
        out = [obj, rc, *sloop.u35(off), 0 if rc else count & 127, 0 if rc else count >> 7]
        if not rc:
            out += sloop.pack7(d[off:off + count])
        self.reply(66, out)

    def cmd_67(self, a):                              # BACKUP_PUT: ids 0-9; an id 8 with data is taken, not kept
        op, obj, rc = a[0], a[1], 1
        if op == 0 and obj <= 9 and self.caps & 2:
            self.playing = False
            length, crc = (sum(a[s + k] << (7 * k) for k in range(5)) for s in (2, 7))
            self.put, self.snapshot, rc = {"id": obj, "len": length, "crc": crc, "data": bytearray()}, None, 0
        elif not self.put or self.put["id"] != obj:
            rc = 5
        elif op == 1 and sum(a[2 + k] << (7 * k) for k in range(5)) == len(self.put["data"]):
            chunk = sloop.unpack7(a[7:])
            if chunk and len(self.put["data"]) + len(chunk) <= self.put["len"]:
                self.put["data"] += chunk
                rc = 0
        elif op == 2:
            d, p = bytes(self.put["data"]), self.put
            self.put = None
            if len(d) != p["len"] or zlib.crc32(d) != p["crc"]:
                rc = 2
            elif obj in (0, 2, 3, 4, 5) and d and d[:4] != b"ANUF":
                rc = 2                                  # (its own FUN10 only: SLOOP's projects aren't valid here)
            else:
                if obj != 8:
                    self.objects[obj] = d
                rc = 0
        elif op == 3:
            self.put, rc = None, 0
        self.reply(67, [op, obj, rc])

    def cmd_15(self, a):                              # SMP_INFO: three slots
        out = [3, 80]
        for k in range(3):
            d = self.objects[32 + k]
            out += [d[6] if d else 0, *(d[8:16].rstrip(b"\0") if d else b""), 0, (len(d) - 512) // 1024 if d else 0]
        self.reply(15, out)


def mvave_frame(body):
    """an M-VAVE reply: body (00 59 cmd ...) packed as fm1_install packs, without F0 / F7"""
    import fm1_install
    return list(fm1_install.pack7(bytes(body)))


class FakeStock(FakeFM1):
    """M-VAVE's stock firmware (V15): no SLOOP protocol at all; M-VAVE's handshake (its package id) and, as
    czietz/fm1-read-voice reads it, the current voice (command 23, sub 5). DX7 SysEx sent to it lands in `dx7`;
    every M-VAVE command it's sent, in `vendor`."""

    def __init__(self, ident="FM-1_015", voice=None):
        super().__init__(version="", proto=0)
        self.ident, self.voice = ident, voice
        self.dx7, self.vendor = [], []

    def get_input_names(self):
        return ["Midi Through:Midi Through Port-0 14:0", "FM-1:FM-1 MIDI 1 24:0"]

    get_output_names = get_input_names

    def raw_reply(self, data):
        self.input.callback(mido.Message("sysex", data=data))

    def handle(self, data):
        import fm1_install
        if data[:1] == [0x43]:
            self.dx7.append(bytes([0xF0, *data, 0xF7]))
            return
        if data == list(fm1_install.HS_QUERY[1:-1]):
            self.vendor.append("hello")
            text = self.ident.encode().ljust(27, b"\0")
            body = bytes([0x00, 0x59, 0x11, 27, 0, 0]) + text
            self.raw_reply(mvave_frame(body + bytes([~sum(text) & 0xFF])))
            return
        u = fm1_install.unpack7(bytes(data))
        if u[:2] == b"\x00\x59":
            self.vendor.append(u[2])
            if u[2] == 0x23 and u[6] == 5 and self.voice is not None:
                body = bytes([0x00, 0x59, 0x23, 0, 0, 0]) + bytes(8) + self.voice
                self.raw_reply(mvave_frame(body + bytes([~sum(self.voice) & 0xFF])))


class FakeJiant(FakeFelucca):
    """JIANT FM 0.9 (juanjiant-bit/JIANT, Felucca 1.1.5.1 based), as its EDITOR_PROTOCOL.md and fm1backup.js say:
    Felucca's 65-67 with 43 objects, 0-9 as Felucca's, 10 the song index and 40-71 every song's sections (40 + 4 x
    song + section); no sample slots. `old` (before 0.3): no songs, ids 10 and 40-71 answer rc 1 at begin."""

    def __init__(self, version="JIANT v0.9.18", old=False):
        super().__init__(version=version)
        self.old = old
        self.objects = {i: d for i, d in self.objects.items() if i < 32}
        self.objects[0] = project(0x11, 1, 3744)
        if not old:
            self.objects[10] = b"JSI1" + bytes(1324)
            for k in range(32):
                self.objects[40 + k] = project(0x11, k, 3744) if k % 5 == 0 else b""

    def cmd_67(self, a):
        if a[0] == 0 and (a[1] >= 10 and (self.old or a[1] not in self.objects)):
            self.reply(67, [0, a[1], 1])                 # (an id it doesn't know: nothing written)
            return
        if a[0] == 0 and a[1] > 9:                       # (Felucca's fake takes 0-9 only)
            length, crc = (sum(a[s + k] << (7 * k) for k in range(5)) for s in (2, 7))
            self.put, self.snapshot = {"id": a[1], "len": length, "crc": crc, "data": bytearray()}, None
            self.reply(67, [0, a[1], 0])
            return
        super().cmd_67(a)


class FakeX0X(FakeFM1):
    """X0X (charlesvestal/fm1-x0x), as its firmware/src/backup.c and tools/x0x_backup.py say: INFO "X0X <ver>" and
    nothing else of SLOOP's (anything SLOOP-only it's sent lands in `wrong`); in M-VAVE's frames, 42 "X0XB" streams
    its .x0b (42 pieces of 128 bytes, then 43), 41 makes it read a file from the host (read requests 30), check it,
    ask on its screen (`answer`: "SEL", "HOME" or None for no answer) and report at C0000000 / CF0000xx."""

    def __init__(self, version="X0X 1.0", playing=False, answer="SEL"):
        super().__init__(version=version, proto=0)
        import x0x
        self.x0x, self.playing, self.answer, self.wrong = x0x, playing, answer, []
        self.project = {0: b"SET1" + bytes(60), 1: b"SND1" + bytes(900), 2: b"PAT1" + bytes(3000), 3: b"",
                        5: b"SNG1" + bytes(200), 6: b""}
        self.unsaved = False
        self.pull = None

    def image(self):
        return self.x0x.make_backup(self.project, 1 if self.unsaved else 0)

    def cmd_1(self, a):                               # INFO: its name, no engines
        self.reply(1, [*self.version.encode(), 0, 0, 0, 0, 16, 0, 0])

    def handle(self, data):
        import fm1_install
        import mvave
        if data[:3] == HDR:
            if data[3] not in (1, 25):
                self.wrong.append(data[3])
            return super().handle(data)
        u = fm1_install.unpack7(bytes(data))
        if u[:3] == b"\x00\x59\x30" and self.pull is not None:   # the host's answer to a read request
            addr, n = int.from_bytes(u[7:11], "little"), u[11] | u[12] << 8
            self.on_answer(addr, u[14:14 + n])
            return
        f = mvave.parse_frame(data)
        if not f:
            return
        cmd, body = f
        if cmd == mvave.X0X_BACKUP and body == b"X0XB":
            image = self.image()
            for off in range(0, len(image), 128):
                self.raw(mvave.X0X_BACKUP, struct.pack("<I", off) + image[off:off + 128])
            self.raw(mvave.X0X_END, struct.pack("<IIBB", len(image), zlib.crc32(image), 0, int(self.unsaved)))
        elif cmd == mvave.X0X_RESTORE and len(body) >= 8:
            n, crc = struct.unpack_from("<II", body)
            if self.playing:
                return self.report(mvave.X0X_FAIL | mvave.X0X_PLAYING)
            self.pull = {"len": n, "crc": crc, "got": bytearray()}
            self.request(0)

    def raw(self, cmd, body):
        import mvave
        self.input.callback(mido.Message("sysex", data=mvave.frame(cmd, body)))

    def request(self, addr, n=256):
        import fm1_install
        body = bytes([0, *addr.to_bytes(4, "little"), n & 0xFF, n >> 8, 0])
        u = bytes([0x00, 0x59, 0x30, 8, 0, 0]) + body + bytes([~sum(body) & 0xFF])
        self.input.callback(mido.Message("sysex", data=list(fm1_install.pack7(u))))

    def report(self, addr):
        self.request(addr, 8)

    def on_answer(self, addr, data):
        import mvave
        p = self.pull
        if addr & 0xFF000000 in (mvave.X0X_OK, mvave.X0X_ASK, mvave.X0X_FAIL):
            if addr == mvave.X0X_ASK:                      # the question on its screen
                if self.answer == "SEL":
                    self.project = {k: v or b"" for k, v in self.x0x.read_backup(bytes(p["got"])).items()}
                    self.report(mvave.X0X_OK)
                elif self.answer == "HOME":
                    self.report(mvave.X0X_FAIL | mvave.X0X_DECLINED)
            else:
                self.pull = None
            return
        p["got"][addr:addr + len(data)] = data
        if len(p["got"]) < p["len"]:
            self.request(len(p["got"]), min(256, p["len"] - len(p["got"])))
            return
        got = bytes(p["got"][:p["len"]])
        if zlib.crc32(got) != p["crc"]:
            return self.report(mvave.X0X_FAIL | 6)
        p["got"] = bytearray(got)
        self.report(mvave.X0X_ASK)


class FakeJangada(FakeFM1):
    """Jangada 1.0 (zednaked/jangada), as its EDITOR_PROTOCOL.md (v8) and fm1backup.js say: SLOOP's BK_LIST / GET /
    PUT 34-36 and SMP_*, INFO "JANGADA 1.0.1" with protocol 8 (no LIVE), objects 0-11 (projects "JNG2", banks, two
    FM6 banks as four halves) and the samples 32-34; a commit checks a project's magic. `fm6`: firmware before 0.6
    lists no 10 / 11 and answers rc 1 at their begin. DX7 SysEx it's sent lands in `dx7`."""

    def __init__(self, version="JANGADA 1.0.1", banks2=True):
        super().__init__(version=version, proto=8, pcount=96)
        self.banks2, self.dx7 = banks2, []
        jng = lambda fill: b"JNG2" + bytes((fill + i) & 0xFF for i in range(1200))   # noqa: E731
        self.objects = {0: jng(1), 1: b"PER2" + bytes(80), 2: jng(2), 3: b"", 4: b"", 5: jng(5),
                        6: b"UPB3" + bytes(2000), 7: b"", 8: b"FM6B" + bytes(2060), 9: b"", 32: sample_slot("LOOP"),
                        33: b"", 34: b""}
        if banks2:
            self.objects.update({10: b"FM6B" + bytes(2060), 11: b""})

    def handle(self, data):
        if data[:1] == [0x43]:
            self.dx7.append(bytes([0xF0, *data, 0xF7]))
            return
        super().handle(data)

    def cmd_77(self, a):                              # (not LIVE: a parameter number on Jangada; never sent)
        raise AssertionError("LIVE sent to Jangada")

    def listed(self):
        return sorted(self.objects)

    def cmd_36(self, a):
        if a[0] == 0 and a[1] in (10, 11) and not self.banks2:
            self.reply(36, [0, a[1], 1])
            return
        if a[0] == 2 and self.put and self.put["id"] in (0, 2, 3, 4, 5):
            d = bytes(self.put["data"])
            if d and d[:4] != b"JNG2":                  # its own projects only
                self.put = None
                self.reply(36, [2, a[1], 2])
                return
            if len(d) == self.put["len"] and zlib.crc32(d) == self.put["crc"]:
                self.objects[self.put["id"]], self.put = d, None
                self.reply(36, [2, a[1], 0])
                return
        super().cmd_36(a)


class FakeSloopDX(FakeFM1):
    """sloopDX 4.0 (zvenson/dxsloop, SLOOP 2.7 as a DX7 synth), as its editor.c says: SLOOP's protocol 12 with object
    8 = the DX7 bank in use (4096 voice bytes), 8 banks switched by BANK_SELECT 46 (not while it plays), BANK_INFO
    40, and a .syx loaded by BANK_BEGIN 37 (empties the bank) / WRITE 38 / END 39 (the DX7 checksum). No samples."""

    def __init__(self, version="FELUCCA sloopDX 4.0"):
        super().__init__(version=version, proto=12, pcount=71)
        self.banks = {k: bytes((k * 7 + i) & 0x7F for i in range(4096)) if k in (0, 2, 5) else b"" for k in range(8)}
        self.cur = 2
        self.objects = {i: d for i, d in self.objects.items() if i < 32}
        self.objects.update({8: self.banks[2], 10: bytes(40), 11: b""})
        self.loading = None

    def all_banks(self):
        return {**self.banks, self.cur: self.objects[8]}

    def cmd_40(self, a):                              # BANK_INFO: ok, 32 names, the bank in use, banks
        self.reply(40, [1] + [0] * 32 + [self.cur, 8])

    def cmd_46(self, a):                              # BANK_SELECT
        if a and not self.playing:
            self.banks[self.cur] = self.objects[8]
            self.cur = a[0]
            self.objects[8] = self.banks[a[0]]
        self.reply(46, [self.cur, 8, 1])

    def cmd_37(self, a):                              # BANK_BEGIN: the bank is empty from now on
        self.objects[8], self.loading = b"", bytearray()
        self.reply(37, [0])

    def cmd_38(self, a):                              # BANK_WRITE: offset (2), voice bytes
        off = a[0] | a[1] << 7
        ok = self.loading is not None and off == len(self.loading)
        if ok:
            self.loading += bytes(a[2:])
        self.reply(38, [a[0], a[1], 0 if ok else 1])

    def cmd_39(self, a):                              # BANK_END: the DX7 checksum
        d = bytes(self.loading or b"")
        rc = 1 if len(d) != 4096 or (-sum(d)) & 0x7F != a[0] else 3 if self.playing else 0
        if not rc:
            self.objects[8] = d
        self.loading = None
        self.reply(39, [rc])


class FakeClipper(FakeFM1):
    """Clipper 1.3 (isod89/clipper-fm1, a synth from SLOOP 2.5), as its editor.c says: SLOOP's BK_* with ids 0-9 (8 the
    FM6 bank, 9 the SYN kits; no 10, 11), 3 sample slots (its wavetables) 32-34, protocol 14; 77 is HY_GET there, not
    LIVE, and 37 LOCK_GET: anything sent on those lands in `wrong`. Its writes answer rc 3 while it plays."""

    def __init__(self, version="FELUCCA CLIPPER 1.3"):
        super().__init__(version=version, proto=14, pcount=126)
        self.wrong = []
        self.objects = {i: d for i, d in self.objects.items() if i <= 9 or 32 <= i <= 34}
        self.objects[0], self.objects[2] = project(5, 1), project(5, 2)
        self.objects[5] = project(5, 5)

    def cmd_77(self, a):
        self.wrong.append(77)

    def cmd_37(self, a):
        self.wrong.append(37)

    def cmd_36(self, a):
        if a[0] == 0 and a[1] > 9:
            self.reply(36, [0, a[1], 1])
            return
        super().cmd_36(a)

    def cmd_15(self, a):                              # SMP_INFO: three slots
        out = [3, 80]
        for k in range(3):
            d = self.objects[32 + k]
            out += [d[6] if d else 0, *(d[8:16].rstrip(b"\0") if d else b""), 0, (len(d) - 512) // 1024 if d else 0]
        self.reply(15, out)


class FakeMelodee(FakeFelucca):
    """Melodee 1.6 (keremimo/melodee, Felucca based), as its EDITOR_PROTOCOL.md and fm1backup.js say: Felucca's 65-67
    with 57 objects (0-28, its projects 5-32 at 64-91, projects of FUN22 "FUNI" up to 27936 bytes), id 8 always empty
    and refusing a payload, no sample slots; it takes DX7 SysEx (in `dx7`)."""

    def __init__(self, version="MELODEE v1.6.0"):
        super().__init__(version=version)
        self.dx7 = []
        funi = lambda fill, n=6000: project(0x19, fill, n)          # noqa: E731  ("FUNI": 0x30 + 0x19 = "I")
        self.objects = {i: (b"UPB9" + bytes(1000 + i) if i % 3 else b"") for i in range(29)}
        self.objects.update({0: funi(1, 9000), 1: b"PER9" + bytes(200), 2: funi(2), 3: b"", 4: b"", 5: funi(5),
                             8: b""})
        self.objects.update({64 + k: funi(64 + k) if k % 9 == 0 else b"" for k in range(28)})

    def handle(self, data):
        if data[:1] == [0x43]:
            self.dx7.append(bytes([0xF0, *data, 0xF7]))
            return
        super().handle(data)

    def cmd_67(self, a):
        op, obj = a[0], a[1]
        if op == 0:
            length = sum(a[2 + k] << (7 * k) for k in range(5))
            if not (obj <= 28 or 64 <= obj < 92) or (obj == 8 and length):
                return self.reply(67, [0, obj, 1])
            crc = sum(a[7 + k] << (7 * k) for k in range(5))
            self.put, self.snapshot = {"id": obj, "len": length, "crc": crc, "data": bytearray()}, None
            return self.reply(67, [0, obj, 0])
        if op == 2 and self.put and self.put["id"] == obj:
            d, p = bytes(self.put["data"]), self.put
            self.put = None
            ok = len(d) == p["len"] and zlib.crc32(d) == p["crc"]
            if ok and d and (obj in (0, 2, 3, 4, 5) or obj >= 64) and d[:4] != b"INUF":
                ok = False
            if ok:
                self.objects[obj] = d
            return self.reply(67, [2, obj, 0 if ok else 2])
        super().cmd_67(a)


class FakeFM1VA(FakeStock):
    """Baud Girl's FM-1+VA (closed; as the community's Virtual-FM-1 Fm1Codec and fm1-pulses describe it): M-VAVE's
    handshake with its id (FM-1_102), 128 presets (a packed DX7 voice and a 59-byte record) read with
    F0 43 00 7D 10 and written with the 231-byte 04 message (no reply; repacked as the firmware does), replies
    bitstream-packed after F0 7D. While `playing`, reads answer status 3 and writes are dropped."""

    def __init__(self, ident="FM-1_102"):
        super().__init__(ident=ident)
        import dx7
        self.dx7mod = dx7
        self.presets = {}
        for s in range(128):
            from test_dx7 import random_voice
            voice = bytes(dx7.pack(random_voice(s, f"PRESET {s:03}")))
            record = bytes([(s + i) & 0xFF for i in range(59)])
            record = record[:18] + bytes([(0x5A, 0xA5, 0xC3)[s % 3]]) + record[19:]
            self.presets[s] = (voice, record)
        self.writes = 0

    def handle(self, data):
        import baudgirl
        if data[:3] == [0x43, 0x00, 0x7D]:
            body = data[3:-1]
            if baudgirl.ysum(body[2:] if body[:1] == [0x04] else body) != data[-1]:   # (a write's: over its payload)
                return
            if body[0] == 0x10 and len(body) == 2:
                slot = body[1]
                status = 3 if self.playing else 1 if slot >= 128 else 0
                d = b"" if status else b"".join(self.presets[slot])
                buf = bytes([0x7D, 0x50, status, *slot.to_bytes(4, "little"), len(d) & 0xFF, len(d) >> 8]) + d
                buf += bytes([~sum(buf) & 0xFF])
                import fm1_install
                self.raw_reply([0x7D, *fm1_install.pack7(buf)])
            elif body[0] == 0x04 and len(body) == 2 + 155 + 68 and not self.playing:
                slot, voice, packed = body[1], bytes(body[2:157]), body[157:]
                self.presets[slot] = (bytes(self.dx7mod.pack(voice)), sloop.unpack7(packed)[:59])
                self.writes += 1
            return
        super().handle(data)
