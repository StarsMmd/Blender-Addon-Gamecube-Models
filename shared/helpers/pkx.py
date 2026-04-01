"""PKX container helper — read and write PKX file metadata and DAT payloads.

PKX files wrap a DAT model binary with a header and trailer:
  - Colosseum: 0x40 byte header, trailer after DAT (shiny params at end of file)
  - XD: 0xE60+ byte header (shiny params at 0x73), trailer after DAT

Structure: [header][DAT payload (dat_file_size bytes)][trailer]

The DAT's own file_size field (first uint of its 32-byte header) determines
where the DAT ends and the trailer begins. The PKX header at offset 0x00
also stores this value.

The constructor takes the raw bytes of the whole PKX file. Properties provide
read/write access to the DAT payload and shiny parameters.
"""
from .binary import read, write_into
from .shiny_params import ShinyParams


def _to_brightness(byte_val):
    """Map a brightness byte [0, 255] to a float [-1.0, 1.0].

    Byte 127 maps to 0.0 (no change). Values 0-126 scale linearly to
    [-1.0, 0.0) and values 128-255 scale linearly to (0.0, 1.0].
    """
    if byte_val <= 127:
        return (byte_val / 127.0) - 1.0
    else:
        return (byte_val - 127.0) / 128.0


def _from_brightness(value):
    """Map a brightness float [-1.0, 1.0] to a byte [0, 255]."""
    if value <= 0.0:
        return max(0, round((value + 1.0) * 127.0))
    else:
        return min(255, round(value * 128.0) + 127)


def _is_noop_shiny(route_r, route_g, route_b, route_a, raw_brightness):
    """Check if shiny parameters are a no-op (identity routing + neutral brightness)."""
    identity_routing = (route_r == 0 and route_g == 1 and route_b == 2 and route_a == 3)
    neutral_brightness = all(abs(b - 128) <= 1 for b in raw_brightness)
    return identity_routing and neutral_brightness


class PKXContainer:
    """Mutable representation of a PKX file.

    Takes the complete raw bytes of a PKX file. The header, DAT payload,
    and trailer are identified automatically. Properties provide read/write
    access to the DAT payload and shiny parameters while preserving all
    other bytes.

    Structure: [header][DAT payload][trailer]
      - header_size is 0x40 (Colosseum) or 0xE60+ (XD)
      - DAT payload size is determined by the DAT's file_size field
      - trailer is everything after the DAT payload
    """

    def __init__(self, raw_bytes):
        self._data = bytearray(raw_bytes)

        if len(self._data) < 0x44:
            self._is_xd = False
            self._header_size = min(0x40, len(self._data))
            self._dat_end = self._header_size
            return

        # Detect format: XD has different values at 0x00 and 0x40
        val_0 = read('uint', self._data, 0)
        val_40 = read('uint', self._data, 0x40)
        self._is_xd = val_0 != val_40

        # Compute header size
        if self._is_xd:
            self._header_size = 0xE60
            gpt1_size = read('uint', self._data, 8)
            if gpt1_size > 0:
                self._header_size += gpt1_size + ((0x20 - (gpt1_size % 0x20)) % 0x20)
        else:
            self._header_size = 0x40

        # DAT payload ends at header_size + dat_file_size
        dat_file_size = read('uint', self._data, self._header_size)
        self._dat_end = self._header_size + dat_file_size

    @classmethod
    def from_file(cls, filepath):
        """Create a PKXContainer from a file path."""
        with open(filepath, 'rb') as f:
            return cls(f.read())

    # -----------------------------------------------------------------------
    # Read-only properties
    # -----------------------------------------------------------------------

    @property
    def is_xd(self):
        """True for XD format, False for Colosseum."""
        return self._is_xd

    @property
    def header_size(self):
        """Size of the PKX header in bytes."""
        return self._header_size

    # -----------------------------------------------------------------------
    # DAT payload
    # -----------------------------------------------------------------------

    @property
    def dat_bytes(self):
        """The DAT model payload."""
        return bytes(self._data[self._header_size:self._dat_end])

    @dat_bytes.setter
    def dat_bytes(self, new_dat_bytes):
        """Replace the DAT payload, preserving header and trailer.

        Updates the file size field at offset 0x00 in the PKX header and
        recomputes the DAT end boundary so the trailer remains intact.
        """
        trailer = self._data[self._dat_end:]
        new_dat_file_size = read('uint', new_dat_bytes, 0)

        # Rebuild: header + new DAT + original trailer
        self._data[self._header_size:] = new_dat_bytes + trailer
        self._dat_end = self._header_size + new_dat_file_size

        # Update file size field in PKX header
        write_into('uint', new_dat_file_size, self._data, 0)

    # -----------------------------------------------------------------------
    # Shiny parameters
    # -----------------------------------------------------------------------

    @property
    def _shiny_base(self):
        """Compute the base offset for shiny parameters."""
        if self._is_xd:
            return 0x73
        else:
            return len(self._data) - 0x11

    @property
    def shiny_params(self):
        """Read shiny filter parameters. Returns ShinyParams or None."""
        base = self._shiny_base
        if base < 0 or base + 17 > len(self._data):
            return None

        route_r = read('uchar', self._data, base + 0)
        route_g = read('uchar', self._data, base + 4)
        route_b = read('uchar', self._data, base + 8)
        route_a = read('uchar', self._data, base + 12)

        raw_brightness = [
            read('uchar', self._data, base + 13),
            read('uchar', self._data, base + 14),
            read('uchar', self._data, base + 15),
            read('uchar', self._data, base + 16),
        ]

        # Colosseum stores brightness as ABGR
        if not self._is_xd:
            raw_brightness = list(reversed(raw_brightness))

        if _is_noop_shiny(route_r, route_g, route_b, route_a, raw_brightness):
            return None

        return ShinyParams(
            route_r=route_r,
            route_g=route_g,
            route_b=route_b,
            route_a=route_a,
            brightness_r=_to_brightness(raw_brightness[0]),
            brightness_g=_to_brightness(raw_brightness[1]),
            brightness_b=_to_brightness(raw_brightness[2]),
            brightness_a=_to_brightness(raw_brightness[3]),
        )

    @shiny_params.setter
    def shiny_params(self, params):
        """Write shiny filter parameters."""
        base = self._shiny_base
        if base < 0 or base + 17 > len(self._data):
            return

        # Channel routing (with 3-byte gaps)
        write_into('uchar', params.route_r, self._data, base + 0)
        write_into('uchar', params.route_g, self._data, base + 4)
        write_into('uchar', params.route_b, self._data, base + 8)
        write_into('uchar', params.route_a, self._data, base + 12)

        # Brightness
        brightness_rgba = [
            _from_brightness(params.brightness_r),
            _from_brightness(params.brightness_g),
            _from_brightness(params.brightness_b),
            _from_brightness(params.brightness_a),
        ]

        # Colosseum stores brightness as ABGR
        if not self._is_xd:
            brightness_rgba = list(reversed(brightness_rgba))

        write_into('uchar', brightness_rgba[0], self._data, base + 13)
        write_into('uchar', brightness_rgba[1], self._data, base + 14)
        write_into('uchar', brightness_rgba[2], self._data, base + 15)
        write_into('uchar', brightness_rgba[3], self._data, base + 16)

    # -----------------------------------------------------------------------
    # Serialization
    # -----------------------------------------------------------------------

    def to_bytes(self):
        """Return the complete PKX file as bytes."""
        return bytes(self._data)
