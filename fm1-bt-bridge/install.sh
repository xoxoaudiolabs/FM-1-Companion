#!/usr/bin/env bash
# FM-1 Companion installer for Raspberry Pi OS Lite (Bookworm or Trixie, 32- or 64-bit): the Pocket (a Pi Zero W
# or Zero 2 W with a Waveshare Zero screen HAT) or the Studio (Pi 3/4 + 3.5" SPI touchscreen), told apart by the
# board.
# Run as your normal user (not with sudo):  bash install.sh
# The Pocket's screen is asked for; to answer it ahead:  FM1_SCREEN=oled|lcd144|lcd13|ask bash install.sh
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
    echo "Run this as your normal user, not root: bash install.sh" >&2
    exit 1
fi
DIR="$(cd "$(dirname "$0")" && pwd)"
MODEL="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || true)"
case "$MODEL" in
    *Zero*) BUILD=pocket ;;
    *)      BUILD=desk ;;
esac
echo "== $MODEL: the $([ "$BUILD" = desk ] && echo Studio || echo Pocket)"

# Before anything is installed: what the Companion can't run without, said plainly
stop() { echo; echo "Can't install: $*" >&2; exit 1; }
if [ "$BUILD" = pocket ] && ! ls /sys/class/bluetooth/hci* >/dev/null 2>&1; then
    stop "this Pi has no Bluetooth. A Pi Zero, Zero 1.3 or Zero H has no wireless: the Pocket needs a Pi Zero W, \
Zero WH or Zero 2 W. (On one of those, check Bluetooth isn't switched off with dtoverlay=disable-bt in config.txt.)"
fi
command -v raspi-config >/dev/null || stop "this isn't Raspberry Pi OS (no raspi-config). Flash Raspberry Pi OS Lite \
with Raspberry Pi Imager."
. /etc/os-release
case "${VERSION_CODENAME:-}" in
    bookworm|trixie) ;;
    *) [ -n "${FM1_ANY_OS:-}" ] || stop "Raspberry Pi OS ${VERSION_CODENAME:-unknown} isn't one it's made for: use Bookworm \
or Trixie (Raspberry Pi Imager's current Raspberry Pi OS Lite). To try anyway: FM1_ANY_OS=1 bash install.sh" ;;
esac
FREE_KB=$(df --output=avail -k / | tail -1)
[ "$FREE_KB" -ge 1000000 ] || stop "under 1 GB free on the card ($((FREE_KB / 1024)) MB). Use a card of 8 GB or more."

SCREEN_CHOICE=""
if [ "$BUILD" = pocket ]; then            # the HAT can't be asked which it is (SPI only talks one way)
    SCREEN_CHOICE="${FM1_SCREEN:-}"
    if [ -z "$SCREEN_CHOICE" ] && [ -t 0 ]; then
        echo
        echo "Which screen HAT is on the Pi?"
        echo "  1) 1.3\" OLED (black and white, 128x64)"
        echo "  2) 1.44\" LCD (colour, 128x128)"
        echo "  3) 1.3\" LCD (colour, 240x240)"
        echo "  4) Not sure: the box asks on its first start (press KEY1 when you can read it)"
        read -r -p "1-4 [4]: " answer
        case "$answer" in 1) SCREEN_CHOICE=oled ;; 2) SCREEN_CHOICE=lcd144 ;; 3) SCREEN_CHOICE=lcd13 ;; *) SCREEN_CHOICE=ask ;; esac
    fi
    case "$SCREEN_CHOICE" in oled|lcd144|lcd13|ask|"") ;; *) stop "FM1_SCREEN must be oled, lcd144, lcd13 or ask" ;; esac
fi

echo "== Your password is needed once, for sudo"
sudo -v
while kill -0 "$$" 2>/dev/null; do sudo -n true; sleep 50; done 2>/dev/null &   # keep sudo for the whole install

echo "== Installing packages (this takes a while: several minutes, longest on a Pi Zero)"
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    pipewire wireplumber libspa-0.2-bluetooth dbus-user-session rtkit bluez \
    python3-pil python3-spidev python3-libgpiod fonts-dejavu-core \
    python3-dbus python3-gi python3-mido python3-rtmidi python3-numpy python3-smbus2 i2c-tools
if [ "$BUILD" = desk ]; then              # USB drives for the DJ decks: mounted, FAT / exFAT / NTFS
    sudo apt-get install -y --no-install-recommends udisks2 exfatprogs ntfs-3g
fi

echo "== Enabling SPI for the screen, Bluetooth, and permissions"
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0       # a PiSugar 3 battery, if there's one, answers on I2C
sudo rfkill unblock bluetooth || true
sudo systemctl enable --now bluetooth
sudo usermod -aG bluetooth,gpio,spi,i2c,audio "$USER"
# USB at full speed, Pocket only: the Zero's USB can't drive a USB 2 hub at high speed (devices behind it
# time out), and the FM-1 and USB keyboards are full-speed devices anyway. (A Pi 3/4's built-in ports need
# none of it.) Takes effect at the next boot.
CMDLINE=/boot/firmware/cmdline.txt
[ -f "$CMDLINE" ] || CMDLINE=/boot/cmdline.txt
if [ "$BUILD" = pocket ] && ! grep -q "dwc_otg.speed=1" "$CMDLINE"; then
    sudo cp "$CMDLINE" "$CMDLINE.bak"
    sudo sed -i '1 s/$/ dwc_otg.speed=1/' "$CMDLINE"
fi
# The Studio: no console text on its screens (its boot screen shows from early in boot instead, and HDMI
# mirrors the screen), no blinking cursor, no logo
for opt in vt.global_cursor_default=0 fbcon=map:9 logo.nologo; do
    if [ "$BUILD" = desk ] && ! grep -q "$opt" "$CMDLINE"; then
        sudo cp "$CMDLINE" "$CMDLINE.bak"
        sudo sed -i "1 s/\$/ $opt/" "$CMDLINE"
    fi
done
# The Studio's 3.5" touchscreen (ILI9486 display, XPT2046 touch: the common "3.5 inch RPi LCD"): the kernel's
# own driver, a framebuffer at /dev/fb1 and a touch input device; landscape. Not the seller's LCD-show script,
# which replaces system files. Takes effect at the next boot.
CONFIG=/boot/firmware/config.txt
[ -f "$CONFIG" ] || CONFIG=/boot/config.txt
# Raspberry Pi OS from 2026 no longer ships waveshare35a: piscreen is the same chips on the same pins (display on
# CE0, DC GPIO24, reset GPIO25; touch on CE1, its interrupt GPIO17). Its fbtft driver, not its DRM one (drm):
# on the Hosyond 3.5" the DRM driver's start-up leaves the panel white (tested 2026-10-24). 24 MHz SPI: clean on
# that panel and half again the frames of 16 MHz (the meters smoother; tested 2026-10-24).
if [ -f "$(dirname "$CONFIG")/overlays/waveshare35a.dtbo" ]; then
    SCREEN="dtoverlay=waveshare35a,rotate=90"
else
    SCREEN="dtoverlay=piscreen,speed=24000000,rotate=90"
fi
if [ "$BUILD" = desk ] && ! grep -q "^dtoverlay=\(waveshare35a\|piscreen\|mipi-dbi-spi\)" "$CONFIG"; then
    sudo cp "$CONFIG" "$CONFIG.bak"
    printf '
[all]
# FM-1 Companion Studio: the 3.5" touchscreen
dtparam=spi=on
%s
' "$SCREEN" | sudo tee -a "$CONFIG" >/dev/null
fi

if [ "$BUILD" = desk ]; then              # the boot screen as soon as the touchscreen appears (deskboot.py)
    echo "== The Studio's boot screen, early in boot"
    printf 'SUBSYSTEM=="graphics", KERNEL=="fb[0-9]", ATTR{name}=="fb_ili9486|ili9486drmfb", RUN+="/bin/sh -c '"'"'test -f %s && cat %s > /dev/%%k'"'"'"\n' \
        "$HOME/.local/share/fm1-bridge/splash.raw" "$HOME/.local/share/fm1-bridge/splash.raw" \
        | sudo tee /etc/udev/rules.d/90-fm1-splash.rules >/dev/null
fi

if [ "$BUILD" = desk ]; then              # network MIDI for a DAW (Kraken): listed for computers to find
    echo "== Announcing the Studio's network MIDI (FM-1 Companion, FM-1 Companion MCU)"
    sudo install -D -m 644 "$DIR/config/fm1-midi.service" /etc/avahi/services/fm1-midi.service
    sudo install -D -m 644 "$DIR/config/fm1-midi-mcu.service" /etc/avahi/services/fm1-midi-mcu.service
fi

echo "== Letting the bridge shut down, switch Wi-Fi and copy backups to the SD card without a password"
sudo install -m 755 "$DIR/config/fm1-sd-sync" /usr/local/sbin/fm1-sd-sync
sudo install -m 755 "$DIR/config/fm1-screen" /usr/local/bin/fm1-screen    # which screen HAT, over SSH
sudo install -m 755 "$DIR/config/fm1-report" /usr/local/bin/fm1-report    # a report to paste into an email or issue
SUDOERS=/etc/sudoers.d/fm1-bridge
printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff, /usr/bin/nmcli radio wifi on, /usr/bin/nmcli radio wifi off, /usr/local/sbin/fm1-sd-sync\n' \
    "$USER" | sudo tee "$SUDOERS" >/dev/null
sudo chmod 440 "$SUDOERS"
sudo visudo -cf "$SUDOERS"

echo "== Letting the web page use port 80 (http://$(hostname).local) without root"
echo "net.ipv4.ip_unprivileged_port_start=80" | sudo tee /etc/sysctl.d/50-fm1-bridge.conf >/dev/null
sudo sysctl -q -w net.ipv4.ip_unprivileged_port_start=80

echo "== Letting PipeWire run its audio threads in real time (no desktop session on a headless Pi)"
sed "s/FM1_USER/$USER/" "$DIR/config/50-fm1-bridge-rtkit.rules" | sudo tee /etc/polkit-1/rules.d/50-fm1-bridge-rtkit.rules >/dev/null
if [ "$BUILD" = desk ]; then
    echo "== Letting the DJ decks mount a USB drive of music when it's plugged in"
    sed "s/FM1_USER/$USER/" "$DIR/config/50-fm1-bridge-usb.rules" | sudo tee /etc/polkit-1/rules.d/50-fm1-bridge-usb.rules >/dev/null
fi

echo "== Installing the bridge"
install -D -m 755 "$DIR/bridge.py"                              ~/.local/share/fm1-bridge/bridge.py
install -D -m 644 "$DIR/blemidi.py"                             ~/.local/share/fm1-bridge/blemidi.py
install -D -m 644 "$DIR/sloop.py"                               ~/.local/share/fm1-bridge/sloop.py
install -D -m 644 "$DIR/libui.py"                               ~/.local/share/fm1-bridge/libui.py
install -D -m 644 "$DIR/meters.py"                              ~/.local/share/fm1-bridge/meters.py
install -D -m 644 "$DIR/midiui.py"                              ~/.local/share/fm1-bridge/midiui.py
install -D -m 644 "$DIR/metronome.py"                           ~/.local/share/fm1-bridge/metronome.py
install -D -m 644 "$DIR/battery.py"                             ~/.local/share/fm1-bridge/battery.py
install -D -m 644 "$DIR/lcd.py"                                 ~/.local/share/fm1-bridge/lcd.py
install -D -m 644 "$DIR/pocketui.py"                            ~/.local/share/fm1-bridge/pocketui.py
install -D -m 644 "$DIR/pocketmeters.py"                        ~/.local/share/fm1-bridge/pocketmeters.py
install -D -m 644 "$DIR/oledi2c.py"                             ~/.local/share/fm1-bridge/oledi2c.py
install -D -m 644 "$DIR/screenpick.py"                          ~/.local/share/fm1-bridge/screenpick.py
install -D -m 644 "$DIR/device.py"                              ~/.local/share/fm1-bridge/device.py
install -D -m 644 "$DIR/desk.py"                                ~/.local/share/fm1-bridge/desk.py
install -D -m 644 "$DIR/deskui.py"                              ~/.local/share/fm1-bridge/deskui.py
install -D -m 644 "$DIR/deskmeters.py"                          ~/.local/share/fm1-bridge/deskmeters.py
install -D -m 644 "$DIR/deskpages.py"                           ~/.local/share/fm1-bridge/deskpages.py
install -D -m 644 "$DIR/pads.py"                                ~/.local/share/fm1-bridge/pads.py
install -D -m 644 "$DIR/deskpads.py"                            ~/.local/share/fm1-bridge/deskpads.py
install -D -m 644 "$DIR/deskdecks.py"                           ~/.local/share/fm1-bridge/deskdecks.py
install -D -m 644 "$DIR/padfx.py"                               ~/.local/share/fm1-bridge/padfx.py
install -D -m 644 "$DIR/deskboot.py"                            ~/.local/share/fm1-bridge/deskboot.py
install -D -m 644 "$DIR/netmidi.py"                             ~/.local/share/fm1-bridge/netmidi.py
install -D -m 644 "$DIR/sloopstyle.py"                          ~/.local/share/fm1-bridge/sloopstyle.py
install -D -m 644 "$DIR/weblink.py"                             ~/.local/share/fm1-bridge/weblink.py
install -D -m 644 "$DIR/samplefast.py"                          ~/.local/share/fm1-bridge/samplefast.py
install -D -m 644 "$DIR/sampler.py"                             ~/.local/share/fm1-bridge/sampler.py
install -D -m 644 "$DIR/sampleui.py"                            ~/.local/share/fm1-bridge/sampleui.py
install -D -m 755 "$DIR/library.py"                             ~/.local/share/fm1-bridge/library.py
install -D -m 644 "$DIR/x0x.py"                                 ~/.local/share/fm1-bridge/x0x.py
install -D -m 644 "$DIR/decks.py"                               ~/.local/share/fm1-bridge/decks.py
install -D -m 644 "$DIR/djlib.py"                               ~/.local/share/fm1-bridge/djlib.py
install -D -m 755 "$DIR/web.py"                                 ~/.local/share/fm1-bridge/web.py
mkdir -p ~/.local/share/fm1-bridge/vendor/sloop ~/fm1-library/backups ~/fm1-library/projects \
    ~/fm1-library/samples ~/fm1-library/firmware
install -m 644 "$DIR"/vendor/sloop/*                            ~/.local/share/fm1-bridge/vendor/sloop/
mkdir -p ~/.local/share/fm1-bridge/vendor/fonts
install -m 644 "$DIR"/vendor/fonts/*                            ~/.local/share/fm1-bridge/vendor/fonts/
mkdir -p ~/.local/share/fm1-bridge/icons
install -m 644 "$DIR"/icons/*.png                              ~/.local/share/fm1-bridge/icons/
mkdir -p ~/.local/share/fm1-bridge/kits/808       # the sampler's ready-made 808 KIT (pads.factory_kits copies it in)
install -m 644 "$DIR"/kits/808/*                               ~/.local/share/fm1-bridge/kits/808/
install -D -m 644 "$DIR/config/pipewire-10-fm1-bridge.conf"     ~/.config/pipewire/pipewire.conf.d/10-fm1-bridge.conf
install -D -m 644 "$DIR/config/wireplumber-51-fm1-bridge.conf"  ~/.config/wireplumber/wireplumber.conf.d/51-fm1-bridge.conf
if wireplumber --version 2>/dev/null | grep -q "Linked with libwireplumber 0\.4"; then   # Bookworm: Lua config
    install -D -m 644 "$DIR/config/wireplumber-51-fm1-bridge.lua" ~/.config/wireplumber/bluetooth.lua.d/51-fm1-bridge.lua
else                                                                                # 0.5+ warns about Lua files
    rm -f ~/.config/wireplumber/bluetooth.lua.d/51-fm1-bridge.lua
fi
install -D -m 644 "$DIR/config/fm1-bridge.service"              ~/.config/systemd/user/fm1-bridge.service
install -D -m 644 "$DIR/config/fm1-web.service"                 ~/.config/systemd/user/fm1-web.service

if [ "$BUILD" = desk ] && [ ! -f ~/.local/share/fm1-bridge/splash.raw ]; then   # the first boot's picture
    (cd ~/.local/share/fm1-bridge && python3 -c "import deskboot, sloopstyle; deskboot.save(sloopstyle.Theme())")         || echo "   (the boot screen's picture comes with the first start instead)"
fi

echo "== Booting faster (on Trixie a Zero W otherwise takes ~3 minutes before the Companion starts)"
# cloud-init only applies Raspberry Pi Imager's settings on the first boot, but costs ~40 s on every boot
sudo touch /etc/cloud/cloud-init.disabled
# start the user services (PipeWire, the bridge) without waiting for NetworkManager
sudo install -m 644 "$DIR/config/systemd-user-sessions.service" /etc/systemd/system/systemd-user-sessions.service
# swap in RAM only: the default file-backed swap is rebuilt on every boot (~20 s)
sudo install -D -m 644 "$DIR/config/rpi-swap-50-fm1-bridge.conf" /etc/rpi/swap.conf.d/50-fm1-bridge.conf
sudo systemctl daemon-reload

if [ -n "$SCREEN_CHOICE" ]; then             # the Pocket's screen, as answered above (kept with its settings)
    python3 - "$SCREEN_CHOICE" <<'PY'
import json, sys
from pathlib import Path
f = Path.home() / ".config/fm1-bridge/fm1-bridge.json"
try:
    d = json.loads(f.read_text())
except (OSError, ValueError):
    d = {}
d["screen"] = sys.argv[1]
f.parent.mkdir(parents=True, exist_ok=True)
f.write_text(json.dumps(d, indent=2))
PY
fi

echo "== Starting at boot without a login"
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable pipewire.socket wireplumber.service fm1-bridge.service fm1-web.service
sync                                    # on the card before anyone pulls the power

echo
echo "Installed on:  $MODEL ($(nproc) cores), ${PRETTY_NAME:-Raspberry Pi OS} $(dpkg --print-architecture)"
if [ "$BUILD" = pocket ]; then
    echo "Screen:        $(fm1-screen 2>/dev/null | sed 's/^screen: //') (change it with: fm1-screen oled|lcd144|lcd13|ask)"
fi
echo
echo "Done. Reboot now:  sudo reboot"
if [ "$BUILD" = desk ]; then
    echo "After the reboot: the boot screen, then HOME (on the first install, the touch setup first: four targets)."
else
    echo "After the reboot the screen shows the Companion. If it is upside down, see README.md."
    echo "Once everything works, turn Wi-Fi off on the device: joystick right > Wi-Fi."
    echo "Trouble? Run fm1-report and send what it prints."
fi
