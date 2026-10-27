# 808 KIT: where its sounds come from

Sixteen recordings of a real Roland TR-808 (serial no. 103852), made by **Michael Fischer of Technopolis** in 1994
("Roland TR-808 Rhythm Composer Sound Sample Set 1.0.0"), from the
[tidalcycles/sounds-tr808-fischer](https://github.com/tidalcycles/sounds-tr808-fischer) repository (commit
`85fbecf`), released there under **CC0 1.0** (the `LICENSE` file beside this one, copied from it).

`kits/make_kits.py` renamed each one after SLOOP's drum key it's on, and cut off the near-silence after it (below
-66 dB) with a 10 ms fade. Nothing else is changed: not their level, not their sound.

| Pad (SLOOP drum key) | Fischer's file | His knob settings |
|---|---|---|
| 1 KICK | `BD2575` | tone 2.5, decay 7.5 |
| 2 KICK 2 | `BD5025` | tone 5, decay 2.5 |
| 3 SNARE | `SD5050` | tone 5, snappy 5 |
| 4 CLAP | `CP` | |
| 5 HAT | `CH` | |
| 6 OPEN HAT | `OH50` | decay 5 |
| 7 PEDAL HAT | `OH00` | decay 0 |
| 8 RIM | `RS` | |
| 9 SNARE 2 | `SD7575` | tone 7.5, snappy 7.5 |
| 10 LOW TOM | `LT50` | tuning 5 |
| 11 HI TOM | `HT50` | tuning 5 |
| 12 CRASH | `CY5075` | tone 5, decay 7.5 |
| 13 RIDE | `CY2525` | tone 2.5, decay 2.5 |
| 14 SHAKER | `MA` (maracas) | |
| 15 CONGA | `MC50` | tuning 5 |
| 16 COWBELL | `CB` | |

Not affiliated with Roland. TR-808 is a trademark of Roland Corporation.
