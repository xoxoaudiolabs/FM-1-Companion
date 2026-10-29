# Hardware: what each part needs

What a board or screen needs to run the FM-1 Companion's Pocket build, and how to add a screen. Which parts are
tested, which should work and which won't: [Compatibility](fm1-bt-bridge/README.md#compatibility). Built one on
other hardware? [Tell us](https://github.com/xoxoaudiolabs/FM-1-Companion/issues/new?template=hardware-report.yml).

## The board

- **Built-in Bluetooth.** The Companion's audio out and Bluetooth MIDI are the Pi's own Bluetooth (BlueZ): a Pi Zero
  W, Zero WH or Zero 2 W. A Pi Zero without the W has none; the installer stops on one, and the box says so on its
  screen.
- **A USB port that can be the host**, for the FM-1 (and a hub with keyboards and a second FM-1). On a Pi Zero
  that's the port labelled USB, through an OTG adapter. The installer sets it to full speed (`dwc_otg.speed=1` in
  `cmdline.txt`), so a hub works: the FM-1 and USB MIDI keyboards are full-speed devices anyway.
- **SPI** (the screens) and **I2C** (a PiSugar battery, the OLED switched to I2C): `install.sh` turns both on.
- **Raspberry Pi OS Lite**, Bookworm or Trixie. Everything comes from its own packages (`python3-*`, PipeWire,
  BlueZ), so 32- and 64-bit are the same to the Companion.
- **Any Pi Zero is the Pocket** (`device.detect`: the board's name has "Zero" in it); a Pi 3 or 4 with a 3.5"
  touchscreen is the Studio.

## The screen

The Pocket's screens are made for Waveshare's Zero-size HATs: a screen, a 5-way joystick and three keys, on the
Pi's 40-pin header.

**The keys and joystick** (BCM numbers, active low, pulled up by the Pi): KEY1 21, KEY2 20, KEY3 16, up 6, down 19,
left 5, right 26, press 13 (`bridge.KEYS`). Any HAT with these works with the Companion's keys as they are.

**The screens it has drivers for:**

| HAT | Controller | Pixels | Bus | DC | RST | BL | Driver |
|---|---|---|---|---|---|---|---|
| 1.3" OLED HAT | SH1106 | 128×64, one colour | SPI0 CE0 | 24 | 25 | – | `bridge.SH1106` |
| the same, switched to I2C | SH1106 | 128×64 | I2C-1, 0x3C / 0x3D | – | – | – | `oledi2c.SH1106I2C` |
| 1.44" LCD HAT | ST7735S | 128×128 colour | SPI0 CE0 | 25 | 27 | 24 | `lcd.ST7735` |
| 1.3" LCD HAT | ST7789 | 240×240 colour | SPI0 CE0 | 25 | 27 | 24 | `lcd.ST7789` |

None of them can be read back, so which is fitted is a setting (`"screen"` in
`~/.config/fm1-bridge/fm1-bridge.json`: `fm1-screen` sets it), or the screen picker finds out (`screenpick.py`).
Note that GPIO 24 is the OLED's DC and the LCDs' backlight: the picker lets each driver's pins go before trying the
next.

**How the screens are drawn:** the one-colour screens are 128×64 (the OLED's, in `bridge.py`, `libui.py`,
`meters.py`, `midiui.py`, `sampleui.py`). The colour screens are `pocketui.py` and `pocketmeters.py`, drawn at
128×128 or at 120×120 (`pocketui.GEOMETRY`; the 1.3" LCD shows the 120 at twice the size, so its pixel font stays
crisp). The theme's colours are `sloopstyle.py`'s.

## Adding a screen

1. **A driver** in `lcd.py` (a colour SPI panel): a `Panel` with its controller's set-up commands (`setup`), its
   pixels (`W`, `H`), where they start in its RAM (`X0`, `Y0`), its colour order, how far round it sits from the
   OLED (`TURN`, so the same `"rotate"` setting does for both), its SPI clock (`SPEED`) and the size the screens
   are drawn at (`size`: 128, or 120 shown at twice the size). Add it to `lcd.PANELS` under a name.
   A different kind of screen needs the OLED's calls: `show(img)`, `contrast(value)`, `power(on)` and `close()`.
2. **Its name** in `screenpick.SCREENS` and `NAMES` (the picker tries it), in `config/fm1-screen`'s choices, and in
   `install.sh`'s question.
3. **Check it with the test card:** stop the Companion (`systemctl --user stop fm1-bridge`), then
   `python3 ~/.local/share/fm1-bridge/lcd.py NAME`. A white frame should show on all four edges (junk along one
   edge: `X0` / `Y0`), red, green and blue bars in that order (red and blue swapped: the colour order), and TOP at
   the top with KEYS on the keys' side (otherwise: `TURN`).
4. **A test** in `tests/test_pocket_hw.py`, and a row in Compatibility, marked tested only once it's been seen on
   the real HAT.
