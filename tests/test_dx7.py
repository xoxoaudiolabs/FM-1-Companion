"""Tests for DX7 patches (dx7.py, library.py dx7-send): the bank and single-voice formats, a bank's voices unpacked,
and what's sent to an FM-1: the standard DX7 messages to a firmware that isn't SLOOP, nothing to SLOOP.

  python tests/test_dx7.py     (needs mido)
"""
import os
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
sys.path.insert(0, str(ROOT / "tests"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-dx7-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"))
os.environ["FM1_SETTINGS"] = str(TMP / "settings.json")
(TMP / "run").mkdir()

import mido  # noqa: E402

import dx7  # noqa: E402
import fake_fm1  # noqa: E402
import library  # noqa: E402
import sloop  # noqa: E402

# each unpacked parameter's largest value, as the DX7's own voice data allows (21 an operator, then the rest)
OP_MAX = [99] * 8 + [99, 99, 99, 3, 3, 7, 3, 7, 99, 1, 31, 99, 14]
GLOBAL_MAX = [99] * 8 + [31, 7, 1, 99, 99, 99, 99, 1, 5, 7, 48] + [126] * 10


def random_voice(seed, name="TEST VOICE"):
    rng = random.Random(seed)
    voice = [rng.randint(0, m) for m in OP_MAX * 6 + GLOBAL_MAX]
    voice[145:155] = list(name.ljust(10)[:10].encode())
    return bytes(voice)


def test_pack_and_unpack():
    """a voice packed as a bank holds it, unpacked again: the same 155 bytes, for any values the DX7 allows"""
    for seed in range(200):
        voice = random_voice(seed)
        packed = dx7.pack(voice)
        assert len(packed) == 128 and dx7.unpack(packed) == voice, seed
    assert dx7.packed_name(dx7.pack(random_voice(1, "BRASS   1"))) == "BRASS   1"


def test_messages_and_files():
    voices = [dx7.pack(random_voice(i, f"VOICE {i:02}")) for i in range(32)]
    bank = dx7.bank_message(voices)
    assert len(bank) == 4104 and bank[:6] == dx7.BANK_HEAD and bank[-1] == 0xF7
    assert (sum(bank[6:4102]) + bank[4102]) & 0x7F == 0                      # the checksum
    kind, read = dx7.read(b"junk" + bank + b"more")
    assert kind == "bank" and read == voices
    one = dx7.voice_message(random_voice(7, "E.PIANO"))
    assert len(one) == 163 and one[:6] == dx7.VOICE_HEAD and (sum(one[6:161]) + one[161]) & 0x7F == 0
    assert dx7.read(one) == ("voice", random_voice(7, "E.PIANO"))
    path = TMP / "bank.syx"
    path.write_bytes(bank)
    info = dx7.describe(path)
    assert info["kind"] == "bank" and info["voices"][0] == "VOICE 00" and len(info["voices"]) == 32
    assert dx7.to_send(path) == bank
    assert dx7.to_send(path, 5) == dx7.voice_message(dx7.unpack(voices[5]))   # a bank's voice 6, as a single voice
    for broken in (bank[:-2] + bytes([bank[-2] ^ 1, 0xF7]), b"\xf0\x41\x10\xf7", b""):
        try:
            dx7.read(broken)
            assert False, "read a broken file"
        except dx7.DX7Error:
            pass


class SilentFM1:
    """an FM-1 running a firmware that isn't SLOOP: takes MIDI, answers nothing (mido's module, for sloop.Link)"""
    Message = mido.Message

    def __init__(self):
        self.sent = []

    def get_input_names(self):
        return ["Felucca:Felucca MIDI 1 24:0"]

    get_output_names = get_input_names

    def open_input(self, name, callback=None):
        return fake_fm1.Port(self)

    def open_output(self, name):
        return fake_fm1.Port(self)

    def handle(self, data):
        self.sent.append(bytes([0xF0, *data, 0xF7]))


def test_sending():
    """to a firmware that isn't SLOOP: the bank, or one voice, exactly; to SLOOP: refused, no DX7 sent"""
    voices = [dx7.pack(random_voice(i, f"V{i}")) for i in range(32)]
    path = library.folder("patches") / "test-bank.syx"
    path.write_bytes(dx7.bank_message(voices))
    entry = next(p for p in library.listing()["patches"] if p["name"] == path.name)
    assert entry["kind"] == "bank" and entry["voices"][3] == "V3"
    silent = SilentFM1()
    was = sloop.Link
    try:
        sloop.Link = lambda card=None: was(mido=silent, time_scale=0.02)
        assert library.main(["dx7-send", str(path)]) == 0
        assert silent.sent[-1] == dx7.bank_message(voices)
        assert all(m[1:4] == bytes([0x7D, 0x46, 0x4C]) for m in silent.sent[:-1])   # before it: SLOOP's INFO only
        assert library.main(["dx7-send", str(path), "4"]) == 0
        assert silent.sent[-1] == dx7.voice_message(dx7.unpack(voices[3]))
        assert "V3" in library.read_state()["message"]
        assert library.main(["dx7-send", str(path), "33"]) == 1
        fake = fake_fm1.FakeFM1()                                       # SLOOP: it answers INFO
        sloop.Link = lambda card=None: was(mido=fake, time_scale=0.02)
        assert library.main(["dx7-send", str(path)]) == 1
        assert "doesn't take DX7" in library.read_state()["message"]
    finally:
        sloop.Link = was


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
