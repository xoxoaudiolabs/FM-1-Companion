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
      stream.props = {{ node.name = "{name}" node.description = "{description}" media.class = "Audio/Sink" }}"""


def sender_config(address, port=PORT, ssrc=None, fm1s=()):
    """fm1s: the FM-1 letters sent on their own (FM1_PORTS), each a sink and stream of its own beside SINK's"""
    modules = [sink_args(address, port, ssrc or stream_id(), SINK, "Studio (link)")]
    modules += [sink_args(address, FM1_PORTS[x], stream_id(x), fm1_sink(x), f"Studio (link) FM-1 {x}") for x in fm1s]
    return config(["libpipewire-module-rtp-sink"] * len(modules), modules, "fm1-studio-link")


def receiver_config(port=PORT, latency_ms=40, name=SOURCE, description="Pocket (link)"):
    """latency_ms: what the Studio holds back to ride out the network's jitter (PipeWire's default is 100). For a
    Pocket's FM-1 on its own: FM1_PORTS[letter], fm1_source(letter)"""
    return config("libpipewire-module-rtp-source", f"""      source.ip = "0.0.0.0"
      source.port = {port}
      sess.latency.msec = {latency_ms}
      sess.media = "audio"
      stream.props = {{ node.name = "{name}" node.description = "{description}" media.class = "Audio/Source" }}""",
                  "fm1-pocket-link" if name == SOURCE else name + "-link")


def studio_takes_fm1s(address, port=80, timeout=2.0):
    """the Studio at address takes the Pocket's FM-1s each on its own stream (its /api/status says
    "pocket_fm1s"); False for an older one, or one that doesn't answer"""
    try:
        with urllib.request.urlopen(f"http://{address}:{port}/api/status", timeout=timeout) as reply:
            return bool(json.loads(reply.read(1 << 20)).get("pocket_fm1s"))
    except (OSError, ValueError, AttributeError):
        return False


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
