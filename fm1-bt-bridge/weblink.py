"""The box's side of the web page (mixed into bridge.App): its live status for the page, and the page's commands.

The page (web.py, a process of its own) reads library.STATUS and queues commands in library.COMMANDS; the box
writes the status about once a second when something changed (monitor thread) and takes the commands on its
main loop, so they go through the same code as the joystick. Writes to the FM-1's data (restore, loads,
firmware) aren't commands: they still wait for a hold-press on the box (library.ask_box).
"""
import re
import time

import blemidi
import library

SETTINGS = ("metronome", "bpm", "clock_mode", "click", "audio_rate", "auto_backup", "output")
OUTPUTS = ("both", "speaker", "phones")       # the "output" setting: where the sound goes when there's a jack


def library_auto_choices():
    from libui import AUTO_CHOICES          # off, at start, every 2-30 min
    return AUTO_CHOICES


class WebLink:
    def web_init(self):
        self.web_shown, self.web_written = None, 0.0     # the status last written for the page, and when

    def web_status(self):
        """everything the page shows, as plain JSON"""
        midi, clock = self.midi, getattr(self.midi, "clock", None) if self.midi else None
        keys = self.keys_route()
        return {
            "fm1": self.source and ((self.fw_label or self.source["label"]) + (" + B" if self.source_b else "")),
            "live": self.live(),
            "mixer": ([{"key": k, "label": self.channel_name(k, n), "level": self.mix_level(k),
                        "input": self.input_label(k, n)} for k, n in self.mix_channels()]
                      if len(self.mix_channels()) > 1 else None),
            "speaker": self.sink and self.sink["label"], "speaker_name": self.state["last_name"],
            "connecting": self.connecting, "volume": self.volume, "battery": self.battery,
            "midi": {"peer": midi and midi.peer, "enabled": bool(midi and midi.enabled), "usb": midi and midi.usb_label(),
                     "error": midi and midi.error, "controllers": list(getattr(midi, "controllers", None) or []),
                     "usb_b": getattr(midi, "usb_b", None), "net": list(getattr(midi, "net", None) or []),
                     "pads": bool(getattr(midi, "pads", False))},
            "matrix": dict(zip(("sources", "dests"), self.matrix_lists())),
            "clock": clock, "clock_text": self.clock_text(),
            "recording": int(self.recorder.seconds()) if self.recorder.recording() else None,
            "settings": dict({k: self.state[k] for k in SETTINGS}, arp_on=keys["arp_on"], chord_on=keys["chord_on"],
                             arp=keys["arp"], arp_rate=keys["arp_rate"], chord=keys["chord"]),
            "routes": self.routes(), "presets": self.presets(), "wifi": self.wifi,
            "link": self.link_status(),       # the Pocket's Studio link (None on the Studio)
            "theme": self.theme_status(),     # the Pocket's colour screen's theme (None: no colour screen)
            "jack": bool(self.jack),          # a 3.5 mm jack to choose with "output" (the Studio's)
            "speaker_saved": bool(self.state.get("last_mac")),   # one to connect / disconnect
        }

    def theme_status(self):
        """the Pocket's theme and its choices ("follow": FM-1 A's), or None without a colour screen"""
        if self.desk or not getattr(self.display, "colour", False):
            return None
        import sloopstyle
        return {"value": self.state.get("desk_theme", "follow"), "choices": ["follow", *sloopstyle.ALL]}

    def web_publish(self):
        """called by the monitor thread every second: the status file, rewritten when it changed, and every 2 s
        anyway (the page takes a status over 5 s old to mean the box isn't running). A small file in RAM."""
        status, now = self.web_status(), time.monotonic()
        if status != self.web_shown or now - self.web_written >= 2:
            try:
                library.write_status(status)
                self.web_shown, self.web_written = status, now
            except OSError:
                pass

    def web_commands(self):
        """called by the main loop: apply what the page asked for"""
        for command in library.take_commands():
            try:
                text = self.web_command(command)
            except (KeyError, TypeError, ValueError) as e:
                text = f"Web: {str(e)[:30]}"
            if text:
                self.say(text, 1.5)

    def web_command(self, c):
        """one command from the page -> a short message for the screen. Values are checked here too: the page
        checks them, but the commands file is the only door and it gets the same care."""
        cmd = c.get("cmd")
        if cmd == "set":
            key, value = c["key"], c["value"]
            if key in ("metronome",) and isinstance(value, bool):
                self.state[key] = value
                self.save_settings()
                return f"Web: Metronome {'on' if value else 'off'}"
            if key == "bpm" and isinstance(value, (int, float)) and 30 <= value <= 300:
                self.set_clock(bpm=value)
                return f"Web: Tempo {self.state['bpm']}"
            if key == "clock_mode" and value in ("follow", "box"):
                self.set_clock(mode=value)
                return f"Web: Clock {value}"
            if key == "click" and value in ("low", "mid", "high"):
                self.state["click"] = value
                self.save_settings()
                return f"Web: Click {value}"
            if key == "audio_rate" and value in (44100, 48000):
                if value != self.state["audio_rate"]:
                    self.state["audio_rate"] = value
                    self.save_settings()
                    self.loop.reopen(value)
                    self.mixer.reopen(value)
                return f"Web: Audio {value / 1000:g} kHz"
            if key in ("arp_on", "chord_on") and isinstance(value, bool):
                if self.keys_route()[key] != value:
                    self.toggle_keys(key)
                return None                   # toggle_keys says it
            if re.fullmatch(r"mix_(a|b|usb|u-[a-z0-9]+)", key) and isinstance(value, int) and 0 <= value <= 200:
                self.set_mix_level(key[4:], value)
                return None
            if re.fullmatch(r"input_u-[a-z0-9]+", key):          # a multichannel source: its next pair
                pair = self.next_input_pair(key[6:])
                return pair and f"Web: inputs {pair}"
            if key == "auto_backup" and not isinstance(value, bool) and value in library_auto_choices():
                self.state["auto_backup"] = value
                self.last_auto = time.monotonic()
                self.save_settings()
                return f"Web: Auto backup {self.auto_label(value)}"
            if key == "output" and value in OUTPUTS:
                self.state["output"] = value
                self.save_settings()
                self.scan_now = True
                return f"Web: Output {value}"
            if key == "theme" and self.theme_status() and value in self.theme_status()["choices"]:
                self.state["desk_theme"] = value
                self.save_settings()
                self.theme_check = 0.0        # (pocket_theme looks again now)
                return f"Web: Theme {'FM-1 A' if value == 'follow' else value}"
            if key in ("studio_link", "link_audio") and isinstance(value, bool) and not self.desk:
                (self.set_studio_link if key == "studio_link" else self.set_link_audio)(value)
                return None                   # (they say it)
            if key == "volume" and isinstance(value, int) and 0 <= value <= 100 and self.sink:
                self.volume_to(value)
                return None
            raise ValueError(f"bad setting {key}")
        if cmd == "transport" and c.get("value") in ("start", "stop"):
            if self.midi:
                self.playing = c["value"] == "start"
                self.midi.transport(c["value"])
            return f"Web: {c['value'].title()}"
        if cmd == "speaker" and c.get("value") in ("connect", "disconnect"):
            if not self.state.get("last_mac"):
                raise ValueError("no speaker paired")
            self.reconnect() if c["value"] == "connect" else self.disconnect()
            return None                       # (they say it)
        if cmd == "record" and c.get("value") in ("start", "stop"):
            if (c["value"] == "start") != self.recorder.recording():
                self.toggle_recording()
            return None                       # toggle_recording says it
        if cmd == "routes":
            self.state["routes"] = self.keep_routes(blemidi.clean_routes(c.get("routes")))
            self.save_settings()
            if self.midi:
                self.midi.set_routes(self.routes())
            return "Web: MIDI routes"
        if cmd == "preset" and c.get("slot") in ("1", "2", "3", "4") and c.get("action") in ("load", "save", "clear"):
            name = c.get("name")
            self.preset_apply(c["slot"], c["action"], name if isinstance(name, str) else None)
            return None                       # preset_apply says it
        raise ValueError(f"bad command {cmd}")
