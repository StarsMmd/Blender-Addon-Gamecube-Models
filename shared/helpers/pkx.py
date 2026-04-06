"""PKX container helper — read and write PKX file metadata and DAT payloads.

PKX files wrap a DAT model binary with a header and trailer:
  - Colosseum: 0x40 byte header, DAT, GPT1, animation metadata, shiny (20 bytes at end)
  - XD: dynamic header (preamble + anim entries + padding), optional GPT1, DAT, trailer

Structure (XD): [header][DAT payload][trailer]
Structure (Colo): [0x40 header][DAT padded][GPT1 padded][anim entries][shiny 20 bytes]

The DAT's own file_size field (first uint of its 32-byte header) determines
where the DAT ends and the trailer begins. The PKX header at offset 0x00
also stores this value.

The constructor takes the raw bytes of the whole PKX file. Properties provide
read/write access to the DAT payload and shiny parameters.
"""
from .binary import read, write_into
from .shiny_params import ShinyParams
from .pkx_header import PKXHeader, _align32, _COLO_SHINY_SIZE


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

    Structure (XD): [header][DAT payload][trailer]
      - header_size is dynamic: align32(0x84 + anim_count * 0xD0) + align32(gpt1_length)
      - DAT payload size is determined by the DAT's file_size field
      - trailer is everything after the DAT payload

    Structure (Colosseum): [0x40 header][DAT padded][GPT1 padded][anim entries][shiny]
      - header is fixed 0x40 bytes
      - DAT and GPT1 are each padded to 0x20 boundary
      - animation metadata follows, then 20-byte shiny trailer
    """

    def __init__(self, raw_bytes):
        self._data = bytearray(raw_bytes)
        self._header_cache = None

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
            anim_count = read('uint', self._data, 0x10)
            base = 0x84 + anim_count * 0xD0
            self._header_size = _align32(base)
            gpt1_size = read('uint', self._data, 8)
            if gpt1_size > 0:
                self._header_size += _align32(gpt1_size)
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

    @classmethod
    def build_xd(cls, dat_bytes, header, gpt1_data=b'', trailer=b''):
        """Build a complete XD PKX file from components.

        Args:
            dat_bytes: The DAT model binary.
            header: A PKXHeader instance with XD data.
            gpt1_data: Optional GPT1 particle data bytes.
            trailer: Optional trailer bytes after the DAT.

        Returns:
            A new PKXContainer instance.
        """
        # Update header fields to match actual data
        header.dat_file_size = read('uint', dat_bytes, 0) if len(dat_bytes) >= 4 else 0
        header.gpt1_length = len(gpt1_data) if gpt1_data else 0

        header_bytes = header.to_bytes()
        parts = [header_bytes]
        if gpt1_data:
            # GPT1 goes between header and DAT, but it's already accounted for
            # in header_byte_size via gpt1_length. Actually for XD, GPT1 is
            # embedded in the header region. The header.to_bytes() output is
            # header_byte_size which includes the GPT1 space. We need to
            # place GPT1 data at the right offset.
            # header_byte_size = align32(0x84 + count*0xD0) + align32(gpt1_length)
            # GPT1 sits at align32(0x84 + count*0xD0)
            base = _align32(0x84 + header.anim_section_count * 0xD0)
            # Extend header_bytes to include GPT1
            extended = bytearray(header_bytes)
            extended[base:base + len(gpt1_data)] = gpt1_data
            parts = [bytes(extended)]

        parts.append(dat_bytes)
        if trailer:
            parts.append(trailer)

        return cls(b''.join(parts))

    @classmethod
    def build_colosseum(cls, dat_bytes, header, gpt1_data=b''):
        """Build a complete Colosseum PKX file from components.

        Args:
            dat_bytes: The DAT model binary.
            header: A PKXHeader instance with Colosseum data.
            gpt1_data: Optional GPT1 particle data bytes.

        Returns:
            A new PKXContainer instance.
        """
        dat_size = read('uint', dat_bytes, 0) if len(dat_bytes) >= 4 else 0
        header.dat_file_size = dat_size
        header.gpt1_length = len(gpt1_data) if gpt1_data else 0

        header_bytes, metadata_bytes = header.to_bytes()

        parts = [header_bytes]

        # DAT padded to 0x20
        dat_padded = bytearray(dat_bytes)
        pad = _align32(len(dat_padded)) - len(dat_padded)
        if pad > 0:
            dat_padded.extend(b'\x00' * pad)
        parts.append(bytes(dat_padded))

        # GPT1 padded to 0x20
        if gpt1_data:
            gpt1_padded = bytearray(gpt1_data)
            pad = _align32(len(gpt1_padded)) - len(gpt1_padded)
            if pad > 0:
                gpt1_padded.extend(b'\x00' * pad)
            parts.append(bytes(gpt1_padded))

        # Animation entries + shiny
        parts.append(metadata_bytes)

        return cls(b''.join(parts))

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
    # Parsed header
    # -----------------------------------------------------------------------

    @property
    def header(self):
        """Lazily parsed PKXHeader. Returns None for very small files."""
        if self._header_cache is not None:
            return self._header_cache

        if len(self._data) < 0x44:
            return None

        if self._is_xd:
            self._header_cache = PKXHeader.from_bytes(self._data, is_xd=True)
        else:
            # Compute metadata start for Colosseum
            dat_size = read('uint', self._data, 0x00)
            gpt1_size = read('uint', self._data, 0x04)
            meta_start = 0x40 + _align32(dat_size)
            if gpt1_size > 0:
                meta_start += _align32(gpt1_size)
            self._header_cache = PKXHeader.from_bytes(
                self._data, is_xd=False, meta_start=meta_start)

        return self._header_cache

    # -----------------------------------------------------------------------
    # GPT1 particle data
    # -----------------------------------------------------------------------

    @property
    def gpt1_data(self):
        """Extract GPT1 particle data bytes, or empty bytes if none."""
        if self._is_xd:
            gpt1_size = read('uint', self._data, 0x08)
            if gpt1_size <= 0:
                return b''
            anim_count = read('uint', self._data, 0x10)
            gpt1_start = _align32(0x84 + anim_count * 0xD0)
            return bytes(self._data[gpt1_start:gpt1_start + gpt1_size])
        else:
            gpt1_size = read('uint', self._data, 0x04)
            if gpt1_size <= 0:
                return b''
            dat_size = read('uint', self._data, 0x00)
            gpt1_start = 0x40 + _align32(dat_size)
            return bytes(self._data[gpt1_start:gpt1_start + gpt1_size])

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

        # Invalidate header cache
        self._header_cache = None

    # -----------------------------------------------------------------------
    # Shiny parameters (backward-compatible interface)
    # -----------------------------------------------------------------------

    @property
    def _shiny_base(self):
        """Compute the base offset for shiny parameters."""
        if self._is_xd:
            return 0x70
        else:
            return len(self._data) - _COLO_SHINY_SIZE

    @property
    def shiny_params(self):
        """Read shiny filter parameters. Returns ShinyParams or None."""
        base = self._shiny_base
        if base < 0 or base + _COLO_SHINY_SIZE > len(self._data):
            return None

        if self._is_xd:
            # XD: 4 × uint32 routing at 0x70, 4 × uint8 brightness at 0x80
            route_r = read('uint', self._data, base + 0)
            route_g = read('uint', self._data, base + 4)
            route_b = read('uint', self._data, base + 8)
            route_a = read('uint', self._data, base + 12)

            raw_brightness = [
                read('uchar', self._data, base + 16),
                read('uchar', self._data, base + 17),
                read('uchar', self._data, base + 18),
                read('uchar', self._data, base + 19),
            ]
        else:
            # Colosseum: 4 × uint32 routing, then uint32 ARGB
            route_r = read('uint', self._data, base + 0)
            route_g = read('uint', self._data, base + 4)
            route_b = read('uint', self._data, base + 8)
            route_a = read('uint', self._data, base + 12)

            argb = read('uint', self._data, base + 16)
            # ARGB → RGBA byte order
            raw_brightness = [
                (argb >> 16) & 0xFF,    # R
                (argb >> 8) & 0xFF,     # G
                argb & 0xFF,            # B
                (argb >> 24) & 0xFF,    # A
            ]

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
        if base < 0 or base + _COLO_SHINY_SIZE > len(self._data):
            return

        if self._is_xd:
            # XD: 4 × uint32 routing at 0x70, 4 × uint8 brightness at 0x80
            write_into('uint', params.route_r, self._data, base + 0)
            write_into('uint', params.route_g, self._data, base + 4)
            write_into('uint', params.route_b, self._data, base + 8)
            write_into('uint', params.route_a, self._data, base + 12)

            write_into('uchar', _from_brightness(params.brightness_r), self._data, base + 16)
            write_into('uchar', _from_brightness(params.brightness_g), self._data, base + 17)
            write_into('uchar', _from_brightness(params.brightness_b), self._data, base + 18)
            write_into('uchar', _from_brightness(params.brightness_a), self._data, base + 19)
        else:
            # Colosseum: 4 × uint32 routing, then uint32 ARGB
            write_into('uint', params.route_r, self._data, base + 0)
            write_into('uint', params.route_g, self._data, base + 4)
            write_into('uint', params.route_b, self._data, base + 8)
            write_into('uint', params.route_a, self._data, base + 12)

            brightness_rgba = [
                _from_brightness(params.brightness_r),
                _from_brightness(params.brightness_g),
                _from_brightness(params.brightness_b),
                _from_brightness(params.brightness_a),
            ]
            # RGBA → ARGB
            argb = (brightness_rgba[3] << 24) | (brightness_rgba[0] << 16) | \
                   (brightness_rgba[1] << 8) | brightness_rgba[2]
            write_into('uint', argb, self._data, base + 16)

        # Invalidate header cache
        self._header_cache = None

    # -----------------------------------------------------------------------
    # Serialization
    # -----------------------------------------------------------------------

    def to_bytes(self):
        """Return the complete PKX file as bytes."""
        return bytes(self._data)
