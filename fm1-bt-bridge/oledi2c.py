"""The Waveshare 1.3" OLED HAT switched to I2C (its resistor jumpers moved from SPI to I2C): the same SH1106 and
128x64 picture as over SPI (bridge.SH1106), on i2c-1 at 0x3C or 0x3D. The PiSugar 3 answers at 0x57 and 0x68, so
they don't clash. Found by itself: with the screen set to "oled", the box looks here first.

Not tried on a real HAT switched to I2C yet."""
import time

ADDRESSES = (0x3C, 0x3D)
BUS = 1


def find(bus=BUS):
    """the address an OLED answers at on the I2C bus, or None"""
    try:
        import smbus2
        with smbus2.SMBus(bus) as b:
            for addr in ADDRESSES:
                try:
                    b.read_byte(addr)
                    return addr
                except OSError:
                    pass
    except (ImportError, OSError):
        pass
    return None


def pack_pages(img):
    """A 128x64 1-bit image as the SH1106's 8 pages (bridge.pack_pages: bridge runs as the program, not a module)."""
    from PIL import Image
    data = img.transpose(Image.Transpose.ROTATE_270).tobytes()
    return [data[7 - p::8] for p in range(8)]


class SH1106I2C:
    """bridge.SH1106's calls (show, contrast, power) over I2C: a control byte 0x00 before commands, 0x40 before
    the picture's bytes"""

    def __init__(self, rotate=0, contrast=128, addr=None, bus=BUS):
        import smbus2
        self.bus, self.addr, self.rotate = smbus2.SMBus(bus), addr or find(bus) or ADDRESSES[0], rotate
        time.sleep(0.01)
        # the same set-up as bridge.SH1106's: 0xAD 0x8B switches on the panel's DC-DC supply
        self.cmd(0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0xAD, 0x8B, 0xA1, 0xC8, 0xDA, 0x12,
                 0x81, contrast, 0xD9, 0x22, 0xDB, 0x35, 0xA4, 0xA6)
        from PIL import Image
        self.show(Image.new("1", (128, 64)))
        self.cmd(0xAF)

    def cmd(self, *values):
        self.bus.write_i2c_block_data(self.addr, 0x00, list(values))

    def show(self, img):
        if self.rotate:
            img = img.rotate(self.rotate)
        for page, data in enumerate(pack_pages(img)):
            self.cmd(0xB0 + page, 0x02, 0x10)       # the panel's 128 columns start at RAM column 2
            for i in range(0, len(data), 32):      # (SMBus blocks: 32 bytes at most)
                self.bus.write_i2c_block_data(self.addr, 0x40, list(data[i:i + 32]))

    def contrast(self, value):
        self.cmd(0x81, value)

    def power(self, on):
        self.cmd(0xAF if on else 0xAE)

    def close(self):
        self.bus.close()
