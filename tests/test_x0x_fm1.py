"""Tests for an FM-1 running X0X (mvave.py's X0X frames, library.py's backup and restore jobs) against a pretend X0X
(fake_fm1.FakeX0X, made from X0X's firmware/src/backup.c and tools/x0x_backup.py; never tried on a real one): its
project as a .x0b in the x0x folder, a restore it pulls and confirms on its own screen, the answers it can give (HOME,
playing), and nothing of SLOOP's sent to it.

  python tests/test_x0x_fm1.py     (needs mido)
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
sys.path.insert(0, str(ROOT / "tests"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-x0x-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"))
os.environ["FM1_SETTINGS"] = str(TMP / "settings.json")
(TMP / "run").mkdir()

import fake_fm1  # noqa: E402
import library  # noqa: E402
import sloop  # noqa: E402
import x0x  # noqa: E402


def run(fake, args):
    was = sloop.Link
    try:
        sloop.Link = lambda card=None: was(mido=fake, time_scale=0.05)
        return library.main(args)
    finally:
        sloop.Link = was


def test_family():
    dev = sloop.Sloop(sloop.Link(mido=fake_fm1.FakeX0X(), time_scale=0.05))
    assert sloop.family(dev.version) == "x0x" and dev.dialect == "x0x" and not dev.can_backup()
    for check in (dev.require_backup, dev.require_sample_slots, dev.read_song):
        try:
            check()
            raise AssertionError(check)
        except sloop.SloopError as e:
            assert e.code == "family"


def test_backup_and_auto():
    fake = fake_fm1.FakeX0X()
    assert run(fake, ["backup"]) == 0
    files = sorted(library.folder("x0x").glob("*_X0X_manual.x0b"))
    assert len(files) == 1 and files[0].read_bytes() == fake.image() and fake.wrong == []
    assert x0x.describe(files[0].read_bytes())["parts"] == ["settings", "sounds", "patterns 1-16", "song"]
    assert run(fake, ["backup", "--auto"]) == 0 and run(fake, ["backup", "--auto"]) == 0
    assert len(list(library.folder("x0x").glob("*_X0X_auto.x0b"))) == 1          # unchanged: no second file
    assert library.read_state()["result"].get("unchanged")
    fake.unsaved = True                                                            # it played: changes left out
    assert run(fake, ["backup"]) == 0 and "left out" in library.read_state()["message"]


def test_restore_confirmed():
    fake = fake_fm1.FakeX0X()
    assert run(fake, ["backup"]) == 0
    saved = sorted(library.folder("x0x").glob("*_X0X_manual.x0b"))[-1]
    was = dict(fake.project)
    fake.project[1] = b"SND2" + bytes(500)
    assert run(fake, ["restore", str(saved)]) == 0
    assert fake.project == was and fake.wrong == []
    befores = list(library.folder("x0x").glob("*_X0X_before-restore.x0b"))
    assert befores and x0x.read_backup(befores[-1].read_bytes())[1].startswith(b"SND2")


def test_restore_refused():
    fake = fake_fm1.FakeX0X()
    assert run(fake, ["backup"]) == 0
    saved = sorted(library.folder("x0x").glob("*_X0X_manual.x0b"))[-1]
    for fake, words in ((fake_fm1.FakeX0X(answer="HOME"), "HOME"), (fake_fm1.FakeX0X(playing=True), "stop X0X")):
        before = dict(fake.project)
        assert run(fake, ["restore", str(saved)]) == 1
        assert words in library.read_state()["message"] and fake.project == before
    damaged = TMP / "damaged.x0b"
    damaged.write_bytes(saved.read_bytes()[:-1] + b"\0")
    fake = fake_fm1.FakeX0X()
    assert run(fake, ["restore", str(damaged)]) == 1 and fake.pull is None     # (checked before anything's sent)
    assert run(fake_fm1.FakeFM1(), ["restore", str(saved)]) == 1                  # not onto SLOOP
    assert "X0X backup" in library.read_state()["message"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
