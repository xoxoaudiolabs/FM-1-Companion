"""The Studio link's audio: the Pocket's sound to a Studio over the same cable (or Wi-Fi) as its MIDI (netmidi.py's
Invitation). Plain RTP audio (L16: 48 kHz, 16-bit, stereo, about 1.5 Mbit/s), which PipeWire sends and receives
itself (its rtp-sink and rtp-source modules), so no new program runs on either box: a PipeWire of its own hosts
the module, started and stopped from here.

The Pocket (Sender): a sink, "fm1-studio-link", whose sound goes to the Studio's address. The bridge plays into it
what the speaker would play (the mixer's or the FM-1's sound), or a copy of it when a speaker is there too.
The Studio (Receiver): a source, "fm1-pocket", from what arrives on PORT, for its mixer or its speaker.

Each FM-1 its own stream (a Studio that says "pocket_fm1s" in its /api/status): the Pocket's FM-1 A, B and C go
to FM1_PORTS (46002, 46004, 46006) on sinks of their own ("fm1-studio-link-a" ...), where the Studio names them
FM-1 E, F and G; PORT then carries the rest of the Pocket's sound (a keyboard's own, the pads) as POCKET. All the
streams from the one PipeWire. An older Studio gets the whole mix on PORT, as before.

As a snake (a Studio whose /api/status says "link_return"): the Studio sends its mix back to the Pocket on
RETURN_PORT, received here as MIX_BACK for the Pocket's USB sound card (bridge.py), and its "latency" step sets the
blocks both ends work in (LATENCY). The senders keep PipeWire's packet size (about 6.5 ms of sound): asked for
1-2 ms packets (sess.min-ptime / max-ptime), PipeWire's sender on a Pi Zero W missed its timer and dropped sound
("missing timeout", "overrun"), and so did the Studio's (tried 2026-11-01).
"""

import json
import os
import socket
import subprocess
import urllib.request
import zlib
import tempfile
from pathlib import Path

PORT = 46000                    # (PipeWire's own default for RTP audio)
SINK = "fm1-studio-link"        # the Pocket's: what goes to the Studio
SOURCE = "fm1-pocket"           # the Studio's: what comes from a Pocket
FM1_PORTS = {"A": 46002, "B": 46004, "C": 46006}   # the Pocket's FM-1s, each on its own (a Studio's FM-1 E-G)
RETURN_PORT = 46010             # the Studio's mix back to the Pocket (a Studio that says "link_return")
MIX_BACK = "fm1-studio-mix"     # the Pocket's: the Studio's mix, as it arrives
# the Studio's Latency steps (its MORE > AUDIO): PipeWire's block in samples, a link receiver's buffer in ms
LATENCY = {"SAFE": (1024, 40), "LOW": (512, 20), "LOWER": (256, 10), "LOWEST": (128, 6)}
POCKET_BLOCK = 512              # the smallest block the Pocket follows down to: a Pi Zero W's one core ran out at
                                # 256 with its FM-1, the snake's mix and a USB sound card (2026-11-01: crackle)
FORMAT = """      audio.format = "S16BE"
      audio.rate = 48000
      audio.channels = 2
      audio.position = [ FL FR ]"""


def config(module, args, name):
    """a PipeWire configuration that hosts one module and nothing else (as pipewire-aes67 does); module and args
    may be lists, for several of them in the one PipeWire"""
    modules = "\n".join(f"""  {{ name = {m}
    args = {{
{a}
{FORMAT}
    }}
  }}""" for m, a in (zip(module, args) if isinstance(module, list) else [(module, args)]))
    return f"""context.properties = {{ core.daemon = false core.name = {name} }}
context.spa-libs = {{ audio.convert.* = audioconvert/libspa-audioconvert support.* = support/libspa-support }}
context.modules = [
  {{ name = libpipewire-module-rt args = {{ }} flags = [ ifexists nofail ] }}
  {{ name = libpipewire-module-protocol-native }}
  {{ name = libpipewire-module-client-node }}
  {{ name = libpipewire-module-adapter }}
{modules}
]
"""


def fm1_sink(letter):
    """the Pocket's sink for its FM-1 letter (A-C), sent on its own"""
    return f"{SINK}-{letter.lower()}"


def fm1_source(letter):
    """the Studio's source for a Pocket's FM-1 letter (A-C)"""
    return f"{SOURCE}-{letter.lower()}"


def stream_id(stream=""):
    """this Pocket's RTP stream id (SSRC), the same every time from its host name: a Studio's receiver keeps to the
    first id it hears, so a sender started again (the link back after a restart) has to keep it. stream: "" for
    PORT's, an FM-1's letter for its own"""
    return zlib.crc32((socket.gethostname() + (f"/{stream}" if stream else "")).encode()) or 1


def sink_args(address, port, ssrc, name, description):
    return f"""      destination.ip = "{address}"
      destination.port = {port}
      rtp.ssrc = {ssrc}
      net.mtu = 1280
      sess.media = "audio"
      stream.props = {{ resample.quality = 1 node.name = "{name}" node.description = "{description}" media.class = "Audio/Sink" }}"""


def sender_config(address, port=PORT, ssrc=None, fm1s=()):
    """fm1s: the FM-1 letters sent on their own (FM1_PORTS), each a sink and stream of its own beside SINK's"""
    modules = [sink_args(address, port, ssrc or stream_id(), SINK, "Studio (link)")]
    modules += [sink_args(address, FM1_PORTS[x], stream_id(x), fm1_sink(x), f"Studio (link) FM-1 {x}") for x in fm1s]
    return config(["libpipewire-module-rtp-sink"] * len(modules), modules, "fm1-studio-link")


def receiver_config(port=PORT, latency_ms=40, name=SOURCE, description="Pocket (link)"):
    """latency_ms: what the Studio holds back to ride out the network's jitter (PipeWire's default is 100). For a
    Pocket's FM-1 on its own: FM1_PORTS[letter], fm1_source(letter). Any stream id (SSRC) is taken: a sender
    started again has a new one (seen: the Studio's mix back, refused packet by packet after its restart)"""
    return config("libpipewire-module-rtp-source", f"""      source.ip = "0.0.0.0"
      source.port = {port}
      sess.latency.msec = {latency_ms}
      sess.ignore-ssrc = true
      sess.media = "audio"
      stream.props = {{ resample.quality = 1 node.name = "{name}" node.description = "{description}" media.class = "Audio/Source" }}""",
                  "fm1-pocket-link" if name == SOURCE else name + "-link")


def studio_status(address, port=80, timeout=2.0):
    """what the Studio at address says of the link in its /api/status: {"fm1s": it takes the Pocket's FM-1s each on
    its own stream, "audio": what it wants of the Pocket's sound ("mix": one stream, "fm1s": each FM-1 on its own,
    "midi": none; None from an older Studio), "rec": its Linked REC is on (the Pocket's REC / STOP sent to it as
    MMC), "sees_pocket": it has a Pocket linked (None: it doesn't say), "return": the port its mix comes back on
    (None: it doesn't send it),
    "latency": its LATENCY step}; an older Studio, or one that doesn't answer: False, None and "SAFE"
    """
    try:
        with urllib.request.urlopen(f"http://{address}:{port}/api/status", timeout=timeout) as reply:
            status = json.loads(reply.read(1 << 20))
    except (OSError, ValueError):
        status = {}
    if not isinstance(status, dict):
        status = {}
    back = status.get("link_return")
    return {"fm1s": bool(status.get("pocket_fm1s")),
            "audio": status.get("link_audio") if status.get("link_audio") in ("mix", "fm1s", "midi") else None,
            "rec": status.get("link_rec") is True,
            "sees_pocket": bool(status["pocket"]) if "pocket" in status else None,
            "return": back if isinstance(back, int) and not isinstance(back, bool) and 0 < back < 65536 else None,
            "latency": status.get("latency") if status.get("latency") in LATENCY else "SAFE"}


def studio_takes_fm1s(address, port=80, timeout=2.0):
    """the Studio at address takes the Pocket's FM-1s each on its own stream (its /api/status says
    "pocket_fm1s"); False for an older one, or one that doesn't answer"""
    return studio_status(address, port, timeout)["fm1s"]


def snake_timing(step, speaker=False):
    """the Pocket's (block in samples, MIX_BACK's buffer in ms) for the Studio's LATENCY step: the Studio's block,
    but not below POCKET_BLOCK, and 1024 with a Bluetooth speaker (it needs the room); the buffer more than two of
    the Pocket's blocks, or PipeWire's RTP receiver runs short and starts over"""
    block, ms = LATENCY.get(step, LATENCY["SAFE"])
    block = 1024 if speaker else max(block, POCKET_BLOCK)
    return block, max(ms, -(-2 * block * 1000 // 48000) + 1)


class Hosted:
    """one PipeWire hosting a configuration, started again when the configuration changes or it stops"""

    def __init__(self, name):
        self.name, self.proc, self.text = name, None, None
        self.path = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / f"{name}.conf"

    def ensure(self, text):
        """text: the configuration to run, or None for none"""
        if text == self.text and (text is None or self.running()):
            return
        self.stop()
        if text:
            self.path.write_text(text, encoding="utf-8")
            self.proc = subprocess.Popen(["pipewire", "-c", str(self.path)],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.text = text

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc, self.text = None, None


class Sender(Hosted):
    """the Pocket's: SINK, to the Studio at address while it's linked"""

    def __init__(self):
        super().__init__("fm1-studio-link")
        self.address, self.fm1s = None, ()

    def to(self, address, fm1s=()):
        """fm1s: the FM-1 letters to send on their own (a Studio that takes them), the rest on SINK"""
        self.address, self.fm1s = address, tuple(fm1s)
        self.ensure(sender_config(address, fm1s=self.fm1s) if address else None)


class MixBack(Hosted):
    """the Pocket's: MIX_BACK, the Studio's mix as it arrives on its port"""

    def __init__(self):
        super().__init__("fm1-studio-mix")

    def listen(self, port=None, latency_ms=40):
        """port: the Studio's return port, or None for none"""
        self.ensure(receiver_config(port, latency_ms, MIX_BACK, "Studio mix (link)") if port else None)


class Receiver(Hosted):
    """the Studio's: SOURCE, from whatever Pocket sends to PORT"""

    def __init__(self):
        super().__init__("fm1-pocket-link")

    def listen(self, on=True, latency_ms=40):
        self.ensure(receiver_config(latency_ms=latency_ms) if on else None)


if __name__ == "__main__":             # by hand: python3 netaudio.py send <address> | receive
    import sys
    import time
    if len(sys.argv) > 1 and sys.argv[1] in ("send", "receive"):
        hosted = Sender() if sys.argv[1] == "send" else Receiver()
        hosted.to(sys.argv[2]) if sys.argv[1] == "send" else hosted.listen()
        print(f"{hosted.name}: running (Ctrl-C to stop)")
        try:
            while hosted.running():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        hosted.stop()
    else:
        print(__doc__)
