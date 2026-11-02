"""Tests for M-VAVE's stock firmware (mvave.py, library.py dx7-read) against a pretend stock FM-1
(fake_fm1.FakeStock, made from czietz/fm1-read-voice and fm1_install's handshake; never tried on a real one): who an
FM-1 is by its package id, the sound it plays now saved as a DX7 voice, and the read never sent to anything else.

  python tests/test_stock.py     (needs mido)
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "fm1-bt-bridge"))
sys.path.insert(0, str(ROOT / "tests"))
TMP = Path(tempfile.mkdtemp(prefix="fm1-stock-"))
os.environ.update(FM1_LIBRARY=str(TMP / "library"), XDG_RUNTIME_DIR=str(TMP / "run"), FM1_SD_LIBRARY=str(TMP / "sd"))
os.environ["FM1_SETTINGS"] = str(TMP / "settings.json")
(TMP / "run").mkdir()

import dx7  # noqa: E402
import fake_fm1  # noqa: E402
import fm1_install  # noqa: E402
import library  # noqa: E402
import mvave  # noqa: E402
import sloop  # noqa: E402
from test_dx7 import random_voice  # noqa: E402


def run(fake, args):
    was = sloop.Link
    try:
        sloop.Link = lambda card=None: was(mido=fake, time_scale=0.02)
        return library.main(args)
    finally:
        sloop.Link = was


def test_kinds():
    ident = lambda text: fm1_install.Identity(text, text.split("_")[0], int(text.split("_")[1]))   # noqa: E731
    assert [mvave.kind(ident(t)) for t in ("FM-1_014", "FM-1_019", "FM-1_020", "FM-1_079", "FM-1_906",
                                           "FM-1_8000014", "ota-FM-1_906", "FM-1_102", "FM-1_700")] == [
        "stock", "stock", "baudgirl", "baudgirl", "felucca", "fomni", None, "baudgirl", None]
    assert mvave.kind(None) is None


def test_save_the_sound():
    voice = bytes(random_voice(3, "BRASS 1"))
    fake = fake_fm1.FakeStock(voice=voice)
    assert run(fake, ["dx7-read"]) == 0
    files = list(library.folder("patches").glob("*.syx"))
    assert len(files) == 1 and files[0].read_bytes() == dx7.voice_message(voice)
    assert dx7.describe(files[0]) == {"kind": "voice", "voices": ["BRASS 1"]}
    assert "BRASS 1" in library.read_state()["message"] and fake.dx7 == []      # (it only reads)
    entry = next(p for p in library.listing()["patches"] if p["name"] == files[0].name)
    assert entry["kind"] == "voice"


def test_not_stock_not_asked():
    """Baud Girl's, Felucca's: the handshake only, never the read; SLOOP's fake doesn't answer it: refused too"""
    for ident in ("FM-1_079", "FM-1_906"):
        fake = fake_fm1.FakeStock(ident=ident, voice=bytes(155))
        assert run(fake, ["dx7-read"]) == 1
        assert fake.vendor and 0x23 not in fake.vendor and "stock firmware" in library.read_state()["message"]
    assert run(fake_fm1.FakeFM1(), ["dx7-read"]) == 1


def test_damaged_or_silent():
    fake = fake_fm1.FakeStock(voice=bytes([200]) + bytes(154))          # not 7-bit: not a voice
    assert run(fake, ["dx7-read"]) == 1 and "damaged" in library.read_state()["message"]
    assert run(fake_fm1.FakeStock(voice=None), ["dx7-read"]) == 1         # no answer to the read


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
