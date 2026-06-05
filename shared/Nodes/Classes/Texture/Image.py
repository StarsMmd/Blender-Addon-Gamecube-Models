from ...Node import Node
from ....Constants import *
from ....gx_texture import (
    CCC, FORMAT_INFO, decode_texture, get_palette_color,
    # Re-export constants and decoders for backward compatibility
    TILE_S_I4, TILE_S_I8, TILE_S_IA4, TILE_S_IA8, TILE_S_RGB565,
    TILE_S_RGB5A3, TILE_S_RGBA8, TILE_S_CMPR, TILE_S_C4, TILE_S_C8, TILE_S_C14X2,
    TILE_T_I4, TILE_T_I8, TILE_T_IA4, TILE_T_IA8, TILE_T_RGB565,
    TILE_T_RGB5A3, TILE_T_RGBA8, TILE_T_CMPR, TILE_T_C4, TILE_T_C8, TILE_T_C14X2,
    BITSPPX_I4, BITSPPX_I8, BITSPPX_IA4, BITSPPX_IA8, BITSPPX_RGB565,
    BITSPPX_RGB5A3, BITSPPX_RGBA8, BITSPPX_CMPR, BITSPPX_C4, BITSPPX_C8, BITSPPX_C14X2,
    decode_I4_block as convert_I4_block,
    decode_I8_block as convert_I8_block,
    decode_IA4_block as convert_IA4_block,
    decode_IA8_block as convert_IA8_block,
    decode_RGB565_block as convert_RGB565_block,
    decode_RGB5A3_block as convert_RGB5A3_block,
    decode_RGBA8_block as convert_RGBA8_block,
    decode_CMPR_block as convert_CMPR_block,
    decode_C4_block as convert_C4_block,
    decode_C8_block as convert_C8_block,
    decode_C14X2_block as convert_C14X2_block,
)

import array

# Backward-compatible alias
format_dict = FORMAT_INFO

# Image
class Image(Node):
    class_name = "Image"
    fields = [
        ('data_address', 'uint'),
        ('width', 'ushort'),
        ('height', 'ushort'),
        ('format', 'uint'),
        ('mipmap', 'uint'),
        ('minLOD', 'float'),
        ('maxLOD', 'float'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        # Use the address of the image data as the id
        self.id = self.data_address
        parser.logger.debug("Image 0x%X: %dx%d, format=%d, data_address=0x%X",
                            self.address, self.width, self.height, self.format, self.data_address)

        # Store raw texture data for round-trip writing
        if self.data_address is not None and self.format in format_dict:
            bits_per_pixel, tile_S, tile_T, _ = format_dict[self.format]
            blocks_x = (self.width  // tile_S) + (1 if ((self.width  % tile_S) > 0) else 0)
            blocks_y = (self.height // tile_T) + (1 if ((self.height % tile_T) > 0) else 0)
            data_size = (blocks_x * tile_S * blocks_y * tile_T * bits_per_pixel) >> 3
            self.raw_image_data = parser.read_chunk(data_size, self.data_address, parser._startOffset(True))
        else:
            self.raw_image_data = b''

    def writePrimitivePointers(self, builder):
        """Write shared image pixel data (Phase 1)."""
        if not hasattr(self, '_raw_pointer_fields'):
            self._raw_pointer_fields = set()
        if self.raw_image_data:
            builder.seek(0, 'end')
            builder.align_buffer()
            self.data_address = builder._currentRelativeAddress()
            for byte in self.raw_image_data:
                builder.write(byte, 'uchar')
            self._raw_pointer_fields.add('data_address')
        else:
            self.data_address = 0

    def decodeFromRawData(self, palette):
        """Decode raw_image_data into RGBA pixels without needing the parser.

        Uses self.raw_image_data stored during loadFromBinary().
        Returns cropped, vertically-flipped RGBA byte array, or None if no data.
        """
        if not self.raw_image_data or self.format not in format_dict:
            return None

        width = self.width
        height = self.height

        bits_per_pixel, tile_S, tile_T, func = format_dict[self.format]
        blocks_x = (width  // tile_S) + (1 if ((width  % tile_S) > 0) else 0)
        blocks_y = (height // tile_T) + (1 if ((height % tile_T) > 0) else 0)

        out_data = array.array('B', [0] * (blocks_x * tile_S * blocks_y * tile_T * CCC))
        buffer = memoryview(out_data)

        image_data = memoryview(bytearray(self.raw_image_data))

        for i in range(blocks_y):
            for j in range(blocks_x):
                func(buffer, image_data, blocks_x, palette)
                image_data = image_data[(tile_S * tile_T * bits_per_pixel) >> 3:]
                buffer = buffer[CCC * tile_S:]
            buffer = buffer[CCC * blocks_x * tile_S * (tile_T - 1):]

        # Crop and flip vertically (GX top-to-bottom → bottom-to-top)
        decoded_stride = blocks_x * tile_S * CCC
        actual_stride = width * CCC
        cropped = array.array('B', [0] * (width * height * CCC))
        for row in range(height):
            src_start = row * decoded_stride
            dst_start = (height - 1 - row) * actual_stride
            cropped[dst_start:dst_start + actual_stride] = out_data[src_start:src_start + actual_stride]

        return cropped

    def loadDataWithPalette(self, parser, palette):
        width = self.width
        height = self.height

        bits_per_pixel, tile_S, tile_T, func = format_dict[self.format]
        blocks_x = (width  // tile_S) + (1 if ((width  % tile_S) > 0) else 0)
        blocks_y = (height // tile_T) + (1 if ((height % tile_T) > 0) else 0)

        out_data = array.array('B', [0] * (blocks_x * tile_S * blocks_y * tile_T * CCC))
        buffer = memoryview(out_data)

        in_data_size = (blocks_x * tile_S * blocks_y * tile_T * bits_per_pixel) >> 3
        in_data = parser.read_chunk(in_data_size, self.data_address, parser._startOffset(True))
        image_data = memoryview(in_data)

        for i in range(blocks_y):
            for j in range(blocks_x):
                func(buffer, image_data, blocks_x, palette)
                image_data = image_data[(tile_S * tile_T * bits_per_pixel) >> 3:]
                buffer = buffer[CCC * tile_S:]
            buffer = buffer[CCC * blocks_x * tile_S * (tile_T - 1):]

        # Crop tile-padded buffer to actual image dimensions and flip vertically.
        # GX textures decode top-to-bottom but Blender's image.pixels expects
        # bottom-to-top (row 0 = bottom). Flip rows so the UV V-flip (1 - V) in
        # PObject and the V-translation formula in MaterialObject work correctly.
        # (The original croppedImage() did this via sorting by (height - y).)
        decoded_stride = blocks_x * tile_S * CCC
        actual_stride = width * CCC
        cropped = array.array('B', [0] * (width * height * CCC))
        for row in range(height):
            src_start = row * decoded_stride
            dst_start = (height - 1 - row) * actual_stride
            cropped[dst_start:dst_start + actual_stride] = out_data[src_start:src_start + actual_stride]

        return cropped

    # get_palette_color, decoder functions, and format_dict are now imported
    # from shared.gx_texture and re-exported above for backward compatibility.

name_dict = {
    gx.GX_TF_I4 : 'GX_TF_I4',
    gx.GX_TF_I8 : 'GX_TF_I8',
    gx.GX_TF_IA4 : 'GX_TF_IA4',
    gx.GX_TF_IA8 : 'GX_TF_IA8',
    gx.GX_TF_RGB565 : 'GX_TF_RGB565',
    gx.GX_TF_RGB5A3 : 'GX_TF_RGB5A3',
    gx.GX_TF_RGBA8 : 'GX_TF_RGBA8',
    gx.GX_TF_CMPR : 'GX_TF_CMPR',
    gx.GX_TF_C4 : 'GX_TF_C4',
    gx.GX_TF_C8 : 'GX_TF_C8',
    gx.GX_TF_C14X2 : 'GX_TF_C14X2',
}

