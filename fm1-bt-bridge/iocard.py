"""The I/O card: a Raspberry Pi Pico on USB that is a sound card (a line out with its own level knob and meter)
and a USB MIDI interface for its 5-pin DIN jacks (github.com/xoxoaudiolabs/Companion-Expansion-Cards, io-card).

The box knows it by its USB name, "Companion I/O" (deliberately without "FM-1", which would make it an FM-1 here):
- its sound card gets a copy of the master mix, or the mix itself when there's no speaker or jack (bridge.py);
- its first MIDI port, the DIN jacks, is "DIN" in the MIDI matrix (blemidi.UsbControllers). Its second port,
  "Card" (the knob's position, as controller 7), isn't opened yet.
"""
import re

NAME = "companion i/o"
DIN = "DIN"                             # the DIN jacks' name in the MIDI matrix
LABEL = "I/O CARD"                      # the line out's name on the screen


def is_card(text):
    """a PipeWire node's or ALSA port's name is the card's ("Companion I/O", or "Companion_I_O" in node names)"""
    low = str(text).lower()
    return NAME in low or "companion_i_o" in low


def din_port(name):
    """mido's port name is the card's DIN port: its first (ALSA port 0), "Companion I/O:Companion I/O MIDI 1 28:0".
    The second port (":1") is the card's own."""
    m = re.search(r"\s\d+:(\d+)$", name)
    return is_card(name) and (m is None or m.group(1) == "0")


def sink_node(objects):
    """the card's line out among pw-dump's objects, as {"id", "name", "label"}, or None"""
    for o in objects:
        if o.get("type") != "PipeWire:Interface:Node":
            continue
        props = (o.get("info") or {}).get("props") or {}
        name = str(props.get("node.name", ""))
        text = " ".join(str(props.get(k, "")) for k in ("node.name", "node.description", "alsa.card_name"))
        if props.get("media.class") == "Audio/Sink" and name.startswith("alsa_output.") and is_card(text):
            return {"id": o.get("id"), "name": name, "label": LABEL}
    return None
