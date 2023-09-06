from ...Node import Node
from ....Constants import *
from ..Colors import *

import array
import bpy

TILE_S_I4 =       8
TILE_S_I8 =       8
TILE_S_IA4 =      8
TILE_S_IA8 =      4
TILE_S_RGB565 =   4
TILE_S_RGB5A3 =   4
TILE_S_RGBA8 =    4
TILE_S_CMPR =     8

TILE_S_C4 =       8
TILE_S_C8 =       8
TILE_S_C14X2 =    4

TILE_T_I4 =       8
TILE_T_I8 =       4
TILE_T_IA4 =      4
TILE_T_IA8 =      4
TILE_T_RGB565 =   4
TILE_T_RGB5A3 =   4
TILE_T_RGBA8 =    4
TILE_T_CMPR =     8

TILE_T_C4 =       8
TILE_T_C8 =       4
TILE_T_C14X2 =    4

BITSPPX_I4 =      4
BITSPPX_I8 =      8
BITSPPX_IA4 =     8
BITSPPX_IA8 =     16
BITSPPX_RGB565 =  16
BITSPPX_RGB5A3 =  16
BITSPPX_RGBA8 =   32
BITSPPX_CMPR =    4

BITSPPX_C4 =      4
BITSPPX_C8 =      8
BITSPPX_C14X2 =   16

CCC = 4 #color component count

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

    # palette is [Color]
    def pixels(self, parser, palette):

        pixels = []

        bits_per_pixel, is_indexed, blockWidth, blockHeight, type = format_dict[self.format]
        blocks_x = (self.width  // blockWidth) + (1 if ((self.width  % blockWidth) > 0) else 0)
        blocks_y = (self.height // blockHeight) + (1 if ((self.height % blockHeight) > 0) else 0)
        bytes_per_pixel = bits_per_pixel >> 3
        pixels_in_image = (blocks_x * blockWidth * blocks_y * blockHeight)

        if is_indexed:
            if bits_per_pixel == 4:
                for i in range(pixels_in_image // 2):
                    value = parser.read('uchar', self.data_address, i)
                    index1 = (value & 0xF0) >> 4
                    index2 = value & 0xF
                    color1 = palette[index1]
                    color2 = palette[index2]
                    pixels.append(color1)
                    pixels.append(color2)
            else:
                for i in range(pixels_in_image):
                    index = parser.read(type, self.data_address, i * bytes_per_pixel)
                    color = palette[index]
                    pixels.append(color)
        else:
            if self.format == gx.GX_TF_RGBA8:
                # rg and ba values of rgba32 are separated within blocks so we'll restructure first
                pixels_per_block = 16 # 4 pixelsperrow x 4 pixelspercolumn
                block_count = pixels_in_image // pixels_per_block

                for i in range(block_count):
                    block_start = i * pixels_per_block * bytes_per_pixel
                    for j in range(16):
                        alpha = parser.read('uchar', self.data_address, block_start + (j * 2))
                        red = parser.read('uchar', self.data_address, block_start + (j * 2) + 1)
                        green = parser.read('uchar', self.data_address, block_start + (j * 2) + 32)
                        blue = parser.read('uchar', self.data_address, block_start + (j * 2) + 32 + 1)
                        color = Color(red, green, blue, alpha)
                        color.normalize()

                        pixels.append(color)

            elif self.format == gx.GX_TF_CMPR:
                sub_blocks_per_block = 4
                sub_block_size = 8
                pixels_per_sub_block = 16
                block_size = sub_blocks_per_block * sub_block_size
                pixels_per_block = sub_blocks_per_block * pixels_per_sub_block
                block_count = pixels_in_image // pixels_per_block
                blocks = []

                # decode one block per loop
                for i in range(block_count):
                    sub_blocks = []
                    block_offset = i * block_size
                    for j in range(4):
                        sub_block = []
                        sub_block_offset = j * sub_block_size
                        colour1 = parser.read('RGB565Color', self.data_address, block_offset + sub_block_offset)
                        colour1_value = parser.read('ushort', self.data_address, block_offset + sub_block_offset)
                        colour2 = parser.read('RGB565Color', self.data_address, block_offset + sub_block_offset + 2)
                        colour2_value = parser.read('ushort', self.data_address, block_offset + sub_block_offset + 2)
                        indices = parser.read('uint', self.data_address, block_offset + sub_block_offset + 4)
                        palette = [colour1, colour2]

                        if colour1_value > colour2_value:
                            r1 = (2 * colour1.red + colour2.red) // 3
                            g1 = (2 * colour1.green + colour2.green) // 3
                            b1 = (2 * colour1.blue + colour2.blue) // 3
                            r2 = (2 * colour2.red + colour1.red) // 3
                            g2 = (2 * colour2.green + colour1.green) // 3
                            b2 = (2 * colour2.blue + colour1.blue) // 3

                            colour3 = Color(r1, g1, b1, 0xFF)
                            colour4 = Color(r2, g2, b2, 0xFF)
                            
                        else:
                            r1 = (colour1.red + colour2.red) // 2
                            g1 = (colour1.green + colour2.green) // 2
                            b1 = (colour1.blue + colour2.blue) // 2

                            colour3 = Color(r1, g1, b1, 0xFF)
                            colour4 = Color(0, 0, 0, 0)

                        palette.append(colour3)
                        palette.append(colour4)

                        colour1.normalize()
                        colour2.normalize()
                        colour3.normalize()
                        colour4.normalize()

                        for k in range(16):
                            nibble_position = (15 - k) * 2
                            index = (indices >> nibble_position) & 0x3

                            sub_block.append(palette[index])
                        sub_blocks.append(sub_block)

                    block = []
                    for subBlockRow in range(2):
                        subBlock1 = sub_blocks[subBlockRow * 2]
                        subBlock2 = sub_blocks[subBlockRow * 2 + 1]
                        for row in range(4):
                            for column in range(4):
                                pixelIndex = row * 4 + column
                                block.append(subBlock1[pixelIndex])

                            for column in range(4):
                                pixelIndex = row * 4 + column
                                block.append(subBlock2[pixelIndex])

                    blocks.append(block)

                for block in blocks:
                    for pixel in block:
                        pixels.append(pixel)

            else:
                if bits_per_pixel == 4:
                    for i in range(pixels_in_image // 2):
                        value = parser.read('uchar', self.data_address, i)
                        intensity1 = (value & 0xF0) >> 4
                        intensity2 = value & 0xF
                        color1 = Color()
                        color1.red = intensity1 << 4
                        color1.green = intensity1 << 4
                        color1.blue = intensity1 << 4
                        color1.alpha = 0xFF
                        color2 = Color()
                        color2.red = intensity2 << 4
                        color2.green = intensity2 << 4
                        color2.blue = intensity2 << 4
                        color2.alpha = 0xFF
                        color1.normalize()
                        color2.normalize()
                        pixels.append(color1)
                        pixels.append(color2)
                else:
                    for i in range(pixels_in_image):
                        color = parser.read(type, self.data_address, i * bytes_per_pixel)
                        color.normalize()
                        pixels.append(color)

        return pixels

    def croppedImage(self, parser, width, height, palette):
        pixels = self.pixels(parser, palette)

        bits_per_pixel, is_indexed, blockWidth, blockHeight, type = format_dict[self.format]

        pixelsPerRow = self.width
        pixelsPerCol = self.height
        while pixelsPerRow % blockWidth != 0:
            pixelsPerRow += 1

        while pixelsPerCol % blockHeight != 0:
            pixelsPerCol += 1

        markedPixels = []

        rowsPerBlock = blockHeight
        columnsPerBlock = blockWidth

        pixelsPerBlock = rowsPerBlock * columnsPerBlock
        blocksPerRow = pixelsPerRow // columnsPerBlock

        for index in range(pixelsPerRow * pixelsPerCol):
            indexOfBlock = index // pixelsPerBlock
            indexInBlock = index % pixelsPerBlock
            rowInBlock = indexInBlock // columnsPerBlock
            columnInBlock = indexInBlock % columnsPerBlock
            rowOfBlock = indexOfBlock // blocksPerRow
            columnOfBlock = indexOfBlock % blocksPerRow

            color = pixels[index]
            x = (columnOfBlock * columnsPerBlock) + columnInBlock
            y = (rowOfBlock * rowsPerBlock) + rowInBlock

            markedPixels.append((x, y, color))

        orderedPixels = list(filter(lambda pix: pix[0] < width and pix[1] < height, markedPixels))
        orderedPixels = sorted(orderedPixels, key=lambda pix: (height - pix[1]) * width + pix[0])

        pixels = []
        for pixel in orderedPixels:
            pixels.append(pixel[2])

        return pixels

    def loadDataWithPalette(self, parser, palette):
        width = self.width
        height = self.height

        # TODO: use dolphin's naming convention for image file name
        name = 'image_' + name_dict.get(self.format) + "_" + str(self.id)
        image = bpy.data.images.new(name, width, height, alpha=True)

        normalized_pixels = []

        pixels = self.croppedImage(parser, width, height, palette)
        for pixel in pixels:
            normalized_pixels.append(pixel.red)
            normalized_pixels.append(pixel.green)
            normalized_pixels.append(pixel.blue)
            normalized_pixels.append(pixel.alpha)

        image.pixels = normalized_pixels

        # image.filepath_raw = "./" + name + ".png"
        # image.file_format = 'PNG'
        # image.save()

        return image

format_dict = {
    #                 bits per pixel| indexed | tile width   | tile height  | type
    gx.GX_TF_I4:     (BITSPPX_I4    ,    False, TILE_S_I4    , TILE_T_I4    , None    ),
    gx.GX_TF_I8:     (BITSPPX_I8    ,    False, TILE_S_I8    , TILE_T_I8    , 'I8Color'    ),
    gx.GX_TF_IA4:    (BITSPPX_IA4   ,    False, TILE_S_IA4   , TILE_T_IA4   , 'IA4Color'   ),
    gx.GX_TF_IA8:    (BITSPPX_IA8   ,    False, TILE_S_IA8   , TILE_T_IA8   , 'IA8Color'   ),
    gx.GX_TF_RGB565: (BITSPPX_RGB565,    False, TILE_S_RGB565, TILE_T_RGB565, 'RGB565Color'),
    gx.GX_TF_RGB5A3: (BITSPPX_RGB5A3,    False, TILE_S_RGB5A3, TILE_T_RGB5A3, 'RGB5A3Color'),
    gx.GX_TF_RGBA8:  (BITSPPX_RGBA8 ,    False, TILE_S_RGBA8 , TILE_T_RGBA8 , 'RGBA8Color' ),
    gx.GX_TF_CMPR:   (BITSPPX_CMPR  ,    False, TILE_S_CMPR  , TILE_T_CMPR  , None  ),
    #GXCITexFmt
    gx.GX_TF_C4:     (BITSPPX_C4    ,     True, TILE_S_C4    , TILE_T_C4    , None    ),
    gx.GX_TF_C8:     (BITSPPX_C8    ,     True, TILE_S_C8    , TILE_T_C8    , 'uchar'    ),
    gx.GX_TF_C14X2:  (BITSPPX_C14X2 ,     True, TILE_S_C14X2 , TILE_T_C14X2 , 'ushort' ),
}

name_dict = {
    gx.GX_TF_I4 : 'I4',
    gx.GX_TF_I8 : 'I8',
    gx.GX_TF_IA4 : 'IA4',
    gx.GX_TF_IA8 : 'IA8',
    gx.GX_TF_RGB565 : 'RGB565',
    gx.GX_TF_RGB5A3 : 'RGB5A3',
    gx.GX_TF_RGBA8 : 'RGBA8',
    gx.GX_TF_CMPR : 'CMPR',
    gx.GX_TF_C4 : 'C4',
    gx.GX_TF_C8 : 'C8',
    gx.GX_TF_C14X2 : 'C14X2',
}


