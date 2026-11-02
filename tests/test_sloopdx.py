"""Tests for sloopDX (sloop.py, library.py) against a pretend sloopDX 4.0 (fake_fm1.FakeSloopDX, made from its
editor.c; never tried on a real one): every one of its 8 DX7 banks in a backup and back, the bank in use put back, a
DX7 .syx loaded into its bank in use (backed up first), and what it doesn't do (samples, single voices, SLOOP's files).

  python tests/test_sloopdx.py     (needs mido)
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
sys.path.insert(0, str(ROOT / "tests"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-sloopdx-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"))
os.environ["FM1_SETTINGS"] = str(TMP / "settings.json")
(TMP / "run").mkdir()

import dx7  # noqa: E402
import fake_fm1  # noqa: E402
import library  # noqa: E402
import sloop  # noqa: E402
from test_dx7 import random_voice  # noqa: E402


def open_dev(fake):
    return sloop.Sloop(sloop.Link(mido=fake, time_scale=0.02))


def run(fake, args):
    was = sloop.Link
    try:
        sloop.Link = lambda card=None: was(mido=fake, time_scale=0.02)
        return library.main(args)
    finally:
        sloop.Link = was


def test_all_banks():
    fake = fake_fm1.FakeSloopDX()
    banks = fake.all_banks()
    data = open_dev(fake).backup()
    assert data["dx7_in_use"] == 2 and fake.cur == 2                  # (put back after)
    assert sloop.dx_banks_of(data) == banks
    fake.objects[8] = b""                                             # the device changes: the file brings it back
    fake.banks[5], fake.cur = b"", 0
    fake.objects[8] = fake.banks[0]
    open_dev(fake).restore(data)
    assert fake.all_banks() == banks and fake.cur == 2


def test_playing_keeps_its_bank():
    fake = fake_fm1.FakeSloopDX()
    fake.playing = True
    try:
        open_dev(fake).backup()
        raise AssertionError("banks read while playing")
    except sloop.SloopError as e:
        assert e.code == "stop"


def test_syx_into_the_bank_in_use():
    voices = [dx7.pack(random_voice(i, f"DX{i}")) for i in range(32)]
    path = library.folder("patches") / "dx-bank.syx"
    path.write_bytes(dx7.bank_message(voices))
    fake = fake_fm1.FakeSloopDX()
    others = {k: d for k, d in fake.all_banks().items() if k != 2}
    assert run(fake, ["dx7-send", str(path)]) == 0
    assert fake.objects[8] == b"".join(voices) and fake.cur == 2
    assert {k: d for k, d in fake.all_banks().items() if k != 2} == others
    befores = list(library.folder("backups").glob("*_before-dx7.json"))
    assert befores and len(sloop.dx_banks_of(sloop.load_json(befores[0]))) == 8
    assert run(fake, ["dx7-send", str(path), "3"]) == 1               # one voice: not on sloopDX


def test_what_it_doesnt_do():
    fake = fake_fm1.FakeSloopDX()
    for job in (lambda d: d.require_sample_slots(), lambda d: d.restore(open_dev(fake_fm1.FakeFM1()).backup())):
        try:
            job(open_dev(fake))
            raise AssertionError("not for sloopDX")
        except sloop.SloopError as e:
            assert e.code == "family"
    try:
        open_dev(fake_fm1.FakeFM1()).write_dx_bank(bytes(4096))       # BANK_BEGIN never goes to SLOOP (LOCK_GET)
        raise AssertionError("bank to SLOOP")
    except sloop.SloopError as e:
        assert e.code == "family"


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
