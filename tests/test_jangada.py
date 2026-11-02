"""Tests for Jangada's full backup (sloop.py: SLOOP's commands, Jangada's file and order) against a pretend Jangada
1.0 (fake_fm1.FakeJangada, made from its EDITOR_PROTOCOL.md and fm1backup.js; never tried on a real one): its 15
objects in its own file format, a restore in its editor's order with the samples, a project load, an older Jangada
without the second FM6 bank, DX7 patches sent to it, and its files kept apart from SLOOP's.

  python tests/test_jangada.py     (needs mido)
"""
import base64
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
sys.path.insert(0, str(ROOT / "tests"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-jangada-"))
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


def test_backup_and_restore():
    fake = fake_fm1.FakeJangada()
    dev = open_dev(fake)
    assert sloop.family(dev.version) == "jangada" and dev.dialect == "sloop" and dev.can_backup()
    assert dev.playing() is None                                      # (protocol 8: no LIVE asked)
    data = dev.backup()
    assert data["format"] == "jangada-backup" and "created" in data
    assert [o["id"] for o in data["objects"]] == list(range(12)) + [32, 33, 34]
    assert all(base64.b64decode(o["data"]) == fake.objects[o["id"]] and o["size"] for o in data["objects"]
               if fake.objects[o["id"]])
    saved = dict(fake.objects)
    fake.objects.update({0: b"JNG2" + bytes(10), 2: b"", 8: b"", 32: b"", 33: fake_fm1.sample_slot("X")})
    puts = []
    was = fake.cmd_36
    fake.cmd_36 = lambda a: (puts.append(a[1]) if a[0] == 0 else None, was(a))[1]
    open_dev(fake).restore(data)
    assert fake.objects == saved
    assert puts == list(range(2, 12)) + [1, 0]                        # its editor's order: 0 last


def test_projects_older_and_refusals():
    fake = fake_fm1.FakeJangada()
    data = open_dev(fake).backup()
    open_dev(fake).put_project(sloop.project_from(data, "A"), "C", firmware=data["firmware"])
    assert fake.objects[4] == fake.objects[2]
    old = fake_fm1.FakeJangada(version="JANGADA 0.5.2", banks2=False)
    old.objects[5] = b""
    open_dev(old).restore(data)                                      # its second FM6 bank: not taken, the rest is
    assert old.objects[5] == fake.objects[5] and 10 not in old.objects
    for dev, file in ((open_dev(fake), open_dev(fake_fm1.FakeFM1()).backup()), (open_dev(fake_fm1.FakeFM1()), data)):
        try:
            dev.restore(file)
            raise AssertionError("mixed")
        except sloop.SloopError as e:
            assert e.code == "family"
    for job in (lambda d: d.read_song(), lambda d: d.require_sample_slots()):
        try:
            job(open_dev(fake))
            raise AssertionError("SLOOP's own on Jangada")
        except sloop.SloopError as e:
            assert e.code == "family" and "Jangada" in str(e)


def test_dx7_goes_to_it():
    voices = [dx7.pack(random_voice(i, f"J{i}")) for i in range(32)]
    path = library.folder("patches") / "jangada-bank.syx"
    path.write_bytes(dx7.bank_message(voices))
    fake = fake_fm1.FakeJangada()
    was = sloop.Link
    try:
        sloop.Link = lambda card=None: was(mido=fake, time_scale=0.02)
        assert library.main(["dx7-send", str(path)]) == 0
    finally:
        sloop.Link = was
    assert fake.dx7 == [dx7.bank_message(voices)]


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
