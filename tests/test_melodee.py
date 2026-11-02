"""Tests for Melodee's full backup (sloop.py's felucca dialect) against a pretend Melodee 1.6 (fake_fm1.FakeMelodee,
made from its EDITOR_PROTOCOL.md and fm1backup.js; never tried on a real one): its 57 objects in Felucca's file format,
a restore in its editor's order, a project into a slot, DX7 patches sent to it, and its files kept apart.

  python tests/test_melodee.py     (needs mido)
"""
import base64
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
sys.path.insert(0, str(ROOT / "tests"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-melodee-"))
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
    fake = fake_fm1.FakeMelodee()
    dev = open_dev(fake)
    assert sloop.family(dev.version) == "melodee" and dev.dialect == "felucca" and dev.can_backup()
    data = dev.backup()
    ids = [o["id"] for o in data["objects"]]
    assert data["format"] == "felucca-backup" and ids == list(range(29)) + list(range(64, 92))
    assert all(base64.b64decode(o["data"]) == fake.objects[o["id"]] for o in data["objects"]) and fake.wrong == []
    saved = dict(fake.objects)
    fake.objects.update({0: b"", 7: b"", 64: b"", 73: fake_fm1.project(0x19, 1, 300)})
    puts = []
    was = fake.cmd_67
    fake.cmd_67 = lambda a: (puts.append(a[1]) if a[0] == 0 else None, was(a))[1]
    open_dev(fake).restore(data)
    assert fake.objects == saved and fake.wrong == []
    assert puts == list(range(2, 29)) + list(range(64, 92)) + [1, 0]


def test_project_dx7_and_apart():
    fake = fake_fm1.FakeMelodee()
    data = open_dev(fake).backup()
    open_dev(fake).put_project(sloop.project_from(data, "A"), "C", firmware=data["firmware"])
    assert fake.objects[4] == fake.objects[2]
    voices = [dx7.pack(random_voice(i, f"M{i}")) for i in range(32)]
    path = library.folder("patches") / "melodee.syx"
    path.write_bytes(dx7.bank_message(voices))
    was = sloop.Link
    try:
        sloop.Link = lambda card=None: was(mido=fake, time_scale=0.02)
        assert library.main(["dx7-send", str(path), "4"]) == 0
    finally:
        sloop.Link = was
    assert fake.dx7 == [dx7.voice_message(dx7.unpack(voices[3]))]
    for dev, file in ((open_dev(fake), open_dev(fake_fm1.FakeFelucca()).backup()),
                      (open_dev(fake_fm1.FakeFelucca()), data)):
        try:
            dev.restore(file)
            raise AssertionError("mixed")
        except sloop.SloopError as e:
            assert e.code == "family"


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
