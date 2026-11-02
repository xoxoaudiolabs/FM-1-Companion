"""Tests for JIANT FM's full backup (sloop.py's felucca dialect) against a pretend JIANT 0.9 (fake_fm1.FakeJiant, made
from JIANT's EDITOR_PROTOCOL.md and fm1backup.js; never tried on a real one): its 43 objects in Felucca's file format,
a restore in its editor's order (every song's sections too), an older JIANT skipping the songs, and its files kept
apart from Felucca's and SLOOP's.

  python tests/test_jiant.py     (needs mido)
"""
import base64
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
sys.path.insert(0, str(ROOT / "tests"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-jiant-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"))
os.environ["FM1_SETTINGS"] = str(TMP / "settings.json")
(TMP / "run").mkdir()

import fake_fm1  # noqa: E402
import sloop  # noqa: E402


def open_dev(fake):
    return sloop.Sloop(sloop.Link(mido=fake, time_scale=0.02))


def test_family():
    dev = open_dev(fake_fm1.FakeJiant())
    assert sloop.family(dev.version) == "jiant" and dev.dialect == "felucca" and dev.can_backup()
    assert sloop.family("JIANT v0.9.18") == "jiant" and sloop.family("FELUCCA v0.2.1") == "felucca"


def test_backup_and_restore():
    fake = fake_fm1.FakeJiant()
    data = open_dev(fake).backup()
    ids = [o["id"] for o in data["objects"]]
    assert data["format"] == "felucca-backup" and ids == list(range(11)) + list(range(40, 72))   # 43, its order
    assert all(base64.b64decode(o["data"]) == fake.objects[o["id"]] for o in data["objects"]) and fake.wrong == []
    saved = dict(fake.objects)
    for i in (0, 10, 45, 60):
        fake.objects[i] = b"" if i else fake_fm1.project(0x11, 77, 3744)
    puts = []
    was = fake.cmd_67
    fake.cmd_67 = lambda a: (puts.append(a[1]) if a[0] == 0 else None, was(a))[1]
    open_dev(fake).restore(data)
    assert fake.objects == saved and fake.wrong == []
    assert puts == list(range(2, 11)) + list(range(40, 72)) + [1, 0]   # the working music last, as its editor


def test_older_jiant_skips_songs():
    """a 0.9 backup onto a JIANT before 0.3: the songs aren't taken (rc 1 at begin), the rest is"""
    data = open_dev(fake_fm1.FakeJiant()).backup()
    old = fake_fm1.FakeJiant(old=True)
    old.objects[2] = b""
    open_dev(old).restore(data)
    assert old.objects[2][:4] == b"ANUF" and 10 not in old.objects and old.wrong == []


def test_kept_apart():
    jiant, felucca = fake_fm1.FakeJiant(), fake_fm1.FakeFelucca()
    j, f = open_dev(jiant).backup(), open_dev(felucca).backup()
    for dev, file in ((open_dev(felucca), j), (open_dev(jiant), f), (open_dev(fake_fm1.FakeFM1()), j)):
        try:
            dev.restore(file)
            raise AssertionError("mixed")
        except sloop.SloopError as e:
            assert e.code == "family"
    for job in (lambda d: d.read_song(), lambda d: d.require_sample_slots()):
        try:
            job(open_dev(jiant))
            raise AssertionError("SLOOP's own on JIANT")
        except sloop.SloopError as e:
            assert e.code == "family" and "JIANT" in str(e)


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
