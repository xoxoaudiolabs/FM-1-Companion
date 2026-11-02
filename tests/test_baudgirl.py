"""Tests for Baud Girl's FM-1+VA (baudgirl.py, library.py) against a pretend FM-1+VA (fake_fm1.FakeFM1VA, made from the
community's description of her protocol; never tried on a real one): its 128 presets backed up and listed, put back
and read back, a refusal while its sequencer plays, damaged files stopped first, and other firmwares left alone.

  python tests/test_baudgirl.py     (needs mido)
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
sys.path.insert(0, str(ROOT / "tests"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-baudgirl-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"))
os.environ["FM1_SETTINGS"] = str(TMP / "settings.json")
(TMP / "run").mkdir()

import baudgirl  # noqa: E402
import fake_fm1  # noqa: E402
import library  # noqa: E402
import sloop  # noqa: E402


def run(fake, args):
    was = sloop.Link
    try:
        sloop.Link = lambda card=None: was(mido=fake, time_scale=0.02)
        return library.main(args)
    finally:
        sloop.Link = was


def test_backup_listing_auto():
    fake = fake_fm1.FakeFM1VA()
    assert run(fake, ["backup"]) == 0
    files = list(library.folder("backups").glob("*_manual.json"))
    assert len(files) == 1
    data = sloop.load_json(files[0])
    assert data["format"] == "fm1va-presets" and baudgirl.presets_of(data) == fake.presets
    entry = next(b for b in library.listing()["backups"] if b["name"] == files[0].name)
    assert entry["presets"] == 128 and entry["engines"] == {"VA": 43, "FM": 43, "8-Bit": 42} and not entry.get("damaged")
    assert run(fake, ["backup", "--auto"]) == 0 and run(fake, ["backup", "--auto"]) == 0
    assert library.read_state()["result"].get("unchanged") and fake.writes == 0


def test_identify_names_it():
    assert run(fake_fm1.FakeFM1VA(), ["identify"]) == 0 and library.firmware_label() == "FM-1+VA 102"


def test_restore_reads_back():
    fake = fake_fm1.FakeFM1VA()
    assert run(fake, ["backup"]) == 0
    path = sorted(library.folder("backups").glob("*_manual.json"))[-1]
    saved = dict(fake.presets)
    fake.presets[7] = fake.presets[9]
    fake.presets[100] = fake.presets[1]
    assert run(fake, ["restore", str(path)]) == 0
    assert fake.presets == saved and fake.writes == 128
    assert list(library.folder("backups").glob("*_before-restore.json"))


def test_refusals():
    fake = fake_fm1.FakeFM1VA()
    assert run(fake, ["backup"]) == 0
    path = sorted(library.folder("backups").glob("*_manual.json"))[-1]
    fake.playing = True
    assert run(fake, ["backup"]) == 1 and "stop it first" in library.read_state()["message"]
    assert run(fake, ["restore", str(path)]) == 1 and fake.writes == 0
    damaged = TMP / "damaged.json"
    data = sloop.load_json(path)
    data["presets"][3]["voice"] = data["presets"][3]["voice"][:-8]
    sloop.save_json(damaged, data)
    fake = fake_fm1.FakeFM1VA()
    assert run(fake, ["restore", str(damaged)]) == 1 and fake.writes == 0
    stock = fake_fm1.FakeStock(voice=bytes(155))                       # stock: not asked for its presets
    assert run(stock, ["backup"]) == 1 and 0x10 not in [v for v in stock.vendor if isinstance(v, int)]
    assert run(fake_fm1.FakeFM1VA(), ["restore", str(sorted(library.folder("backups").glob("*_manual.json"))[0])]) == 0


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
