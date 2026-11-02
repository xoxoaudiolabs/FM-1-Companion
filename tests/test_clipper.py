"""Tests for Clipper (isod89's synth firmware, from SLOOP 2.5) against a pretend Clipper 1.3 (fake_fm1.FakeClipper,
made from its editor.c and EDITOR_PROTOCOL.md; never tried on an FM-1 running it): SLOOP's backup with its ids 0-9
and wavetable slots, a restore, its own refusal while it plays, and nothing sent on SLOOP-only numbers (77 is HY_GET
there, 37 LOCK_GET).

  python tests/test_clipper.py     (needs mido)
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
sys.path.insert(0, str(ROOT / "tests"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-clipper-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"))
os.environ["FM1_SETTINGS"] = str(TMP / "settings.json")
(TMP / "run").mkdir()

import fake_fm1  # noqa: E402
import library  # noqa: E402
import sloop  # noqa: E402


def open_dev(fake):
    return sloop.Sloop(sloop.Link(mido=fake, time_scale=0.02))


def run(fake, args):
    was = sloop.Link
    try:
        sloop.Link = lambda card=None: was(mido=fake, time_scale=0.02)
        return library.main(args)
    finally:
        sloop.Link = was


def test_backup_and_restore():
    fake = fake_fm1.FakeClipper()
    dev = open_dev(fake)
    assert sloop.family(dev.version) == "clipper" and dev.can_backup() and dev.playing() is None
    data = dev.backup()
    assert data["format"] == "sloop-backup" and [o["id"] for o in data["objects"]] == list(range(10)) + [32, 33, 34]
    saved = dict(fake.objects)
    fake.objects.update({0: fake_fm1.project(5, 9), 3: fake_fm1.project(5, 3), 9: b"", 32: b""})
    open_dev(fake).restore(data)
    assert fake.objects == saved and fake.wrong == []


def test_library_jobs_and_playing():
    fake = fake_fm1.FakeClipper()
    assert run(fake, ["backup"]) == 0
    path = sorted(library.folder("backups").glob("*clipper*_manual.json"))[-1]
    fake.playing = True                                               # its commit says "stop first" (rc 3)
    assert run(fake, ["restore", str(path)]) == 1 and "stop" in library.read_state()["message"]
    fake.playing = False
    data = sloop.load_json(path)
    assert run(fake, ["load-project", str(path), "A", "C"]) == 0 and fake.objects[4] == fake.objects[2]
    assert fake.wrong == [] and data["firmware"] == "FELUCCA CLIPPER 1.3"


def test_refusals():
    fake = fake_fm1.FakeClipper()
    for job in (lambda d: d.require_sample_slots(), lambda d: d.restore(open_dev(fake_fm1.FakeFM1()).backup())):
        try:
            job(open_dev(fake))
            raise AssertionError("not for Clipper")
        except sloop.SloopError as e:
            assert e.code == "family"
    assert fake.wrong == []


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
