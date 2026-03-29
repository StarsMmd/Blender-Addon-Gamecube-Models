import codecs
import binascii
import struct


def read_c_string(data):
    try:
        end = 0
        while data[end] != 0 and end <= len(data):
            end += 1
        if end < len(data):
            return codecs.decode(data[:end], 'ascii')
    except:
        #TODO:
        pass
    return ''

def read_u32(data):
    return struct.unpack('>I', data[:4])[0]
