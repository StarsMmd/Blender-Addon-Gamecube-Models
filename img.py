if "bpy" in locals():
    import importlib
    if "gx" in locals():
        importlib.reload(gx)


import logging

logging.basicConfig(filename='./out.txt',level=logging.DEBUG)

def error_output(string):
    print (string)
    logging.error(string)
    return {'CANCELLED'}

def notice_output(string):
    print(string)
    logging.info(string)
    print(string)

from . import gx
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

ccc = 4 #color component count



def read_image_from_scene(tobj, image_path, import_into_memory = True):
    imagedesc = tobj.imagedesc
    tlut = tobj.tlutdesc
    width = imagedesc.width
    height = imagedesc.height
    #from here on this is pretty much my previous C code ported to Python
    bits_per_px, tile_S, tile_T, func = format_dict[imagedesc.format]

    blocks_x = (imagedesc.width  // tile_S) + (1 if ((imagedesc.width  % tile_S) > 0) else 0)
    blocks_y = (imagedesc.height // tile_T) + (1 if ((imagedesc.height % tile_T) > 0) else 0)

    arr = array.array('B', [0] * (blocks_x * tile_S * blocks_y * tile_T * ccc))
    dst = memoryview(arr)

    src = imagedesc.image_ptr

    format = imagedesc.format
    for i in range(blocks_y):
        for j in range(blocks_x):
            func(dst, src, blocks_x, tlut)
            src = src[(tile_S * tile_T * bits_per_px) >> 3:]
            dst = dst[ccc * tile_S:]
        dst = dst[ccc * blocks_x * tile_S * (tile_T - 1):]

    image = None
    if import_into_memory:
        uses_alpha = True
        name = 'imported_image_' + name_dict[imagedesc.format]
        image = bpy.data.images.new(name, width, height, alpha=uses_alpha)
        temp_arr = [0] * width * height * ccc

        for i in range(height):
            in_row = i * (blocks_x * tile_S) * ccc
            out_row = (height - 1 - i) * width * ccc
            temp_arr[out_row : out_row + width * ccc] =  [x / 255 for x in arr[in_row : in_row + width * ccc]]

        image.pixels = temp_arr

    else:
        header = bytearray([0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, width & 0xFF, width >> 8, height & 0xFF, height >> 8, 0x20, 0x28])

        for l in range(width * height):
            arr[l * 4: (l + 1) * 4 - 1] = arr[l * 4: (l + 1) * 4 - 1][::-1]

        try:
            file = open(image_path, 'wb')
            file.write(header)
            file.write(arr)
            notice_output('Read Image ' + image_path)
            file.close()
        except:
            pass

        image = bpy.data.images.load(image_path)
    return image

def get_palette_color(palette, fmt):
    color = [0,0,0,0]
    if fmt == gx.GX_TL_IA8:
        color[0] = palette[1]
        color[1] = palette[1]
        color[2] = palette[1]
        color[3] = palette[0]
    elif fmt == gx.GX_TL_RGB565:
        color[0] = (palette[0] >> 3) * 0x8
        color[1] = (((palette[0] & 0x7) << 3) | (palette[1] >> 5)) * 0x4
        color[2] = (palette[1] & 0x1F) * 0x8
        color[3] = 0xFF;
    elif fmt == gx.GX_TL_RGB5A3:
        if palette[0] & 0x80:
            color[0] = ((palette[0] >> 2) & 0x1F) * 0x8
            color[1] = (((palette[0] & 0x3) << 3) | (palette[1] >> 5)) * 0x8
            color[2] = (palette[1] & 0x1F) * 0x8
            color[3] = 0xFF;
        else:
            color[0] = (palette[0] & 0xF) * 0x10
            color[1] = (palette[1] >> 4) * 0x10
            color[2] = (palette[1] & 0xF) * 0x10
            color[3] = ((palette[0] >> 4) & 0x7) * 0x20
    return array.array('B', color)

def convert_I4_block(dst, src, blocks_x, _):
    c = 0
    s = 0
    for i in range(TILE_T_I4):
        for j in range(TILE_S_I4 // 2):
            val = src[s] >> 4 << 4
            dst[c + 0] = val
            dst[c + 1] = val
            dst[c + 2] = val
            dst[c + 3] = val # 0xFF
            val = (src[s] & 0xF) << 4
            dst[c + 4] = val
            dst[c + 5] = val
            dst[c + 6] = val
            dst[c + 7] = val #0xFF
            c += 2 * ccc
            s += (BITSPPX_I4 * 2) >> 3
        c += (blocks_x - 1) * TILE_S_I4 * ccc

def convert_I8_block(dst, src, blocks_x, _):
    c = 0
    s = 0
    for i in range(TILE_T_I8):
        for j in range(TILE_S_I8):
            val = src[s]
            dst[c + 0] = val
            dst[c + 1] = val
            dst[c + 2] = val
            dst[c + 3] = val #0xFF
            c += ccc
            s += BITSPPX_I8 >> 3
        c += (blocks_x - 1) * TILE_S_I8 * ccc

def convert_IA4_block(dst, src, blocks_x, _):
    c = 0
    s = 0
    for i in range(TILE_T_IA4):
        for j in range(TILE_S_IA4):
            val = (src[s] & 0xF) << 4
            dst[c + 0] = val
            dst[c + 1] = val
            dst[c + 2] = val
            dst[c + 3] = src[s] & 0xF0
            c += ccc
            s += BITSPPX_IA4 >> 3
        c += (blocks_x - 1) * TILE_S_IA4 * ccc

def convert_IA8_block(dst, src, blocks_x, _):
    c = 0
    s = 0
    for i in range(TILE_T_IA8):
        for j in range(TILE_S_IA8):
            val = src[s + 1]
            dst[c + 0] = val
            dst[c + 1] = val
            dst[c + 2] = val
            dst[c + 3] = src[s]
            c += ccc
            s += TILE_S_IA8 >> 3
        c += (blocks_x - 1) * TILE_S_IA8 * ccc

def convert_RGB565_block(dst, src, blocks_x, _):
    c = 0
    s = 0
    for i in range(TILE_T_RGB565):
        for j in range(TILE_S_RGB565):
            dst[c + 0] = (src[s + 0] >> 3) * 0x8
            dst[c + 1] = (((src[s + 0] & 0x7) << 3) | (src[s + 1] >> 5)) * 0x4
            dst[c + 2] = (src[s + 1] & 0x1F) * 0x8
            dst[c + 3] = 0xFF
            c += ccc
            s += BITSPPX_RGB565 >> 3
        c += (blocks_x - 1) * TILE_S_RGB565 * ccc

def convert_RGB5A3_block(dst, src, blocks_x, _):
    c = 0
    s = 0
    for i in range(TILE_T_RGB5A3):
        for j in range(TILE_S_RGB5A3):
            if src[s + 0] & 0x80:
                dst[c + 0] = ((src[s + 0] >> 2) & 0x1F) * 0x8
                dst[c + 1] = (((src[s + 0] & 0x3) << 3) | (src[s + 1] >> 5)) * 0x8
                dst[c + 2] = (src[s + 1] & 0x1F) * 0x8
                dst[c + 3] = 0xFF;
            else:
                dst[c + 0] = (src[s + 0] & 0xF) * 0x10
                dst[c + 1] = (src[s + 1] >> 4) * 0x10
                dst[c + 2] = (src[s + 1] & 0xF) * 0x10
                dst[c + 3] = ((src[s + 0] >> 4) & 0x7) * 0x20
            c += ccc
            s += BITSPPX_RGB5A3 >> 3
        c += (blocks_x - 1) * TILE_S_RGB5A3 * ccc

def convert_RGBA8_block(dst, src, blocks_x, _):
    c = 0
    s = 0
    for i in range(TILE_T_RGBA8):
        for j in range(TILE_S_RGBA8):
            dst[c + 0] = src[s + 1]
            dst[c + 1] = src[s + 32]
            dst[c + 2] = src[s + 33]
            dst[c + 3] = src[s + 0]
            c += ccc
            s += 2
        c += (blocks_x - 1) * TILE_S_RGBA8 * ccc

def convert_CMPR_block(dst, src, blocks_x, _):
    c = 0
    s = 0
    for j in range(2):
        for k in range(2):
            colors = [array.array('B', [0] * ccc),
                      array.array('B', [0] * ccc),
                      array.array('B', [0] * ccc),
                      array.array('B', [0] * ccc)]

            #read 2-color palette
            colors[0][0] = (  src[s + 0]     >>3)                        << 3
            colors[0][1] = (((src[s + 0]&0x7)<<3)|((src[s + 1]>>5)&0x7)) << 2
            colors[0][2] =                         (src[s + 1]    &0x1F) << 3
            colors[0][3] = 0xFF

            colors[1][0] = (  src[s + 2]     >>3)                        << 3
            colors[1][1] = (((src[s + 2]&0x7)<<3)|((src[s + 3]>>5)&0x7)) << 2
            colors[1][2] =                         (src[s + 3]    &0x1F) << 3
            colors[1][3] = 0xFF

            #get two more colors from the original palette
    		#is first color numerically greater ?
            c0 = (src[s + 0] << 8) | src[s + 1]
            c1 = (src[s + 2] << 8) | src[s + 3]
            if c0 > c1:
                #yes, triangulate colors between original two
                colors[2][0] = (2 * colors[0][0] + colors[1][0]) // 3
                colors[2][1] = (2 * colors[0][1] + colors[1][1]) // 3
                colors[2][2] = (2 * colors[0][2] + colors[1][2]) // 3
                colors[2][3] = 0xFF

                colors[3][0] = (colors[0][0] + 2 * colors[1][0]) // 3
                colors[3][1] = (colors[0][1] + 2 * colors[1][1]) // 3
                colors[3][2] = (colors[0][2] + 2 * colors[1][2]) // 3
                colors[3][3] = 0xFF
            else:
                #no, first is middle between the originals and the other one transparent
                colors[2][0] = (colors[0][0] + colors[1][0]) // 2
                colors[2][1] = (colors[0][1] + colors[1][1]) // 2
                colors[2][2] = (colors[0][2] + colors[1][2]) // 2
                colors[2][3] = 0xFF

                #contrary to documentation the RGB components are not 0
                #Reference: [https://www.khronos.org/opengl/wiki/S3_Texture_Compression#DXT1_Format]
                colors[3][0] = (colors[0][0] + colors[1][0]) // 2
                colors[3][1] = (colors[0][1] + colors[1][1]) // 2
                colors[3][2] = (colors[0][2] + colors[1][2]) // 2
                colors[3][3] = 0x0
            s += 4

            #one subblock
            cc = c
            for l in range(4):
                dst[cc + 0 * ccc: cc + 4 * ccc] = colors[(src[s + l] >> 6) & 0x3] +\
                                                  colors[(src[s + l] >> 4) & 0x3] +\
                                                  colors[(src[s + l] >> 2) & 0x3] +\
                                                  colors[(src[s + l] >> 0) & 0x3]
                cc += blocks_x * TILE_S_CMPR * ccc
            s += 4
            c += 4 * ccc
        c += (blocks_x * 4 - 1) * TILE_S_CMPR * ccc


def convert_C4_block(dst, src, blocks_x, tlut):
    c = 0
    s = 0
    for i in range(TILE_T_C4):
        for j in range(TILE_S_C4 // 2):
            dst[c + 0: c + ccc]       = get_palette_color(tlut.lut[((src[s + 0] & 0xF0) >> 4) * 2:], tlut.fmt)
            dst[c + ccc: c + 2 * ccc] = get_palette_color(tlut.lut[(src[s + 0] & 0xF) * 2:], tlut.fmt)
            s += (BITSPPX_C4 * 2) >> 3
            c += 2 * ccc
        c += (blocks_x - 1) * TILE_S_C4 * ccc

def convert_C8_block(dst, src, blocks_x, tlut):
        c = 0
        s = 0
        for i in range(TILE_T_C8):
            for j in range(TILE_S_C8):
                dst[c: c + ccc] = get_palette_color(tlut.lut[src[s] * 2:], tlut.fmt)
                s += BITSPPX_C8 >> 3
                c += ccc
            c += (blocks_x - 1) * TILE_S_C8 * ccc

def convert_C14X2_block(dst, src, blocks_x, tlut):
    c = 0
    s = 0
    for i in range(TILE_T_C14X2):
        for j in range(TILE_S_C14X2):
            dst[c: c + ccc] = get_palette_color(tlut.lut[((src[s + 0] << 8) | src[s + 1]) * 2], tlut.fmt)
            s += BITSPPX_C14X2 >> 3
            c += ccc
        c += (blocks_x - 1) * TILE_S_C14X2 * ccc

format_dict = {
    #                 bits per pixel| tile width   | tile height  | func
    gx.GX_TF_I4:     (BITSPPX_I4    , TILE_S_I4    , TILE_T_I4    , convert_I4_block    ),
    gx.GX_TF_I8:     (BITSPPX_I8    , TILE_S_I8    , TILE_T_I8    , convert_I8_block    ),
    gx.GX_TF_IA4:    (BITSPPX_IA4   , TILE_S_IA4   , TILE_T_IA4   , convert_IA4_block   ),
    gx.GX_TF_IA8:    (BITSPPX_IA8   , TILE_S_IA8   , TILE_T_IA8   , convert_IA8_block   ),
    gx.GX_TF_RGB565: (BITSPPX_RGB565, TILE_S_RGB565, TILE_T_RGB565, convert_RGB565_block),
    gx.GX_TF_RGB5A3: (BITSPPX_RGB5A3, TILE_S_RGB5A3, TILE_T_RGB5A3, convert_RGB5A3_block),
    gx.GX_TF_RGBA8:  (BITSPPX_RGBA8 , TILE_S_RGBA8 , TILE_T_RGBA8 , convert_RGBA8_block ),
    gx.GX_TF_CMPR:   (BITSPPX_CMPR  , TILE_S_CMPR  , TILE_T_CMPR  , convert_CMPR_block  ),
    #GXCITexFmt
    gx.GX_TF_C4:     (BITSPPX_C4    , TILE_S_C4    , TILE_T_C4    , convert_C4_block    ),
    gx.GX_TF_C8:     (BITSPPX_C8    , TILE_S_C8    , TILE_T_C8    , convert_C8_block    ),
    gx.GX_TF_C14X2:  (BITSPPX_C14X2 , TILE_S_C14X2 , TILE_T_C14X2 , convert_C14X2_block ),
}

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
