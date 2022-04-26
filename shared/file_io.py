import struct
import os

primitive_field_types = [
    'uchar', 'ushort', 'uint', 'char', 'short', 'int', 'float', 'double', 'string', 'matrix'
]

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
        
        if type == 'uchar':
            return struct.unpack('>B', self.file.read(1))[0]
        if type == 'ushort':
            return struct.unpack('>H', self.file.read(2))[0]
        if type == 'uint':
            return struct.unpack('>I', self.file.read(4))[0]
        if type == 'char':
            return struct.unpack('>b', self.file.read(1))[0]
        if type == 'short':
            return struct.unpack('>h', self.file.read(2))[0]
        if type == 'int':
            return struct.unpack('>i', self.file.read(4))[0]
        if type == 'float':
            return struct.unpack('>f', self.file.read(4))[0]
        if type == 'double':
            return struct.unpack('>d', self.file.read(8))[0]
        if type == 'string':
            return self._read_string()
        if type == 'matrix':
            rows = []
            for i in range(3):
                self.seek(address + offset + (i * 16))
                rows.append(list(struct.unpack('>4f', self.file.read(16))))
            rows.append([0,0,0,1])
            return rows
        raise ValueError(f'Invalid value for arg `type`: {type}')

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

    def write(type, data, offset=None, whence='start'):
        """
        Writes `data` as type `type` to `offset`
        relative to `whence` ('start' or 'current')
        """
        if offset != None:
        	self.seek(offset, whence)
        
        if type == 'uint8':
            self.file.write(struct.pack('>B', data))
        elif type == 'uint16':
            self.file.write(struct.pack('>H', data))
        elif type == 'uint32':
            self.file.write(struct.pack('>I', data))
        elif type == 'int8':
            self.file.write(struct.pack('>b', data))
        elif type == 'int16':
            self.file.write(struct.pack('>h', data))
        elif type == 'int32':
            self.file.write(struct.pack('>i', data))
        elif type == 'float':
            self.file.write(struct.pack('>f', data))
        elif type == 'double':
            self.file.write(struct.pack('>d', data))
        elif type == 'string':
            # TODO: confirm if this includes null terminator byte
            self.file.write(bytes(data, 'utf-8'))
        else:
            raise ValueError(f'Invalid value for arg `type`: {type}')

    def close(self):
        """Closes the BinaryWriter's file"""
        self.file.close()


