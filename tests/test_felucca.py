"""Tests for Felucca's full backup (sloop.py's felucca dialect, library.py's jobs) against a pretend Felucca 1.x
(fake_fm1.FakeFelucca, made from Felucca's EDITOR_PROTOCOL.md and fm1backup.js; never tried on a real one): a backup
in Felucca's own file format, a restore in its editor's order, a project into a slot, nothing ever sent on SLOOP's
command numbers (other commands there), and SLOOP's files kept off it (and its files off SLOOP).

  python tests/test_felucca.py     (needs mido)
"""
import base64
import os
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
sys.path.insert(0, str(ROOT / "tests"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-felucca-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"))
os.environ["FM1_SETTINGS"] = str(TMP / "settings.json")
(TMP / "run").mkdir()

import fake_fm1  # noqa: E402
import library  # noqa: E402
import sloop  # noqa: E402


def open_dev(fake):
    return sloop.Sloop(sloop.Link(mido=fake, time_scale=0.02))


def with_fake(fake, fn):
    was = sloop.Link
    try:
        sloop.Link = lambda card=None: was(mido=fake, time_scale=0.02)
        return fn()
    finally:
        sloop.Link = was


def test_info_and_family():
    fake = fake_fm1.FakeFelucca()
    dev = open_dev(fake)
    assert sloop.family(dev.version) == "felucca" and dev.dialect == "felucca"
    assert dev.info["backup_caps"] == 3 and dev.can_backup()
    assert dev.playing() is None and fake.wrong == []                 # (no LIVE: 77 is FM6B_LIST there)
    salt = open_dev(fake_fm1.FakeFelucca(version="FELUCCA 0.9-salt14", caps=0))   # no "42 01": no backup
    assert not salt.can_backup()
    try:
        salt.require_backup()
        raise AssertionError("Salt backed up")
    except sloop.SloopError as e:
        assert e.code == "old"


def test_backup_in_feluccas_format():
    fake = fake_fm1.FakeFelucca()
    fake.playing = True                                               # LIST stops it itself
    data = open_dev(fake).backup()
    assert data["format"] == "felucca-backup" and data["version"] == 1 and data["firmware"] == "FELUCCA v1.9.0"
    assert [o["id"] for o in data["objects"]] == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 32, 33, 34]   # fm1backup.js's order
    for o in data["objects"]:
        raw = base64.b64decode(o["data"])
        assert o["size"] == len(raw) and o["crc"] == zlib.crc32(raw) and raw == fake.objects[o["id"]]
    assert "created" in data and fake.wrong == []
    assert sloop.describe(data)["projects"] == ["A", "D"] and sloop.describe(data)["samples"] == ["USR1"]


def test_restore_order_and_content():
    fake = fake_fm1.FakeFelucca()
    data = open_dev(fake).backup()
    saved = dict(fake.objects)
    for i in (0, 2, 5, 6, 9, 32):                                      # the device changes; the file brings it back
        fake.objects[i] = fake_fm1.project(0x11, 99, 3840) if i in (0, 2, 5) else b""
    fake.objects[3] = fake_fm1.project(0x11, 7, 3840)
    puts = []
    was = fake.cmd_67
    fake.cmd_67 = lambda a: (puts.append(a[1]) if a[0] == 0 else None, was(a))[1]
    open_dev(fake).restore(data)
    assert {i: fake.objects[i] for i in saved} == saved and fake.wrong == []
    assert puts == [2, 3, 4, 5, 6, 7, 8, 9, 1, 0]                     # the working project last, settings before it


def test_projects_and_refusals():
    fake = fake_fm1.FakeFelucca()
    backup = open_dev(fake).backup()
    project = sloop.project_from(backup, "A")
    open_dev(fake).put_project(project, "C", firmware=backup["firmware"])
    assert fake.objects[4] == fake.objects[2]
    sloop_backup = open_dev(fake_fm1.FakeFM1()).backup()               # SLOOP's onto Felucca, Felucca's onto SLOOP
    for dev, file in ((open_dev(fake), sloop_backup), (open_dev(fake_fm1.FakeFM1()), backup)):
        try:
            dev.restore(file)
            raise AssertionError("mixed families")
        except sloop.SloopError as e:
            assert e.code == "family"
    for job in (lambda d: d.read_song(), lambda d: d.require_sample_slots()):   # SLOOP's own, for now
        try:
            job(open_dev(fake))
            raise AssertionError("song or sample on Felucca")
        except sloop.SloopError as e:
            assert e.code == "family"
    assert fake.wrong == []


def test_library_jobs():
    """Back up now and a restore through library.py, as the box and the web page run them"""
    fake = fake_fm1.FakeFelucca()
    assert with_fake(fake, lambda: library.main(["backup"])) == 0
    files = sorted(library.folder("backups").glob("*felucca*_manual.json"))
    assert len(files) == 1
    entry = next(b for b in library.listing()["backups"] if b["name"] == files[0].name)
    assert entry["firmware"] == "FELUCCA v1.9.0" and entry["projects"] == ["A", "D"]
    fake.objects[5] = b""
    assert with_fake(fake, lambda: library.main(["restore", str(files[0])])) == 0
    assert fake.objects[5][:4] == b"ANUF" and fake.wrong == []
    befores = list(library.folder("backups").glob("*_before-restore.json"))
    assert befores and sloop.load_json(befores[0])["format"] == "felucca-backup"


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
