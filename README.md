# FM-1 Companion

**A studio sidekick for the M-VAVE FM-1 pocket synth.** Bluetooth audio and MIDI, a mixer, a recorder that keeps
the MIDI too, a sample editor, meters and a MIDI matrix, with no computer needed once it's set up. By
[XOXO Audio Labs](https://xoxoaudiolabs.com).

**[xoxoaudiolabs.com](https://xoxoaudiolabs.com)** · [The Pocket](https://xoxoaudiolabs.com/products/fm1-companion-pocket/)
· [The Studio](https://xoxoaudiolabs.com/products/fm1-companion-studio/) ·
[Try the web app](https://xoxoaudiolabs.com/app/) (sample data, in your browser) ·
[What's new](docs/CHANGELOG.md)

| The Studio | The Pocket |
|---|---|
| [![The Studio tour: its touch screens, the sampler, the sequencer, the meters, with each tap shown](docs/images/studio-preview.gif)](https://cdn.jsdelivr.net/gh/xoxoaudiolabs/FM-1-Companion@main/docs/video/fm1-companion-studio-v1.3.mp4) | [![The Pocket demo: the box's screens and meters, with the button presses shown](docs/images/demo-preview.gif)](https://cdn.jsdelivr.net/gh/xoxoaudiolabs/FM-1-Companion@main/docs/video/fm1-companion-demo-v2.6.1.mp4) |
| **[▶ Studio tour](https://cdn.jsdelivr.net/gh/xoxoaudiolabs/FM-1-Companion@main/docs/video/fm1-companion-studio-v1.3.mp4)** (1:12, with sound) | **[▶ Pocket demo](https://cdn.jsdelivr.net/gh/xoxoaudiolabs/FM-1-Companion@main/docs/video/fm1-companion-demo-v2.6.1.mp4)** (1:46, with sound) |

Both videos are drawn by the boxes' own screen code on a computer, with each button press or tap shown; they
aren't filmed. Their audio is real: played on the FM-1s and recorded by the box.

<img src="docs/images/device-with-fm1.jpg" width="560" alt="The Pocket on its PiSugar battery, cabled to the FM-1 running SLOOP">

It started as a way to add the Bluetooth that custom FM-1 firmware such as [SLOOP](https://github.com/isod89/sloop-fm1)
leaves switched off, and grew from there. Plug it into the FM-1 by USB and run it from its own screen or from
your phone.

## Two builds, one codebase

| | **The Pocket** | **The Studio** |
|---|---|---|
| Computer | Raspberry Pi Zero W (Zero 2 W: should work, not tried yet) | Raspberry Pi 3 B+ |
| Screen and controls | A Waveshare Zero HAT: the 1.3" OLED, the 1.44" colour LCD or the 1.3" colour LCD (not tried yet); joystick and three keys | 3.5" 480×320 touchscreen, in SLOOP's style and colours |
| Battery | PiSugar 3 | PiSugar 3 Plus (5000 mAh) |
| Adds | Fits in a pocket | SLOOP and X0X running on the Studio itself, DJ decks, a sampler with SLOOP's sequencer and punch-in FX, a headphone jack with cue, a DAW control surface, four USB ports, Ethernet, HDMI out |
| Software | v2.13 | Studio v1.6, and newer work on main |
| More | [Product page](https://xoxoaudiolabs.com/products/fm1-companion-pocket/) | [Product page](https://xoxoaudiolabs.com/products/fm1-companion-studio/) |

The installer works out which build it's on, and each build only shows what its hardware can do. What's been
tried on the real boxes, and what hasn't yet: [Tested on the real hardware](#tested-on-the-real-hardware).

## Compatibility

The Pocket needs a **Pi Zero with wireless** (Zero W, Zero WH, Zero 2 W) for its Bluetooth, and a **Waveshare
Zero screen HAT** with the joystick and three keys. Which boards, screens and OS versions are tested, which should
work, and which won't: [the setup guide's Compatibility](fm1-bt-bridge/README.md#compatibility). What Bluetooth
does and doesn't do: [Bluetooth](fm1-bt-bridge/README.md#bluetooth-what-the-pocket-can-and-cant-do).

Built one on different hardware, or had trouble? [Tell us](https://github.com/xoxoaudiolabs/FM-1-Companion/issues/new?template=hardware-report.yml): run `fm1-report` on the box and paste what
it prints. Adding a part or a screen driver: [HARDWARE.md](HARDWARE.md).

## What it does

- **Wireless audio and MIDI.** The FM-1 plays on Bluetooth headphones or a speaker, and the box shows up as a
  Bluetooth MIDI device, **"FM-1 Companion"**, for a phone, iPad, computer or keyboard to play the FM-1. It can
  also connect to keyboards that wait to be connected to (a microKEY Air, a WIDI; not tried with real ones yet).
- **More keyboards, a second FM-1.** Up to four USB MIDI keyboards and a second FM-1 through a hub (or the
  Studio's four ports), found by themselves. **FM-1 A** and **FM-1 B** keep their names by hub port.
- **A mixer.** Each FM-1 and each USB audio device at its own level, 0–200%.
- **A recorder and a sample editor.** Record to WAV, with a `.mid` of what was played beside each take (tried on
  the Studio), and **Record parts** for each source as its own file. Turn a take into a sample: trim, fade, normalize, reverse,
  tune it to its note, ready to load into the FM-1.
- **Playing tools.** MIDI clock (follow, or lead with tap tempo and Start/Stop), metronome, arpeggiator and
  chord memory.
- **A MIDI matrix.** Route Bluetooth, USB keyboards, the FM-1s and the box to each other: transpose, re-channel,
  reshape velocity, pick a key range or split a keyboard, and filter, with four presets.
- **Eleven meters.** LED bars, VU needles, spectrum, scope, a tape deck, a tuner, a keyboard view, a waterfall, a
  goniometer, a level history and a beat counter (the Studio shows ten, without the tuner).
- **Looks after the FM-1 (SLOOP 2.3+).** Back up and restore everything on it, back up and load songs, load
  projects and samples, and install firmware: [SLOOP](https://github.com/isod89/sloop-fm1) or isod89's experimental
  [Clipper](https://github.com/isod89/clipper-fm1). Backups are SLOOP's own files.
- **A web app on your phone** at `http://<the box's hostname>.local`: live status, the mixer, the MIDI matrix, a
  sample editor, your recordings and the library. [Try it with sample data](https://xoxoaudiolabs.com/app/).
- **The Studio adds:**
  - **SLOOP and X0X running on it**, played from a real FM-1:
    [SLOOP Remote Out](https://github.com/xoxoaudiolabs/sloop-remote-out) and
    [X0X for the FM-1 Companion Studio](https://github.com/xoxoaudiolabs/fm1-x0x-companion-studio).
  - **DJ decks** played from a Hercules DJControl Inpulse 200 MK2 and the touchscreen, reading BPM, key and
    beatgrids (Serato's too).
  - **A sampler:** 16 pads in kits, an 808 kit, SLOOP's drum sequencer, note repeat and sixteen of SLOOP's
    punch-in FX.
  - **Headphones:** the 3.5 mm jack with a DJ-style cue on every source.
  - **A DAW control surface** over network MIDI, for [Kraken](https://github.com/isod89/sodwave-site) (Ableton
    Live untested).
- **DX7 patches** for FM-1 firmwares that take them: a library of `.syx` banks, sent whole or a voice at a time
  (not tried on such a firmware yet).
- **Coming:** 5-pin DIN MIDI in, out and thru, on an expansion card of its own (in its own repository).

```
                               ┌── Bluetooth audio ──▶ headphones / speaker
                               ├◀── Bluetooth MIDI ──▶ keyboard / iPad / phone / Mac
FM-1 ◀── USB ──▶ Pocket/Studio ┤
 (audio, MIDI, backups,        ├◀── USB ────────────▶ USB MIDI keyboards, USB audio, a second FM-1
  samples, firmware)           ├◀── Wi-Fi/Ethernet ─▶ web app on your phone; a DAW (the Studio)
                               └── its own screen: meters, mixer, recorder, sample editor
```

## Getting started

Everything is in [`fm1-bt-bridge/`](fm1-bt-bridge/). Its [README](fm1-bt-bridge/README.md) covers what to buy,
flashing the SD card, installing, the controls and troubleshooting. In short:

```
scp -r fm1-bt-bridge YOUR_USER@fm1bridge.local:~
ssh YOUR_USER@fm1bridge.local
bash fm1-bt-bridge/install.sh
sudo reboot
```

Use the hostname you gave the box when you flashed its card (`fm1bridge` above; a Studio might be `fm1studio`).
It's ready about a minute after power-on.

## Screens

Drawn by the Companion's own code on a computer (`tools/render_screens.py`).

| | The Pocket (LCD) | The Pocket (OLED) | The Studio |
|---|---|---|---|
| **Home** | ![Pocket home on the LCD](docs/images/lcd-status.png) | ![Pocket home on the OLED](docs/images/screen-status.png) | ![Studio home](docs/images/desk-ui-home-theme.png) |
| **MIDI routes** | ![Pocket MIDI routes on the LCD](docs/images/lcd-matrix-two.png) | ![Pocket MIDI routes on the OLED](docs/images/screen-matrix-two.png) | ![Studio MIDI routes](docs/images/desk-ui-midi-theme.png) |
| **Meters** | ![A Pocket meter on the LCD](docs/images/lcd-meter-spectrum.png) | ![A Pocket meter on the OLED](docs/images/screen-meter-spectrum.png) | ![A Studio meter](docs/images/desk-ui-meter-theme.png) |
| **Sample editor** | ![The Pocket's sample editor on the LCD](docs/images/lcd-editor.png) | ![The Pocket's sample editor on the OLED](docs/images/screen-editor.png) | ![The Studio's sample editor](docs/images/desk-ui-editor-theme.png) |

<details><summary>More screens: the Studio's sampler, recorder and mixer, every meter, the Pocket's themes</summary>

| The Studio's sampler | The Studio's recorder | The Studio's mixer |
|---|---|---|
| ![Studio sampler](docs/images/desk-ui-pads-theme.png) | ![Studio recorder](docs/images/desk-ui-rec-theme.png) | ![Studio mixer](docs/images/desk-ui-mix-theme.png) |

**The Pocket's eleven meters on the LCD** (joystick left from HOME; up/down changes meter, press records)

![The Pocket's eleven meters on the LCD](docs/images/lcd-meters.png)

**The Pocket's eleven meters on the OLED**

![The Pocket's eleven meters on the OLED](docs/images/screen-meters.png)

**The Studio's ten meters** (MIXER > METERS; tap the meter for the next)

![The Studio's ten meters](docs/images/desk-meters.png)

**The Pocket's HOME in each theme** (Settings › Theme on the LCD)

![HOME in each of the nine themes](docs/images/lcd-themes.png)
</details>

## What's new

The latest of each box; every release in full: **[docs/CHANGELOG.md](docs/CHANGELOG.md)**.

- **Pocket v2.13: splits and key ranges, the XOXO themes, a steadier Studio link.** A MIDI route can pass only
  a range of keys or split a keyboard onto a second channel, scale velocity by a percentage, and arpeggiate at
  1/16T or 1/32 over up to four octaves, with hold. The colour screen's themes are now XOXO (the new default) and
  the eight Studio themes, after FM-1 A's own colours. The Studio link comes back by itself when the Pocket's
  sound stream restarts.
  ([More](docs/CHANGELOG.md#pocket-v213-splits-and-key-ranges-the-xoxo-themes-a-steadier-studio-link))
- **Pocket v2.12: a Studio link, one-click updates, a new web app, SLOOP songs.** The Pocket links to a Studio
  over Wi-Fi or an Ethernet cable: MIDI both ways, the Studio's clock, and the Pocket's sound played on the Studio
  (the Studio's side of the link comes out on 30 October). The web app updates the box to the newest release and
  keeps your settings and library, and it's redrawn. SLOOP songs backed up and loaded back; a DX7 bank loader (not
  tried on a firmware that takes DX7 patches yet).
  ([More](docs/CHANGELOG.md#pocket-v212-a-studio-link-one-click-updates-a-new-web-app-sloop-songs))
- **Pocket v2.11: more boards and screens, a tidier Settings.** Any Pi Zero with wireless, the 1.3" LCD HAT (not
  tried yet) and the OLED over I2C; a screen picker, `fm1-screen` and `fm1-report`; an installer that checks the
  Pi first; Settings opening with Mixer, MIDI routes, Sample editor, Sloop, FM-1 and Bluetooth.
  ([More](docs/CHANGELOG.md#pocket-v211-more-boards-and-screens-a-tidier-settings))
- **Pocket v2.10: a colour screen.** The Waveshare 1.44" LCD HAT as well as the OLED, every screen and meter
  redrawn in colour with the Studio's look, and Settings › Theme. The OLED's screens are unchanged.
  ([More](docs/CHANGELOG.md#pocket-v210-a-colour-screen))
- **On main since Studio v1.6:** MIDI recording (a `.mid` beside each take), the 808 KIT for the sampler, a
  speaker that reconnects itself once, sources heard again at once after a short USB drop, eight Studio themes,
  FM-1 ON STUDIO (map a controller onto SLOOP or X0X) and MIDI learn for the DJ decks (not tried with hardware).
  ([More](docs/CHANGELOG.md#since-studio-v16-on-main-not-a-numbered-release-yet-midi-recording-an-808-kit-a-speaker-that-comes-back))
- **Studio v1.6:** DJ decks, SLOOP and X0X together in time, backups of the Studio's SLOOP and X0X, CUE for both.
  ([More](docs/CHANGELOG.md#studio-v16-dj-decks))

## Tested on the real hardware

What each box has been seen doing for real. Everything else in [What it does](#what-it-does) is built and has
automated tests, but hasn't been tried on the real box yet: it's in the second list until it has.

### The Pocket

A Pi Zero W on Raspberry Pi OS Lite (Trixie) with the Waveshare OLED HAT, later the Waveshare 1.44" LCD HAT on the
Waveshare Ethernet/USB HUB HAT, and a PiSugar 3; FM-1s on SLOOP 2.7 and 2.8; a JBL Go 3; an M-VAVE SMK-37 (over Bluetooth MIDI, and over USB through an ASMedia ASM1074 hub, running Baud
Girl next to two FM-1s).

**Tested**
- Bluetooth audio to a JBL Go 3.
- Bluetooth MIDI: the SMK-37 connecting to the box and playing the FM-1 (up to v2.8.3).
- USB MIDI keyboards through a hub (the SMK-37 on the ASM1074).
- Two FM-1s at once on the hub.
- The library on a real FM-1: a backup, a restore (read back byte for byte), a project load, a sample load, and
  the update from SLOOP 2.7.1 to 2.8 with projects, presets and samples kept.
- Recording to WAV, and the warning when a take clipped (its threshold measured on real FM-1 takes).
- Record parts: each source as its own WAV next to the mix.
- The sample editor, and loading what it saves with Sloop > Load sample.
- The metronome, the arpeggiator and chord memory.
- The PiSugar 3: the battery gauge and the low-battery warning.
- The box as MIDI clock master: exact tempo on average, single ticks about 3 ms early or late (measured while
  playing to a speaker).
- Start-up: about 54 s from power-on to the Companion (measured on Trixie).
- The Bars, VU, Spectrum and Scope meters: about a quarter of the CPU while shown, no audio dropouts.
- The 1.44" LCD HAT (v2.10): every screen, the meters and Settings › Theme, with an FM-1 plugged in. A meter frame
  takes 15–31 ms to draw on the Zero W.
- Reading FM-1 A's theme at start-up for the LCD (a theme made in SLOOP's editor).
- The HUB HAT under it: the Zero W finds its USB hub and Ethernet adapter, with no under-voltage.
- The screen picker on the 1.44" LCD (v2.11): KEY1 on its prompt, KEY1 again to keep it, remembered after a
  restart; `fm1-screen` and `fm1-report` on the real Pocket.
- The Studio link (v2.12) over Wi-Fi and over an Ethernet cable from the HUB HAT: MIDI both ways, the Studio's
  clock, and the Pocket's FM-1 heard on the Studio, coming back after the Pocket's sound stream restarted.
- The update (v2.12): an install from a release file as the updater does it, settings and all 57 library files
  kept as they were; going back to the code from before; the web app asking, the box's hold-press, and an update
  turned down when there's nothing newer, with nothing restarted.
- The MIDI matrix's new route options (v2.13) on the 1.44" LCD Pocket: key ranges, a split, velocity % and arp
  hold saved and read back, a wrong value refused, a split saved from the web app's route editor.
- The themes (v2.13) on the 1.44" LCD: Settings › Theme with XOXO and the eight, each shown as the cursor moves.
- The Studio link (v2.13) over the cable: the Pocket's sound stream stopped on purpose, a new one started and
  heard on the Studio again within 5 s, with nothing done by hand.
- SLOOP songs (v2.12) on an FM-1 running SLOOP 2.8: a song backed up, then loaded back from the box and again from
  `library.py`, read back the same, a backup made first each time. The DX7 loader refusing that SLOOP FM-1 (SLOOP
  doesn't take DX7 patches).

**Not tested on the real Pocket yet**
- From v2.9: connecting to Bluetooth MIDI keyboards (BT keys) and several Bluetooth MIDI devices at once. v2.9 runs
  on the Pocket, but no such keyboard has been tried.
- v2.10 on the OLED HAT: its screens are compared as pictures on a computer only.
- Following FM-1 A's colours on the LCD as they change: the theme is read, but the screen hasn't been watched
  following a change.
- The HUB HAT's extra USB ports.
- The Studio link with Wi-Fi off (the cable only), the Pocket's Ethernet coming up by itself after a restart, and
  the Pocket handing its Bluetooth speaker over to the Studio while linked.
- A whole online update to a newer release: v2.12 is the first release with the updater, so the first real one is
  the next release. A box on v2.11 or older needs one update over SSH to get it. The Studio's update.
- A Pi Zero 2 W, 64-bit Raspberry Pi OS, and Bookworm (for this release).
- The 1.3" LCD HAT (ST7789), and the OLED HAT switched to I2C.
- Sending DX7 patches to a firmware that takes them (M-VAVE's own, FM-1+VA): automated tests only.
- The new web app (tried only in a browser with sample data, [on the website](https://xoxoaudiolabs.com/app/)),
  and its Studio link, theme, auto backup and speaker controls.
- The safe shutdown at 5% battery.
- Installing Clipper: downloaded and accepted by SLOOP's installer, never flashed to an FM-1.
- Playing notes through v2.13's key ranges, splits, velocity % and the new arp rates and hold: saved and shown
  on the box, but not yet played on a keyboard. The Studio link inviting itself again after the Studio restarts
  (v2.13): automated tests only.
- The rest, with automated tests only: the MIDI matrix's route options and presets, the other seven meters,
  auto backup, SD card import and the Wi-Fi switch.

### The Studio

A Pi 3 B+ on Raspberry Pi OS Lite (Trixie), the Hosyond 3.5" touchscreen and a PiSugar 3 Plus, with two FM-1s
on SLOOP 2.8, an M-VAVE SMK-37 running Clipper and a Teenage Engineering K.O. Sidekick (EP-136) on its four USB
ports, and a JBL Go 3. For the DJ decks: a Hercules DJControl Inpulse 200 MK2 (USB; its own sound card for the
headphones), headphones on it, the JBL Go 3 as the master, and 37 MP3s (dubstep around 140 BPM, analysed in Serato
DJ: its tags in them).

**Tested**
- The touchscreen (the piscreen driver at 24 MHz) and touch calibration; the PiSugar 3 Plus.
- Four USB devices at once (the two FM-1s, the SMK-37 and the EP-136), each routed on its own in the MIDI
  matrix; the SMK-37 running Clipper told apart from an FM-1.
- The two FM-1s and the SMK-37 played over MIDI and recorded by the Studio (the audio in the tour video).
- The RECORDER tab.
- The headphone jack as a second output, with CUE on each source.
- Bluetooth audio to a JBL Go 3.
- SLOOP on the Studio (v1.4), with FM-1 A running SLOOP with REMOTE OUT (OUT 16): FM-1 A's keys, buttons and
  knobs drive it; PLAY SLOOP, < HOME and back, HOLD OFF; the + / − level (saved, and set on SLOOP's sound); its
  project kept after a restart of the Companion. Its engine measured: the heaviest case about 8% of one core.
- FM-1 A's REMOTE OUT: keys, buttons and knobs seen arriving on channel 16.
- A scan for Bluetooth MIDI keyboards on the Studio's real Bluetooth (nothing was found: none was on).
- X0X on the Studio (v1.5), by hand from FM-1 A on SLOOP Remote Out: opened from PLAY X0X, its screens moved
  around from FM-1 A's panel, ENV's help and accents.
- REMOTE OUT's every-knob update on FM-1 A: KNOB 4 on SLOOP's TRACKS page and MASTER (CC 123) seen arriving.
- Stress tests of X0X, driven by a script sending REMOTE OUT's messages (not by hand) and recorded by the
  Studio: X0X alone for 41 s (all five parts, mutes, a TB-3PO mutation, the break backwards, a tempo change) and
  X0X with SLOOP at once for 33 s, run as test programs of their own (the Companion then ran one app at a time).
  No gaps in the sound, 0 PipeWire errors, the clip check clean; X0X about 20% of one core, SLOOP about 9%.
- The new clip check on real takes: the stress tests' takes, with an 808 sub-bass, not flagged.
- SLOOP and X0X at once with one clock (v1.6), by hand from FM-1 A through the PLAY tiles: SLOOP
  leading, both playing together in time by ear. A stutter in X0X when SLOOP opened was found this way and fixed;
  by hand afterwards, it was gone.
- The same by a script, each app's sound recorded: X0X following SLOOP at 120 and 130 BPM and through STOP and
  PLAY with no drift, SLOOP following X0X the same way; a follower 9–13 ms after its leader on average, about
  8–9 ms of jitter (two X0Xs in one recording); X0X's beat steady while SLOOP opened and closed.
- DJ decks (v1.6), by hand on the Studio with the Hercules: SCAN of 37 tracks (about 6 minutes, no
  errors), the DECKS screen, browse and LOAD A / B, play, CUE (and PLAY while it's held), the tempo faders, SYNC
  (tempo and beat lock, double / half tempo, the last fader moved leading), EQ, filter, gain, hot cues (Serato's and
  new ones, deleted with SHIFT + pad and on the screen, jumped to from the screen), loops and SHIFT halve / double,
  rolls, the jog (scratch, nudge, through the track), PFL to the Hercules's headphones, the lights, the master on the
  Bluetooth speaker, the decks remembering cues and the session after a restart. Its scan's detection checked
  against Serato's analysis of the 37: the BPM the same as Serato's tag on 32 (36 counting double or half), the key
  on 26 (31 counting a neighbour on the Camelot wheel). Two synced tracks' kicks, 20 ms apart on Serato's grids,
  together after the grid fix (by ear). The decks: about 45 % of one of the Pi 3's cores with both playing.
- CUE on SLOOP's and X0X's MIXER columns, by hand.
- Backups of the Studio's apps (v1.6), by script on the Studio, in test sessions (not by hand, not the
  user's own SLOOP):
  - SLOOP: a real FM-1 A backup restored into the Studio's SLOOP with the Companion's own restore job (19 s, a
    safety backup first); a backup taken right after it matched, all 16 parts (projects, settings, drum kits,
    MIDI map, theme, the four sample slots). A WAV loaded into USR2 (1.9 s), seen in the next backup. A project
    loaded into slot B, still there after SLOOP was stopped and started again.
  - SLOOP's working project from before (the old `project.bin`) taken over by the new SLOOP with the same screen,
    then loaded from the flash file alone.
  - X0X: the user's X0X project backed up to a `.x0b` (X0X's own `tools/x0x_backup.py info` reads it), restored
    into a copy, which X0X opened with the same screen, pixel for pixel.
- A speaker that comes back by itself (on main, after v1.6), by hand with the JBL Go 3: switched off and on, it
  connected itself, the box reconnected it 3 s later (BlueZ's log shows both), and the pads played on it. Once:
  the silent connection it guards against was seen once (that morning) and wasn't brought about again on purpose,
  so whether a given connection by the speaker would have stayed silent isn't known.
- A short USB drop (on main, after v1.6), by hand: FM-1 A unplugged and plugged back in within 3 s; its sound
  path was made again in the same second and it was heard on the JBL Go 3. (Before the fix, a 5 s drop left it
  silent for 90 s.) FM-1 B, a USB keyboard, and a speaker reconnecting this way, not tried.
- The MIXER tab's SLOOP slider, by hand (SLOOP's level on the JBL Go 3).
- The sampler with the 808 KIT (on main, after v1.6): made on the Studio and every sound loads in the sampler's
  engine, by script; its sixteen pads played by hand from the touchscreen and heard on the JBL Go 3, from FM-1
  A's keys (its own sound turned down in the MIXER: the sampler played each key's pad), and by a SLOOP drum
  pattern playing on FM-1 A (GLO › MIDI 2 › OUT = SEQ).
- MIDI recording (on main, after v1.6), by hand on the Studio with FM-1 A through the mixer to the JBL Go 3, six
  takes: each made its `.mid` beside the WAV, one track (FM-1), every note let go. How the notes lined up with the
  sound, measured from the takes (each note against where its sound starts): first 64-82 ms early (SLOOP's kick,
  median 74 ms over 22; chords 65-76 ms); after the 72 ms shift, the clean single hits of the next take +6 to
  +18 ms and one -15 ms (median +13 ms over 19, notes played close together or over another sound reading wider).

**Not tested on the real Studio yet**
- Connecting to a real Bluetooth MIDI keyboard (BT KEYS), and two Bluetooth MIDI devices at once.
- X0X's < HOME, HOLD OFF, + / − and MIXER slider; X0X's song mode; X0X loading its save back after a restart;
  every X0X control tried one by one by hand.
- X0X leading SLOOP (SLOOP's SYNC on USB) by hand: only by a script.
- Turning off the leading app with HOLD OFF while both play: the other should carry on at its own tempo, after a
  stop of about half a second.
- A real clipped take caught by the new clip check (automated tests only).
- SLOOP's project loading back after a reboot of the Studio (after a Companion restart, it did).
- DJ decks: FX and SAMPLER pad modes (not built yet), key lock (not built: a faster track sounds higher), the
  Hercules's master out (nothing was plugged into it), the decks without the Hercules (from the screen alone),
  Serato's tags in FLAC, AIFF or M4A files (only MP3's are read), a track with no beatgrid in its tags on the decks
  (its detected grid: on 36 tracks, within 15 ms of Serato's on 22 after the grid fix), a long set, the decks and
  SLOOP or X0X at once, the beatmatch lights, the decks in the MIXER or the recorder (not built).
- The backups of the Studio's apps by hand from the screen: For, Back up now, Restore, Load project, Load sample;
  a sample loaded into the Studio's SLOOP heard playing; SLOOP's own SAVE and LOAD of its project slots on its
  screen; a Studio SLOOP backup restored onto a real FM-1; a `.x0b` from an FM-1 running X0X restored onto the
  Studio's X0X, or the other way round.
- The sampler's own sequencer (the SEQ page), note repeat and the punch-in FX.
- MIDI recording, beyond what's above: a take straight from one source (no mixer; its delay isn't measured, so
  its notes aren't moved), Record parts takes (the same), FM-1 B, a USB keyboard, Bluetooth or Network MIDI on
  their own tracks, a long take.
- The DAW tab and network MIDI, with Kraken or Ableton Live.
- The HDMI mirror.
- The web app, over Ethernet or Wi-Fi.

## Known limits

- **Bluetooth audio delay:** about 150–250 ms with SBC (the codec is whichever the headphones pick; others
  differ). Fine for listening and practising; you'll notice it when
  playing tightly in time.
- **Recordings clip if the FM-1 sends USB at full level** with several tracks playing (inside the FM-1, before the
  box hears it). The box warns you; set the FM-1's USB audio to master with the knob around half.
- **The Studio's USB:** the Pi 3's USB controller can jam with many audio devices at once (seen with an 8-channel
  high-speed interface next to three full-speed ones): every device goes silent until a reboot.
- **USB devices charge from the battery:** on the PiSugar alone, devices with batteries (the FM-1s) charge from
  it and flatten it in minutes. Keep it plugged in, or use a powered USB hub.
- **Chords over Bluetooth MIDI arrive slightly rolled** (10–50 ms) with keyboards that send each note in its own
  packet.
- **The Pocket only:**
  - **On battery, the FM-1 runs and charges from it too:** the Pi Zero's USB port can't switch its power off, so
    the battery lasts far less with the FM-1 plugged in. A small hardware switch is planned (its parts are on order).
  - **Plugging the FM-1 straight in while the Pi runs can reboot it** (the port has no current limit). Connect
    the FM-1 first, or use a USB hub: replugging the FM-1 on the hub is fine.
  - **USB runs at 12 Mbit/s** so a hub works on the Pi Zero: fine for MIDI and the FM-1's audio, slow for a fast
    USB stick.
  - **Start-up takes about a minute** on the Zero's single core; Wi-Fi comes up about 40 s later (the optional
    `config/fm1-native-wifi` step in the [box README](fm1-bt-bridge/README.md) saves about a minute more).
- **The DJ decks:**
  - No key lock yet: a track played faster sounds higher.
  - Bluetooth runs about 200 ms behind the Hercules's headphones: match beats in the headphones (PFL).
  - A beatgrid found from the sound (no grid in the tags) can sit tens of ms off on some tracks: nudge with the jog.
  - Serato's stems files can't be used (Serato's own protected format); FX and SAMPLER pad modes aren't there yet.
- **SLOOP and X0X on the Studio:**
  - From v1.6 both run at once, sharing one app's clock (not FM-1 A's; in v1.5 one at a time); the follower
    sounds about 10 ms after the leader, give or take about 9 ms, as two boxes on MIDI clock do.
  - X0X's own break loops (its user sample slots) aren't there, so its backups hold none: the built-in breaks
    are.
  - They need FM-1 A running SLOOP with REMOTE OUT (a build of our own, not isod89's release); the official SLOOP
    sends only its keys, not its buttons or knobs.
  - FM-1 A's own SLOOP plays too. Turn FM-1 A down in the MIXER to hear only the Studio's app.
- **Moving the card to another Pi:** Bluetooth pairings belong to the Pi's own Bluetooth chip, so speakers,
  keyboards and phones need pairing again (seen when the Pocket moved to another Zero W).
- **With two FM-1s (or a keyboard's synth), plain recordings need the speaker connected** to hear the whole mix;
  with Record parts on, the mix is made from the parts and needs none. Firmware installs wait until only one FM-1
  is plugged in.

<details><summary>What's in the repository</summary>

| Path | What it is |
|---|---|
| `fm1-bt-bridge/bridge.py` | The app: screens, headphone pairing, audio routing and the mixer (PipeWire), keys |
| `fm1-bt-bridge/blemidi.py` | Bluetooth LE MIDI (BlueZ), the FM-1's USB MIDI and USB keyboards, the clock, the MIDI matrix with its arp and chord memory, the metronome, in a process of its own |
| `fm1-bt-bridge/libui.py` | The Sloop and FM-1 settings, recordings and their screens |
| `fm1-bt-bridge/meters.py` | The eleven meters, recording and playback, pitch detection |
| `fm1-bt-bridge/midiui.py` | The MIDI matrix screens |
| `fm1-bt-bridge/sampleui.py` | The sample editor's screen on the Pocket |
| `fm1-bt-bridge/lcd.py` | The Pocket's 1.44" LCD HAT (ST7735S) |
| `fm1-bt-bridge/pocketui.py` | The Pocket's screens on the LCD, in colour, and Settings › Theme |
| `fm1-bt-bridge/pocketmeters.py` | The eleven meters on the LCD |
| `fm1-bt-bridge/dx7.py` | DX7 banks and voices for firmwares that take them: read, named, sent |
| `fm1-bt-bridge/netaudio.py` | The Pocket's Studio link: its sound to the Studio over the network (PipeWire RTP) |
| `fm1-bt-bridge/update.py` | The web app's one-click update |
| `fm1-bt-bridge/config/fm1-update` | Installs the newest release for the update (root helper, run through sudo) |
| `fm1-bt-bridge/config/50-fm1-ethernet-link.conf` | An Ethernet cable straight to a Studio gets an address with no router |
| `fm1-bt-bridge/battery.py` | The PiSugar battery's charge, read over I2C |
| `fm1-bt-bridge/device.py` | Which build a box is and what its hardware can do |
| `fm1-bt-bridge/deskui.py` | The Studio's touch screens and tabs; starting SLOOP or X0X on the Studio and their margins |
| `fm1-bt-bridge/decks.py` | The DJ decks: two decks, the Hercules DJControl Inpulse 200 MK2, their sound, in a program of their own |
| `fm1-bt-bridge/deskdecks.py` | The Studio's DECKS screen |
| `fm1-bt-bridge/djlib.py` | The Studio DJ Music folder's scan: tags (Serato's too), BPM, key and beat found from the sound |
| `fm1-bt-bridge/x0x.py` | X0X on the Studio: its project to and from X0X's own backups (.x0b) |
| `fm1-bt-bridge/deskpads.py` | The Studio's SAMPLER: pads, kits, SEQ, FX, the sample editor's files |
| `fm1-bt-bridge/pads.py` | The sampler's engine and SLOOP's sequencer, in a process of its own (numpy); its 808 KIT |
| `fm1-bt-bridge/kits/` | The 808 KIT's sounds, and `make_kits.py`, which picked them from Fischer's set |
| `fm1-bt-bridge/padfx.py` | Sixteen of SLOOP's punch-in FX (its original set), for the sampler |
| `fm1-bt-bridge/deskboot.py` | The Studio's boot screen |
| `fm1-bt-bridge/deskmeters.py` | The meters drawn for the Studio (it shows ten: no tuner) |
| `fm1-bt-bridge/deskpages.py` | The Studio's pages: settings, lists, confirmations, jobs, a route's details |
| `fm1-bt-bridge/desk.py` | The Studio's touchscreen and touch input |
| `fm1-bt-bridge/netmidi.py` | Network MIDI (RTP-MIDI) and the Mackie Control surface (the Studio) |
| `fm1-bt-bridge/sloopstyle.py` | SLOOP's palettes, track colours, font and themes (the Studio) |
| `fm1-bt-bridge/sampler.py` | The sample editor's sums, shared by the box and the web page |
| `fm1-bt-bridge/metronome.py` | The metronome's click stream |
| `fm1-bt-bridge/library.py` | The library's jobs (backup, restore, projects, samples, firmware); also a command-line tool |
| `fm1-bt-bridge/sloop.py` | SLOOP's editor protocol over USB MIDI; which FM-1 is A and which is B |
| `fm1-bt-bridge/samplefast.py` | SLOOP's sample converter made faster, byte for byte the same |
| `fm1-bt-bridge/web.py` | The web app at http://fm1bridge.local |
| `fm1-bt-bridge/weblink.py` | How the box and the web app talk |
| `fm1-bt-bridge/vendor/` | SLOOP's firmware installer and sample converter (GPL-3.0) and the Terminus font (SIL OFL), unchanged and credited in `VENDORED.md` |
| `fm1-bt-bridge/install.sh` | Installs packages, configuration and the boot services |
| `fm1-bt-bridge/config/` | PipeWire, WirePlumber, polkit, systemd, swap, Wi-Fi, network MIDI and SD-card configuration |
| `tests/` | A pretend FM-1 speaking SLOOP's protocol, and tests for everything else (`python tests/test_library.py` etc.; needs mido, Pillow and numpy) |
| `tools/render_screens.py` | Draws the screens as PNG files for this README, without a Pi |
| `tools/midi_timing.py` | Analyses the Bluetooth MIDI timing log |
| `docs/` | The images and videos on this page |
</details>

## License

GPL-3.0, like SLOOP. See [LICENSE](LICENSE).

The Studio's palettes and track colours are SLOOP's (isod89/sloop-fm1, GPL-3.0), and its font is Terminus by
Dimitar Toshkov Zhekov (SIL Open Font License 1.1), as SLOOP ships it.

**Copied into this repository** (each with its licence beside it):

| What | From | Licence |
|---|---|---|
| `fm1-bt-bridge/vendor/sloop/` (`fm1_install.py`, `sampleio.py`) | [SLOOP](https://github.com/isod89/sloop-fm1), unchanged ([VENDORED.md](fm1-bt-bridge/vendor/sloop/VENDORED.md)) | GPL-3.0-only |
| `fm1-bt-bridge/vendor/fonts/` (Terminus) | Dimitar Toshkov Zhekov, as SLOOP ships it ([VENDORED.md](fm1-bt-bridge/vendor/fonts/VENDORED.md)) | SIL Open Font License 1.1 |
| `fm1-bt-bridge/kits/808/` (the 808 KIT's sixteen sounds) | Michael Fischer's recordings of a Roland TR-808 (1994), from [tidalcycles/sounds-tr808-fischer](https://github.com/tidalcycles/sounds-tr808-fischer) ([CREDITS.md](fm1-bt-bridge/kits/808/CREDITS.md)) | CC0 1.0 |

**Built on** Raspberry Pi OS and its packages (PipeWire, BlueZ, Python, Pillow, NumPy, mido and others),
each under its own licence: [the full list](docs/CREDITS.md).
