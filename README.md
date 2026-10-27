# FM-1 Companion

**A studio sidekick for the M-VAVE FM-1 pocket synth.** Bluetooth audio and MIDI, a mixer, a recorder that keeps
the MIDI too, a sample editor, eleven meters (ten on the Studio) and a MIDI matrix, with no computer needed once
it's set up. By
[XOXO Audio Labs](https://xoxoaudiolabs.com).

**[xoxoaudiolabs.com](https://xoxoaudiolabs.com)** · [The Pocket](https://xoxoaudiolabs.com/products/fm1-companion-pocket/)
· [The Studio](https://xoxoaudiolabs.com/products/fm1-companion-studio/) ·
[Try the web app](https://xoxoaudiolabs.com/app/) (sample data, in your browser)

| The Studio | The Pocket |
|---|---|
| [![The Studio tour: its touch screens, the sampler, the sequencer, the meters, with each tap shown](docs/images/studio-preview.gif)](https://cdn.jsdelivr.net/gh/xoxoaudiolabs/FM-1-Companion@main/docs/video/fm1-companion-studio-v1.3.mp4) | [![The Pocket demo: the box's screens and meters, with the button presses shown](docs/images/demo-preview.gif)](https://cdn.jsdelivr.net/gh/xoxoaudiolabs/FM-1-Companion@main/docs/video/fm1-companion-demo-v2.6.1.mp4) |
| **[▶ Watch the Studio tour](https://cdn.jsdelivr.net/gh/xoxoaudiolabs/FM-1-Companion@main/docs/video/fm1-companion-studio-v1.3.mp4)** (1:12, with sound): HOME, the mixer with cue, ten meters, the sampler, SLOOP's sequencer and FX, the recorder, MIDI and MORE, with each tap shown (drawn by the Studio's own code on a computer, not filmed). Two FM-1s and an SMK-37 played by Claude over MIDI, recorded by the Studio. | **[▶ Watch the Pocket demo](https://cdn.jsdelivr.net/gh/xoxoaudiolabs/FM-1-Companion@main/docs/video/fm1-companion-demo-v2.6.1.mp4)** (1:46, with sound): the box's own screens (drawn by its code on a computer, not filmed), all eleven meters, the settings, the MIDI matrix and the sample editor, with an overlay of each button press. The music was played on the FM-1 and recorded by the box. |

<img src="docs/images/device-with-fm1.jpg" width="560" alt="The Pocket on its PiSugar battery, cabled to the FM-1 running SLOOP">

It started as a way to add the Bluetooth that custom FM-1 firmware such as [SLOOP](https://github.com/isod89/sloop-fm1)
leaves switched off, and grew from there. Plug it into the FM-1 by USB and run it from its own screen or from
your phone.

## Two builds, one codebase

| | **The Pocket** | **The Studio** |
|---|---|---|
| Computer | Raspberry Pi Zero W | Raspberry Pi 3 B+ |
| Screen and controls | 1.3" OLED, joystick and three keys (Waveshare HAT) | 3.5" 480×320 touchscreen, in SLOOP's style and colours |
| Battery | PiSugar 3 | PiSugar 3 Plus (5000 mAh) |
| Adds | Fits in a pocket | SLOOP and X0X running on the Studio itself, played from an FM-1; DJ decks played from a Hercules DJ controller; an MPC-style sampler with SLOOP's sequencer, punch-in FX and an 808 kit, a recorder, a headphone jack with DJ-style cue, every USB MIDI device routed on its own, a DAW control surface (Kraken; Ableton Live untested), four USB ports, Ethernet, HDMI out |
| Software | v2.9 | Studio v1.6, and newer work on main (running on the real hardware since October 2026) |
| More | [Product page](https://xoxoaudiolabs.com/products/fm1-companion-pocket/) | [Product page](https://xoxoaudiolabs.com/products/fm1-companion-studio/) |

The installer works out which build it's on, and each build only shows what its hardware can do.

## What it does

What's been tried on the real boxes, and what hasn't yet: [Tested on the real hardware](#tested-on-the-real-hardware).

- **Wireless audio and MIDI.** The FM-1 plays on Bluetooth headphones or a speaker, and the box shows up as a
  Bluetooth MIDI device, **"FM-1 Companion"**, so a phone, iPad, computer, or a keyboard that connects to
  Bluetooth MIDI devices itself, can play the FM-1. New in v2.9, and not tried with real devices yet: it also
  connects to keyboards that wait to be connected to (a microKEY Air, a WIDI), and takes several Bluetooth MIDI
  devices at once.
- **SLOOP and X0X on the Studio** (Studio v1.4 to v1.6). [SLOOP](https://github.com/isod89/sloop-fm1)'s and
  [X0X](https://github.com/charlesvestal/fm1-x0x)'s own engines, sequencers and screens, compiled for the Studio's
  Pi, played from a real FM-1 whose SLOOP sends its keys, buttons and knobs over MIDI. Each is in its own repo:
  [SLOOP Remote Out](https://github.com/xoxoaudiolabs/sloop-remote-out) (SLOOP with a REMOTE OUT for the FM-1, and
  its `studio/` program) and [X0X for the FM-1 Companion Studio](https://github.com/xoxoaudiolabs/fm1-x0x-companion-studio)
  (below).
- **DJ decks on the Studio** (Studio v1.6). Two decks played from a Hercules DJControl Inpulse 200
  MK2 and the touchscreen, from a music folder whose BPM, key and beatgrids it reads (Serato's too) or works out:
  sync, hot cues, loops, rolls, EQ, PFL to the controller's own headphones ([below](#studio-v16-dj-decks)).
- **More keyboards, a second FM-1.** Through a USB hub (or the Studio's four ports): up to four USB MIDI
  keyboards and a second FM-1, found by themselves. **FM-1 A** and **FM-1 B** keep their names by the hub
  port they're on.
- **A mixer.** Every sound source gets its own level, 0–200%: each FM-1 and each USB audio device (a
  keyboard's own synth, a mic, an audio interface), added up before Bluetooth.
- **A recorder and a sample editor.** Record to WAV, play takes back, and turn a take into a sample: trim,
  fade, normalize, reverse and tune it to its note, ready to load into the FM-1. **Record parts** also keeps
  each source as its own file next to the mix, and each take gets a `.mid` of what was played, a track a source
  (on main since Studio v1.6; tried on the Studio).
- **Playing tools.** MIDI clock (follow, or lead with tap tempo and Start/Stop), metronome, arpeggiator and
  chord memory.
- **A MIDI matrix.** Route Bluetooth, USB keyboards, the FM-1s and the box to each other: transpose,
  re-channel, reshape velocity and filter, with four presets.
- **Eleven meters.** LED bars, VU needles, spectrum, scope, a reel-to-reel tape deck, a tuner, a keyboard view,
  a waterfall, a stereo goniometer, a level history and a beat counter (the Studio shows ten, without the tuner).
- **Looks after the FM-1 (SLOOP 2.3+).** Back up and restore everything on it (by hand or automatically), load
  projects and samples, and install firmware: [SLOOP](https://github.com/isod89/sloop-fm1), or isod89's
  experimental [Clipper](https://github.com/isod89/clipper-fm1). Backups are SLOOP's own files, so they open in
  SLOOP's web editor too.
- **A web app on your phone** at `http://<the box's hostname>.local`, such as `http://fm1bridge.local` (Wi-Fi,
  or Ethernet on the Studio): live status, the mixer, the MIDI matrix, a sample editor with a waveform you drag,
  your recordings and the library.
  Installable on your home screen. [Try it with sample data](https://xoxoaudiolabs.com/app/).
- **A sampler (the Studio).** 16 pads in kits, an MPC's or laid out as SLOOP's drum track. Sample any source onto a
  pad, trim it in the touch sample editor, play it from the screen or any MIDI keyboard; a ready-made 808 kit (real
  TR-808 recordings, CC0) comes with it. SLOOP's drum sequencer for the pads (up to 64 steps, swing, ratchets,
  nudge, live recording), note repeat, and sixteen of SLOOP's punch-in FX (the original set: loops, stutter,
  reverse, tape stop, filters, crush, gate, echo, wobble).
- **A recorder and headphones (the Studio).** The RECORDER tab with the reel-to-reel deck; the Pi's 3.5 mm jack
  as a second output with no Bluetooth delay, a cue button on every source (DJ-style, before its fader) and a
  cue/main blend.
- **Plays with your DAW (the Studio).** A network MIDI device (RTP-MIDI) whose DAW tab is a Mackie Control
  surface for [Kraken](https://github.com/isod89/sodwave-site): 8 touch faders with track names, meters, pan,
  solo, mute and the transport. Ableton Live's Mackie Control should work too, but it hasn't been tried yet.
- **Coming:** 5-pin DIN MIDI in, out and thru, on an expansion card of its own (in development, in its own repository).

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

The same jobs on both boxes. Every image here is drawn by the Companion's own code on a computer
(`tools/render_screens.py`), except three captured on the real Studio: SLOOP, the DECKS screen, and the middle of
X0X's screen (X0X's own picture).

| | The Pocket | The Studio |
|---|---|---|
| **Home:** the FM-1s, the speaker, MIDI, the volume, the clock; LIVE and the battery | ![Pocket home](docs/images/screen-status.png) | ![Studio home](docs/images/desk-ui-home-theme.png) |
| **Mixer:** a level for each FM-1 and USB device, up to 200%, and Record parts | ![Pocket mixer](docs/images/screen-settings-mixer.png) | ![Studio mixer](docs/images/desk-ui-mix-theme.png) |
| **MIDI routes:** sources down the side, destinations across; FM-1 B and the Studio's NET when connected | ![Pocket MIDI routes](docs/images/screen-matrix-two.png) | ![Studio MIDI routes](docs/images/desk-ui-midi-theme.png) |
| **Meters:** eleven on the Pocket (ten on the Studio, no tuner), from LED bars to a tape deck and a waterfall | ![Pocket meter](docs/images/screen-meter-spectrum.png) | ![Studio meter](docs/images/desk-ui-meter-theme.png) |
| **Settings:** Playing, Audio, MIDI, Recordings, Sloop, FM-1; on the Studio, values with - / + by touch | ![Pocket settings](docs/images/screen-settings-play.png) | ![Studio settings](docs/images/desk-page-settings.png) |
| **Sample editor:** a take trimmed, faded and tuned into a sample for SLOOP; on the Studio, drag the markers | ![Pocket sample editor](docs/images/screen-editor.png) | ![Studio sample editor](docs/images/desk-ui-editor-theme.png) |
| **Recorder:** REC and the time; on the Studio, its own tab with the reel-to-reel deck | ![Pocket recording](docs/images/screen-status-rec.png) | ![Studio recorder](docs/images/desk-ui-rec-theme.png) |
| **Sampler** (the Studio): 16 pads, SLOOP's sequencer, punch-in FX | | ![Studio sampler](docs/images/desk-ui-pads-theme.png) |
| **DAW** (the Studio): a Mackie Control surface for Kraken (Ableton Live: untested) | | ![Studio DAW](docs/images/desk-ui-daw-theme.png) |

<details><summary>More of the Pocket's screens</summary>

| | | |
|---|---|---|
| ![Recording](docs/images/screen-status-rec.png) | ![Volume](docs/images/screen-status-volume.png) | ![Settings](docs/images/screen-settings.png) |
| Recording: REC and the time | Volume, in 2% steps | Settings: its sections |
| ![Sloop](docs/images/screen-settings-sloop.png) | ![FM-1](docs/images/screen-settings-fm1.png) | ![A route](docs/images/screen-route.png) |
| Sloop: backups, projects, samples | FM-1: firmware | A route: transpose, velocity, channels |
| ![A recording](docs/images/screen-recordings.png) | ![The note](docs/images/screen-editor-note.png) | ![Playing](docs/images/screen-player.png) |
| A recording: play, edit, parts, delete | The note it found by listening | A take playing |
| ![Speakers](docs/images/screen-speakers.png) | ![Firmware install](docs/images/screen-job.png) | ![Screensaver](docs/images/screen-screensaver.png) |
| Speakers found by a scan | A SLOOP update running | The screensaver |
</details>

<details><summary>Every meter on each box (eleven on the Pocket, ten on the Studio)</summary>

**The Pocket** (joystick left from home; up/down changes meter, press records)

![The Pocket's eleven meters](docs/images/screen-meters.png)

**The Studio** (MIXER > METERS; tap the meter for the next)

![The Studio's ten meters](docs/images/desk-meters.png)
</details>

## What's new

### Since Studio v1.6 (on main, not a numbered release yet): MIDI recording, an 808 kit, a speaker that comes back

- **MIDI recording:** each take the RECORDER makes now has a `.mid` beside its WAV, of the same name: the MIDI
  played into the box while it recorded, a track for each source (FM-1 A, FM-1 B, each USB keyboard by its own
  name, Bluetooth MIDI, Network MIDI), at the box's tempo when the take started. Its time 0 is the WAV's first
  sample, so both drop into a DAW lined up. A take recorded off the mixer (the usual one on the Studio: more than
  one source, the speaker) has its notes moved 72 ms later, the time its sound takes to get through the mixer into
  the take, measured on the Studio. Left out: clock and transport, SysEx, and an FM-1's channel 16 (its REMOTE
  OUT, the panel driving SLOOP or X0X). A note still held at the end is let go there. With nothing played, no
  `.mid` is made.
  - The tempo written in the file is the box's own (its clock, or the tempo setting): one an FM-1 plays at
    without the box following its clock isn't the file's, so the bars in a DAW won't match it (the notes are still
    at their times).
- **A ready-made 808 KIT for the sampler** (PADS › KITS), there the first time KITS opens: sixteen recordings of a
  real Roland TR-808 by Michael Fischer (1994, CC0 1.0), on SLOOP's drum keys
  ([where each comes from](fm1-bt-bridge/kits/808/CREDITS.md)).
  - Its sounds go into the samples folder (listed after your own) and can be moved, trimmed or swapped like any
    other. Deleted, the kit isn't made again, and a sample of the same name you have already is left alone.
  - Not affiliated with Roland: TR-808 is Roland's trademark.
- **KITS scrolls** (^ v) when there are more than four.
- **A speaker that comes back by itself is reconnected once:** switched on, a Bluetooth speaker calls the box it
  knows, and once (a JBL Go 3 on the Studio) that connection came up silent: connected, the box playing to it,
  nothing heard. So when the speaker connects by itself (not by the box's own connect), the box disconnects it and
  connects it again a few seconds in: a moment of silence, then sound. Never during a recording.
- **A source or speaker back after a short drop is heard again at once:** an FM-1 off USB for a few seconds (or a
  speaker reconnected) comes back as a new PipeWire node of the same name, and its sound path stayed unlinked: FM-1
  A's sound took 90 s to come back after a 5 s drop. Each sound path now notices its ends came back anew and is
  made again within the next look at PipeWire (about 2 s).

### Studio v1.6: DJ decks

| The DECKS screen on the real Studio (a capture of its screen), two tracks synced | MORE › DJ DECKS |
|---|---|
| ![The DECKS screen: deck A and deck B, each with its title, artist, BPM, key, time left, SYNC, its waveform with hot cues and the playhead, CUE / PLAY / SYNC / PFL; the crossfader; the track list with LOAD A and LOAD B](docs/images/studio-decks.png) | ![MORE with a DJ DECKS tile next to PLAY SLOOP and PLAY X0X](docs/images/desk-ui-more-theme.png) |

**MORE › DJ DECKS**: two DJ decks on the Studio, played from a **Hercules DJControl Inpulse 200 MK2** (the controller
they were made and tried with) and from the touchscreen.

- **The music:** `~/fm1-library/Studio DJ Music` (MP3, FLAC, WAV, AIFF, Ogg). **SCAN** reads each new track's
  title, artist, BPM, key (also as Camelot) and beatgrid from its tags, including what Serato DJ saved in it (its
  BPM, key, beatgrid and hot cues, in MP3 files), and works out the BPM, key and beat from the sound where the tags
  lack them, about 10 seconds a track on the Pi 3. Serato's stems files (`.serato-stems`) are Serato's own
  protected format and aren't used.
- **Each deck:** play, CUE as on a CDJ (stopped: it sets the cue and plays while held; PLAY tapped while CUE is held
  keeps it playing), the tempo fader (±8 %, up is slower), the jog wheel (VINYL off, as the decks start: it moves
  through the track and nudges; VINYL on: it scratches), 4 hot cues (pads in HOTCUE mode; SHIFT + pad deletes one),
  loops (LOOP IN: 4 beats from the nearest beat, LOOP OUT, SHIFT halves or doubles), loop rolls (pads in ROLL mode:
  1, 2, 4 or 8 beats while held, then on from where the track would have been), gain, LOW and HIGH EQ, a filter,
  the volume fader, PFL (the headphone button) and the crossfader.
- **SYNC** locks a deck to the other: its tempo and its beat, kept together while both play (a double or half tempo
  where that's nearer: a track tagged 70 BPM locks to one at 140). With both synced, the tempo fader moved last
  leads. Each track's beatgrid is moved onto its own kicks when it loads (a grid can sit some ms off them), and a
  nudge with the jog on a synced deck is kept.
- **The screen:** both decks (title, artist, BPM, key, time left, tempo, SYNC / LOOP), each track's waveform
  overview with where it's at and its hot cues (a line in the cue's colour with its pad's number: tap the number to
  go there, hold it to delete the cue; tap the waveform to go there), the crossfader, and the track list (the row
  the browser knob is on lit; LOAD A, LOAD B). < HOME goes back with the decks playing on; HOLD OFF stops them.
- **Sound:** the master to the Studio's Bluetooth speaker (with none, the Hercules's master out); the headphones
  (PFL) to the Hercules's own sound card: **the Hercules has its own sound card** (4 channels: master out and
  headphones), and its MASTER and HEADPHONES knobs work on it in its own hardware.
- **It remembers:** each track's hot cues and CUE point as set or deleted on the Studio (in
  `.studio-dj-memory.json` beside the music: nothing is written into the music files or their Serato tags), and the
  session: the decks come back loaded and paused where they were, with their tempo, SYNC, PFL and pad mode.
- **The Hercules belongs to the decks:** it's left out of the MIDI routes (its pads don't play the FM-1s).
- Not affiliated with Serato or Hercules: the decks read the cue points and beatgrids Serato DJ saves in a track's
  tags; Serato is a trademark of its owner.

### Studio v1.6: CUE for SLOOP and X0X

![The MIXER with CUE buttons under SLOOP and X0X too](docs/images/desk-ui-mix-theme.png)

- **CUE for SLOOP and X0X:** their MIXER columns have a CUE button too (on the 3.5 mm jack, as the FM-1s'; theirs
  after their fader, the others' before it).

### Studio v1.6: SLOOP and X0X together, in time

- **Both at once.** Opening PLAY X0X no longer stops SLOOP, or the other way round: one is on the screen, the other
  keeps playing behind it. MORE says ON for each one running; HOLD OFF stops only the one on the screen.
- **One clock.** The Companion connects each app's MIDI clock to the other, as two FM-1s cabled both ways. SLOOP
  leads by default (its CLK OUT starts ON on the Studio): PLAY on SLOOP starts both from the top, its tempo is
  both apps' tempo, STOP stops both; X0X shows its tempo in amber while it follows. To have X0X lead, set SLOOP's
  GLO › SYSTEM › SYNC to USB (SLOOP keeps both settings now). An app follows the other's clock only while the
  other plays, so one playing on its own isn't pulled off its beat when the other opens.
- **FM-1 A's own clock** is no longer passed to the apps, so it can't fight theirs.
- **Backups of the Studio's apps.** Settings › Sloop has a **For** row: **FM-1**, **SLOOP Studio** or **X0X
  Studio**.
  - **SLOOP Studio:** the Studio's SLOOP now keeps everything an FM-1's SLOOP keeps (its settings, the working
    project, the four project slots, the song's sections, user presets, the FM6 patches, the four sample slots),
    and Back up now, Restore, Load project and Load sample work on it as on an FM-1: the same jobs, the same files
    in `~/fm1-library`, so a backup of FM-1 A restores onto the Studio's SLOOP and the other way round. SLOOP has
    to be open (PLAY SLOOP) for them. Auto backups and the web page's requests still go to the FM-1.
  - **X0X Studio:** Back up now saves X0X's project as a `.x0b` in `~/fm1-library/x0x/`, X0X's own backup format
    (the one its backup page makes from an FM-1). Restore puts one back: X0X is stopped first (it saves), what it
    held is backed up first, and PLAY X0X opens it. Its break loops aren't in it (the Studio's X0X has none yet).
- It needs both apps rebuilt from their repos' current main (their `studio/` READMEs).
- **Tried:** by hand from FM-1 A, SLOOP leading; by a script, both directions; the backups by script on the
  Studio, not yet by hand. Details and what isn't tried yet: [Tested on the real hardware](#the-studio).

### Studio v1.5: X0X on the Studio

| X0X on the Studio (X0X's picture captured on the real Studio; the margins drawn by the Companion's code) | MORE › PLAY X0X, and X0X's level in the MIXER |
|---|---|
| ![X0X's HOME page in the middle of the Studio's screen: the 909, 808, 303A, 303B and BRK rows at 125 BPM; < HOME and HOLD OFF on the left, X0X's level with + and - on the right](docs/images/studio-x0x.png) | ![MORE with PLAY SLOOP and PLAY X0X tiles, both OFF](docs/images/desk-ui-more-theme.png) ![The MIXER with SLOOP and X0X channels next to the FM-1s](docs/images/desk-ui-mix-theme.png) |

[X0X](https://github.com/charlesvestal/fm1-x0x), Charles Vestal's groovebox firmware for the FM-1 (909, 808, two
303s with TB-3PO, a breakbeat player, song mode), running on the Studio itself, not emulated: its own code, built
for the Pi the way X0X's browser version is built. Its repo:
[X0X for the FM-1 Companion Studio](https://github.com/xoxoaudiolabs/fm1-x0x-companion-studio).

- **Played from the same FM-1 A** as SLOOP on the Studio: SLOOP Remote Out with REMOTE on **OUT 16**. X0X's panel
  is the FM-1's, so every control does what it does on an FM-1 running X0X.
- **MORE › PLAY X0X**, **< HOME**, **HOLD OFF**, its + / − and its MIXER channel work as SLOOP's do. In v1.5 one
  app runs at a time: starting X0X stops SLOOP (it saves first), and the other way round. From v1.6, both run at
  once with a shared clock (above).
- **It keeps what X0X saves** (settings, sounds, patterns, song) in a file of its own, loaded when it starts.
- **REMOTE OUT sends every knob now** (SLOOP Remote Out, updated): every turn of the seven knobs, on any page, and
  MASTER as CC 123, so the Studio's apps get the whole panel, not only what FM-1 A's own SLOOP page uses.
- **The recorder's clip warning no longer fires on deep sub-bass** (an 808 at 30–50 Hz has slow, flat-looking
  peaks): a take counts as clipped only when many of its peaks are cut off at the same level.

**Setting it up:** FM-1 A as for SLOOP below (steps 1 and 2), then on the Studio build and install X0X's
[`studio/`](https://github.com/xoxoaudiolabs/fm1-x0x-companion-studio/tree/main/studio) program (its README; about
1.5 minutes on the Pi). MORE then shows **PLAY X0X**.

**Tried on the real Studio:** X0X opened from PLAY X0X and played by hand from FM-1 A; stress tests by a script
(X0X alone, and X0X next to SLOOP), with no dropouts or audio errors. The details, and what hasn't been tried yet,
are in [Tested on the real hardware](#the-studio).

### Studio v1.4: SLOOP on the Studio

| SLOOP running on the real Studio (a capture of its screen) | MORE › PLAY SLOOP, and SLOOP's level in the MIXER |
|---|---|
| ![SLOOP's TRACKS page in the middle of the Studio's screen: PLUCK BASS, RHODES, LOFI FLUTE, 808 DRUMS; < HOME and HOLD OFF on the left, SLOOP's level with + and - on the right](docs/images/studio-sloop.png) | ![MORE with a PLAY SLOOP tile saying OFF](docs/images/desk-ui-more-theme.png) ![The MIXER with a SLOOP channel next to the FM-1s](docs/images/desk-ui-mix-theme.png) |

[SLOOP](https://github.com/isod89/sloop-fm1) running on the Studio itself, not emulated: its own sound engines,
sequencer and screens, compiled from its sources for the Pi through the harness its own tests use. On one of the
Pi 3's four cores, SLOOP's heaviest test case (a physical-model cello, 8 notes, and drums) takes about 8%.

- **Played from a real FM-1.** FM-1 A runs SLOOP with a REMOTE OUT added
  ([SLOOP Remote Out](https://github.com/xoxoaudiolabs/sloop-remote-out), from SLOOP 2.8.1):
  with GLO › MIDI 3 › REMOTE on **OUT 16**, its 14 buttons, 7 knobs and 27 keys also go out on MIDI channel 16, and
  the Companion passes them to SLOOP on the Studio. FM-1 A keeps playing its own SLOOP too: turn it down in the
  MIXER to hear only the Studio's.
- **MORE › PLAY SLOOP** turns it on (the tile says ON or OFF). SLOOP's picture fills the middle of the screen.
  **< HOME** (top left) goes back to the Companion with SLOOP still running, and playing if it was; PLAY SLOOP
  brings it back as it was. **HOLD OFF** (bottom left, held a second) saves and stops it.
- **Its own level:** + / − in the right margin while it plays, and a SLOOP channel in the MIXER, 0–200%.
- **It keeps its project:** the working project (tracks, sounds, steps, the song's settings, in SLOOP's own format)
  is saved a few seconds after a change and when it stops, and loaded when it starts.
- **In v1.4, not saved:** SLOOP's four project slots, user presets and sample slots lasted only while it ran.
  From v1.6 they're kept.

**Setting it up:**
1. Install SLOOP with REMOTE OUT on FM-1 A: build it from [SLOOP Remote Out](https://github.com/xoxoaudiolabs/sloop-remote-out)
   (as SLOOP builds: its [BUILDING.md](https://github.com/xoxoaudiolabs/sloop-remote-out/blob/main/BUILDING.md)),
   put the `.fwsc` in the library's firmware folder and install it from MORE › FM-1 › Install firmware (it backs
   the FM-1 up first). The official SLOOP goes back on the same way.
2. On FM-1 A: hold GLO, MIDI 3, turn REMOTE to **OUT 16**.
3. On the Studio: build and install its [`studio/`](https://github.com/xoxoaudiolabs/sloop-remote-out/tree/main/studio) program (its README;
   about 2 minutes on the Pi). MORE then shows **PLAY SLOOP**.

### Pocket v2.9 (and the Studio): Bluetooth MIDI keyboards

*Built, with automated tests, but not tried with a real keyboard or two real devices yet.*

| Settings › MIDI › BT keys (drawn by the Companion's code) |
|---|
| ![BT MIDI keys: microKEY Air and WIDI Master found by a scan](docs/images/screen-bt-keys.png) |

- **Keyboards that wait to be connected to** (a microKEY Air, a WIDI): Settings › MIDI › **BT keys** scans for
  Bluetooth MIDI and connects to the one you pick. Up to four are saved and connected again whenever they're on.
- **Several Bluetooth MIDI devices at once:** phones, tablets, computers and those keyboards, all the matrix's
  Bluetooth row and column. Each device's MIDI is read on its own, so in the automated tests two playing at once
  don't mix up their notes.

### Studio v1.3

The first release made on the real Studio, with a sampler, a recorder and headphones.

| The sampler: 16 pads in a kit | SLOOP's sequencer for the pads |
|---|---|
| ![The SAMPLER tab: 16 pads in four rows of SLOOP's track colours, two of them lit as they play](docs/images/desk-ui-pads-theme.png) | ![SEQ: the pads in two rows, 16 steps of the page, the playhead, LEN, DIV, SWG and QUANT](docs/images/desk-ui-seq-theme.png) |
| **Sixteen of SLOOP's punch-in FX** | **The recorder** |
| ![FX: sixteen pads, LOOP 8 latched](docs/images/desk-ui-fx-theme.png) | ![RECORDER: the reel-to-reel deck turning, STOP and TAKES](docs/images/desk-ui-rec-theme.png) |

- **SAMPLER.** 16 pads in kits (MPC notes 36-51, or SLOOP's drum layout so SLOOP's own sequencer plays them),
  sampled from any source, trimmed in the touch **EDITOR** (OPEN lists your samples and takes, TO PAD puts the
  edit on a pad). **SEQ**: SLOOP's drum sequencer, up to 64 steps a pattern with levels, ratchets, nudge, swing
  and live REC. **RPT**: note repeat. **FX**: sixteen of SLOOP's punch-in FX on the pads, held or latched.
- **RECORDER**, its own tab: the reel-to-reel deck, REC, Record parts and your takes.
- **Headphones.** The Pi's 3.5 mm jack: speaker, jack or both; a PHONES fader; a CUE button on each source
  (heard on the jack before its fader) and a cue/main blend, as on a DJ mixer.
- **Every USB MIDI device on its own.** The MIDI routes give each one a row and a column by name (an SMK-37,
  a K.O. Sidekick), remembered when it's unplugged. All four USB ports carry audio and MIDI at once; a second
  device of the same model is numbered.
- **An FM-1 keeps the clock.** With several USB audio devices, an FM-1 is the one the others are re-timed to:
  a keyboard's synth taking it over made the headphone jack drop out and everything crackle.
- **New screens:** a boot screen from power-on to HOME, a touch setup on first start, a cleaner tab bar
  (HOME, MIXER, SAMPLER, RECORDER, MIDI, MORE; METERS under MIXER, DAW under MIDI), MORE as tiles, smoother
  meters, an HDMI mirror of the screen.
- **Made for the real hardware:** the screen driver Raspberry Pi OS ships now (piscreen, at 24 MHz), touch
  calibration, the PiSugar 3 Plus, an SMK-37 running Clipper told apart from an FM-1.

| The boot screen | The MIDI routes, a device each |
|---|---|
| ![The Studio's boot screen: FM-1 COMPANION, STUDIO, the start-up's bar and XOXO//AUDIO//LABS](docs/images/desk-ui-boot-theme.png) | ![The MIDI routes with CLIPPER and EP-136 as rows and columns of their own](docs/images/desk-ui-midi-theme.png) |

**Connecting a DAW:** on the computer, open network MIDI (Mac: Audio MIDI Setup › MIDI Studio › Network;
Windows: the free rtpMIDI driver) and connect a session to each of the Studio's two ports. In Kraken, set the
port connected to "FM-1 Companion MCU" to Mackie; in Live, choose MackieControl as a control surface on that port.

### Pocket v2.8

| Two FM-1s in the MIDI routes | The mixer |
|---|---|
| ![MIDI routes with FM-1 A and FM-1 B rows and A and B columns](docs/images/screen-matrix-two.png) | ![Settings › Audio: FM-1 A level 100%, FM-1 B level 80%, USB keys level 175%](docs/images/screen-settings-mixer.png) |

- **Two FM-1s at once,** named A and B by their hub port, each with its own row and column in the MIDI routes.
- **An audio mixer:** each sound source at its own level, 0–200%, added up before Bluetooth.
- **Record parts (v2.8.1):** each source as its own file next to the mix, from one recording, so they line up to
  the sample.
- **Faster:** one connection to the audio system kept open, about half the CPU it took before.

<details><summary>Release history</summary>

**Studio**
- **v1.6:** DJ decks played from a Hercules DJControl Inpulse 200 MK2; SLOOP and X0X at once with one clock;
  backups of the Studio's SLOOP and X0X; CUE for SLOOP and X0X (above).
- **v1.5:** X0X on the Studio, played from FM-1 A; the recorder's clip check left deep sub-bass alone (above).
- **v1.4:** SLOOP on the Studio, played from FM-1 A (above).
- **v1.3:** the sampler (16 pads, SLOOP's sequencer, punch-in FX), the RECORDER tab, the headphone jack with cue,
  every USB MIDI device routed on its own (above).
- **v1.2:** every screen drawn for touch (settings, lists, route details, jobs), hold to confirm anything that
  writes to the FM-1, the sample editor by touch, Wi-Fi and Shut down in MORE.
- **v1.1:** network MIDI (RTP-MIDI) with a music port and a Mackie Control port; the DAW tab for Kraken (Ableton
  Live untested); every USB audio device on its own named mixer channel, with an input pair for multichannel
  interfaces.
- **v1.0:** the Studio's first release: tabs along the bottom, SLOOP's font, palettes and track colours,
  following FM-1 A's colour theme, the meters redrawn in colour (ten: no tuner), the card slot's pin map and
  card ID plan (the box doesn't read the ID yet; the cards' plans now live with the cards' own project).

**Pocket**
- **v2.8.3:** the shared fixes of Studio v1.3 (an SMK-37 running Clipper next to an FM-1 is a keyboard, not a
  third FM-1; FM-1 A's MIDI found by its sound card).
- **v2.8.2:** a long USB device name in Settings › Audio no longer runs into its level on the OLED.
- **v2.8:** two FM-1s, the mixer, a much lighter audio connection. **v2.8.1:** Record parts.
- **v2.7:** USB MIDI keyboards through a hub, found by themselves; the FM-1 can be replugged on the hub without a
  reboot (v2.7.1).
- **v2.6:** PiSugar 3 battery support (charge on screen, a warning at 15%, a safe shutdown at 5%); a new demo
  video; a warning when a recording clipped (v2.6.2).
- **v2.5:** the sample editor, on the box and in the web app.
- **v2.4:** settings in sections, a bigger web app, route presets by name, faster sample loads.
- **v2.3:** six more meters, the Recordings menu, metronome, arp and chord memory, faster screens.
- **v2.2:** recording to WAV, the Tape meter, MIDI clock and the MIDI matrix.
</details>

## Tested on the real hardware

What each box has been seen doing for real. Everything else in [What it does](#what-it-does) is built and has
automated tests, but hasn't been tried on the real box yet: it's in the second list until it has.

### The Pocket

A Pi Zero W on Raspberry Pi OS Lite (Trixie) with the Waveshare OLED HAT and a PiSugar 3; FM-1s on SLOOP 2.7 and
2.8; a JBL Go 3; an M-VAVE SMK-37 (over Bluetooth MIDI, and over USB through an ASMedia ASM1074 hub, running Baud
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

**Not tested on the real Pocket yet**
- Anything new in v2.9: v2.9 hasn't been on the Pocket yet. That's connecting to Bluetooth MIDI keyboards (BT keys)
  and several Bluetooth MIDI devices at once.
- The web app (tried only in a browser with sample data, [on the website](https://xoxoaudiolabs.com/app/)).
- The safe shutdown at 5% battery.
- Installing Clipper: downloaded and accepted by SLOOP's installer, never flashed to an FM-1.
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

### The demo videos

Both videos are drawn by the boxes' own screen code, rendered on a computer with each button press or tap shown;
they aren't filmed. Their audio is real: played on the FM-1s and recorded by the box.

## Known limits

- **Bluetooth audio delay:** about 150–250 ms (SBC). Fine for listening and practising; you'll notice it when
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

**Built on** (installed on the box by `install.sh` from Raspberry Pi OS's own packages, or already part of it; not
copied into this repository, and each under its own licence):

| Software | What the Companion uses it for | Licence |
|---|---|---|
| Raspberry Pi OS (Debian) and the Linux kernel | the system; the screens' drivers (fbtft, the SPI and I2C drivers) | GPL-2.0 (the kernel); Debian's packages each their own |
| PipeWire (with its tools `pw-cat`, `pw-record`, `pw-loopback` …) and its Bluetooth plugin | all the sound: the mixer, Bluetooth audio, recording, the Studio's apps | MIT, with some parts LGPL-2.1-or-later |
| WirePlumber (`wpctl`) | PipeWire's session manager; levels | MIT |
| BlueZ (`bluetoothctl`) | Bluetooth: speakers, Bluetooth MIDI | GPL-2.0-or-later (its libraries LGPL-2.1-or-later) |
| D-Bus | talking to BlueZ | GPL-2.0-or-later or AFL-2.1 (some parts MIT, BSD) |
| systemd | the Companion's services, library jobs | LGPL-2.1-or-later (some parts GPL-2.0-or-later) |
| NetworkManager (`nmcli`) | Wi-Fi on / off | GPL-2.0-or-later (its libraries LGPL-2.1-or-later) |
| RealtimeKit (rtkit) | real-time priority for the sound | GPL-3.0-or-later (some parts MIT) |
| Python 3 | the Companion itself | PSF License |
| Pillow | drawing every screen | the PIL Software License (MIT-CMU) |
| NumPy | meters, the sampler, the sample editor | BSD-3-Clause |
| mido and python-rtmidi (RtMidi) | MIDI | MIT |
| libsndfile, with mpg123 | the DJ decks reading MP3, FLAC, WAV, AIFF and Ogg | LGPL-2.1-or-later (some parts Apache-2.0); mpg123 LGPL-2.1 |
| dbus-python | BlueZ over D-Bus | MIT (some parts AFL-2.1 or GPL-2.0-or-later) |
| PyGObject | BlueZ's events (GLib) | LGPL-2.1-or-later |
| spidev, libgpiod's Python bindings, smbus2, i2c-tools | the Pocket's screen and keys; the PiSugar battery | MIT; LGPL-2.1-or-later; MIT; GPL-2.0-or-later |
| DejaVu fonts | the Pocket's text | Bitstream Vera / DejaVu licence (free) |

The licences are each project's own, as Debian lists them in each package's `/usr/share/doc/<package>/copyright`
on the box: that file is the one to go by. The Studio's apps (SLOOP Remote Out, X0X for the FM-1 Companion
Studio) are separate programs in their own repositories, each with its own list.
