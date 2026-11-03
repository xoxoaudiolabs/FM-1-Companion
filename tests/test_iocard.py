"""The I/O card (iocard.py): found by its USB name, never taken for an FM-1, its DIN jacks in the MIDI matrix, the
master mix on its line out. No card needed (needs Pillow and mido).

  python tests/test_iocard.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fm1-bt-bridge"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import blemidi  # noqa: E402
import bridge  # noqa: E402
import iocard  # noqa: E402
import sloop  # noqa: E402

# as Linux should show the card (from its USB descriptors; not yet seen on a real one)
CARD_PORTS = ["Companion I/O:Companion I/O MIDI 1 28:0", "Companion I/O:Companion I/O MIDI 2 28:1"]
FM1_PORTS = ["Felucca:Felucca MIDI 1 24:0"]
CARDS = """ 0 [Headphones     ]: bcm2835_headpho - bcm2835 Headphones
                      bcm2835 Headphones
 2 [Felucca        ]: USB-Audio - Felucca
                      Hagelton Instruments Felucca at usb-3f980000.usb-1.2, full speed
 3 [IO             ]: USB-Audio - Companion I/O
                      xoxoaudiolabs Companion I/O at usb-3f980000.usb-1.3, full speed
"""


def node(i, cls, name, **props):
    return {"type": "PipeWire:Interface:Node", "id": i,
            "info": {"props": dict({"media.class": cls, "node.name": name}, **props)}}


CARD_SINK = node(30, "Audio/Sink", "alsa_output.usb-xoxoaudiolabs_Companion_I_O_E6614C311B4C8A2F-00.analog-stereo",
                 **{"node.description": "Companion I/O Analog Stereo", "alsa.card_name": "Companion I/O"})
JACK = node(9, "Audio/Sink", "alsa_output.platform-bcm2835_audio.stereo-fallback",
            **{"alsa.card_name": "bcm2835 Headphones"})
SPEAKER = node(5, "Audio/Sink", "bluez_output.AA_BB_CC_DD_EE_FF.1", **{"node.description": "Speaker"})


class RgbCapture:
    """a colour screen's stand-in: keeps the last full-colour frame"""

    def __init__(self):
        self.image, self.theme = None, None

    def show_rgb(self, img):
        self.image = img.copy()


def test_found_by_name_never_an_fm1():
    assert iocard.is_card("Companion I/O") and iocard.is_card(CARD_SINK["info"]["props"]["node.name"])
    assert not iocard.is_card("Felucca") and not iocard.is_card("bcm2835 Headphones")
    assert iocard.din_port(CARD_PORTS[0]) and not iocard.din_port(CARD_PORTS[1])
    assert not iocard.din_port(FM1_PORTS[0])
    # the FM-1's matcher (the box's own source_match) passes the card by
    fm1 = blemidi.UsbMidi(bridge.DEFAULTS["source_match"], lambda m: None)
    assert fm1.pick(CARD_PORTS + FM1_PORTS) == FM1_PORTS[0] and fm1.pick(CARD_PORTS) is None
    assert sloop.fm1_cards(CARDS) == [2]                             # its sound card isn't an FM-1's
    assert sloop.find_ports(CARD_PORTS) is None


def test_din_in_the_matrix():
    fm1 = blemidi.UsbMidi(bridge.DEFAULTS["source_match"], lambda m: None)
    keys = blemidi.UsbControllers(fm1, lambda m: None)
    real = sloop.fm1_cards
    sloop.fm1_cards = lambda text=None: [6]
    try:
        names = FM1_PORTS + CARD_PORTS + ["SMK-37:SMK-37 MIDI 1 32:0"]
        assert keys.wanted(names) == {"DIN": CARD_PORTS[0], "SMK-37": "SMK-37:SMK-37 MIDI 1 32:0"}
        assert keys.wanted(CARD_PORTS[1:]) == {}                     # the Card port alone: not opened
    finally:
        sloop.fm1_cards = real
    sources, dests = blemidi.matrix(["DIN", "SMK-37"])               # the Studio: a row and a column of its own
    assert "U:DIN" in sources and "U:DIN" in dests
    assert blemidi.route_default("U:DIN>FM-1")["on"] and not blemidi.route_default("FM-1>U:DIN")["on"]


def test_line_out_found():
    objects = [JACK, SPEAKER, CARD_SINK]
    card = iocard.sink_node(objects)
    assert card == {"id": 30, "name": CARD_SINK["info"]["props"]["node.name"], "label": "I/O CARD"}
    assert iocard.sink_node([JACK, SPEAKER]) is None
    assert bridge.jack_node(objects)["id"] == 9                      # the jack is still the jack
    source, sink, _, others = bridge.pick_nodes(objects, bridge.DEFAULTS["source_match"])
    assert sink["id"] == 5 and source is None and others == []      # a line out, not a sound source


class FakeLoop:
    def __init__(self):
        self.calls = []

    def ensure(self, source, sink, name=None, pair=None):
        self.calls.append((source, sink, name))

    def running(self):
        return False

    def heal(self, objects, now=None):
        return False

    def follow(self, objects):
        return False

    def stop(self):
        pass


class FakeWatch:
    def __init__(self, objects):
        self.objects = objects

    def snapshot(self):
        return self.objects


def scan(objects, **state):
    app = bridge.App(RgbCapture(), dict(bridge.DEFAULTS, **state))
    app.save_settings = lambda: None
    app.loop, app.jack_loop, app.card_loop = FakeLoop(), FakeLoop(), FakeLoop()
    app.pw = FakeWatch(objects)
    real = bridge.run
    bridge.run = lambda *a, **k: (0, "")
    try:
        app.scan_devices()
    finally:
        bridge.run = real
    return app


def test_master_mix_on_the_line_out():
    card = CARD_SINK["info"]["props"]["node.name"]
    speaker, jack = SPEAKER["info"]["props"]["node.name"], JACK["info"]["props"]["node.name"]

    app = scan([SPEAKER, CARD_SINK])                                  # the Pocket with a speaker: a copy
    assert app.card["label"] == "I/O CARD" and "I/O card in" in (app.message or "")
    assert app.outputs() == (speaker, None)
    assert app.card_loop.calls[-1] == ("monitor:" + speaker, card, "fm1-card")

    app = scan([JACK, SPEAKER, CARD_SINK], output="both")            # the Studio: speaker, jack and card
    assert app.outputs() == (speaker, jack)
    assert app.card_loop.calls[-1] == ("monitor:" + speaker, card, "fm1-card")

    app = scan([CARD_SINK])                                           # nothing else: the card is the output
    assert app.outputs() == (card, None) and app.cue_target() == card
    assert not app.card_loop.calls[-1][0]                             # (no copy of itself)

    app = scan([SPEAKER])                                             # no card: no copy
    assert app.card is None and app.card_loop.calls[-1] == (None, None, "fm1-card")


if __name__ == "__main__":
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"all {len(tests)} passed")
