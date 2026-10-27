"""The sampler's ready-made 808 KIT, made once on a computer (not on the Pi) into kits/808:

  python make_kits.py PATH-TO/sounds-tr808-fischer

Sixteen of Michael Fischer's recordings of a real Roland TR-808 (1994, CC0 1.0: the tidalcycles/sounds-tr808-fischer
repository), each in SLOOP's drum order, the silence after it cut off. 16-bit mono WAVs at 44.1 kHz, as he made
them. Not affiliated with Roland; TR-808 is its trademark.
"""
import shutil
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
HERE = Path(__file__).resolve().parent
DRUMS = ("KICK", "KICK-2", "SNARE", "CLAP", "HAT", "OPEN-HAT", "PEDAL-HAT", "RIM", "SNARE-2", "LOW-TOM", "HI-TOM",
         "CRASH", "RIDE", "SHAKER", "CONGA", "COWBELL")          # SLOOP's drum keys 1-16 (pads.SLOOP_DRUMS)
FISCHER = ("bd8/BD2575", "bd8/BD5025", "sd8/SD5050", "cp8/CP", "ch8/CH", "oh8/OH50", "oh8/OH00", "rs8/RS",
           "sd8/SD7575", "lt8/LT50", "ht8/HT50", "cy8/CY5075", "cy8/CY2525", "ma8/MA", "mc8/MC50", "cb8/CB")


def trimmed(x, floor_db=-66):
    """x without the near-silence after it, its last 10 ms faded"""
    peak = np.max(np.abs(x)) or 1
    loud = np.nonzero(np.abs(x) > peak * 10 ** (floor_db / 20))[0]
    x = x[:loud[-1] + 1] if len(loud) else x
    fade = min(len(x), int(0.01 * SR))
    x = x.copy()
    x[len(x) - fade:] *= np.linspace(1, 0, fade)
    return x


def write(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((trimmed(x) * 32767).astype("<i2").tobytes())


def main(fischer):
    out = HERE / "808"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.wav"):
        old.unlink()
    for name, src in zip(DRUMS, FISCHER):
        with wave.open(str(Path(fischer) / f"{src}.WAV")) as w:
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, SR), src
            x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(np.float64) / 32768
        write(out / f"808-{name}.wav", x)
    shutil.copy(Path(fischer) / "LICENSE", out / "LICENSE")
    print("made", len(DRUMS), "sounds")


if __name__ == "__main__":
    main(sys.argv[1])
