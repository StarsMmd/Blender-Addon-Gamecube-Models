import struct
import os

from ..Constants import *

class BinaryReader:
    """
    Wrapper class to simplify reading data of various types
    from a binary file (assumes big-endian byte order)
    """
    
    def __init__(self, filepath):
        self.filepath = filepath
        self.file = open(filepath, 'rb')
        self.filesize = os.path.getsize(filepath)

    def read(self, type, address, offset=0, whence='start'):
        """
        Reads data of type `type` from `base` + `offset`
        relative to `whence` ('start' or 'current')
        """
        self.seek(address + offset, whence)
        if is_primitive_type(type):
            if type == 'void':
                return None
            elif type == 'string':
                return self._read_string()
            elif type == 'vec3':
                format = get_primitive_type_format(type)
                length = get_primitive_type_length(type)
                return struct.unpack(format, self.file.read(length))
            elif type == 'matrix':
                rows = []
                for i in range(3):
                    self.seek(address + offset + (i * 16))
                    rows.append(list(struct.unpack('>4f', self.file.read(16))))
                rows.append([0,0,0,1])
                return rows
            else:
                format = get_primitive_type_format(type)
                length = get_primitive_type_length(type)
                return struct.unpack(format, self.file.read(length))[0]
        else:
            raise InvalidPrimitiveTypeError()

    def _read_string(self):
        """
        Reads a char[] from the current position
        and converts it to an ascii string
        """
        s = ''
        nextChar = self.file.read(1)[0] # converts byte to int
        while nextChar != 0:
            s += chr(nextChar)
            nextChar = self.file.read(1)[0]
        return s

    def read_chunk(self, size, address, offset=0):
        """Reads `size` bytes from `address`"""
        self.seek(address + offset)
        return self.file.read(size)

    def seek(self, offset, whence='start'):
        """
        Moves the BinaryReader's file to `offset`
        relative to `whence` ('start' or 'current')
        """
        if whence == 'start':
            self.file.seek(offset)
        elif whence == 'current':
            self.file.seek(offset, 1)
        else:
            raise ValueError(f'Invalid value for `whence`: {whence}')

    def close(self):
        """Closes the BinaryReader's file"""
        self.file.close()

class BinaryWriter:
    """
    Wrapper class to simplify writing data of various types
    to a binary file (uses big-endian byte order)
    """
    
    def __init__(self, filepath):
        self.filepath = filepath
        self.file = open(filepath, 'wb+')

    def currentAddress(self):
    	return self.file.tell()

    def seek(self, offset, whence='start'):
        """
        Moves the BinaryReader's file to `offset`
        relative to `whence` ('start' or 'current')
        """
        if whence == 'start':
            self.file.seek(offset)
        elif whence == 'current':
            self.file.seek(offset, 1)
        elif whence == 'end':
            self.file.seek(offset, 2)
        else:
            raise ValueError(f'Invalid value for `whence`: {whence}')

    def write(self, type, data, offset=None, whence='start'):
        """
        Writes `data` as type `type` to `offset`
        relative to `whence` ('start' or 'current')
        """
        if offset != None:
        	self.seek(offset, whence)
        
        if is_primitive_type(type):
            if type == 'void':
                return
            elif type == 'string':
                # TODO: confirm if this includes null terminator byte
                self.file.write(bytes(data, 'utf-8'))
            elif type == 'vec3':
                for i in range(3):
                    self.file.write(struct.pack('>f', data[i]))
            elif type == 'matrix':
                rows = []
                for i in range(3):
                    row = data[i]
                    for j in range(4):
                        self.file.write(struct.pack('>f', row[j]))
            else:
                format = get_primitive_type_format(type)
                self.file.write(struct.pack(format, data))
        else:
            raise InvalidPrimitiveTypeError()

    def close(self):
        """Closes the BinaryWriter's file"""
        self.file.close()


