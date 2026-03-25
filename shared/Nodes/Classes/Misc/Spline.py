
from ...Node import Node

# Spline
class Spline(Node):
    class_name = "Spline"
    fields = [
        ('flags', 'ushort'),
        ('n', 'ushort'),
        ('f0', 'float'),
        ('s1', 'uint'),
        ('f1', 'float'),
        ('s2', 'uint'),
        ('s3', 'uint'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        spline_type = self.flags >> 8
        parser.logger.debug("Spline 0x%X: type=%d, n=%d, s1=0x%X, s2=0x%X, s3=0x%X",
                            self.address, spline_type, self.n, self.s1 or 0, self.s2 or 0, self.s3 or 0)
        if (self.flags >> 8) == 0:
            if self.s1:
                s1_address = self.s1
                self.s1 = []
                for i in range(self.n):
                    v = []
                    for j in range(3):
                        offset = i * 12 + j * 4
                        value = parser.read('float', s1_address, offset)
                        v.append(value)
                    self.s1.append(v)

            else:
                self.s1 = None

            if not self.s3:
                self.s3 = None

        elif (self.flags >> 8) == 3:
            if self.s1:
                s1_address = self.s1
                self.s1 = []
                for i in range(self.n + 2):
                    v = []
                    for j in range(3):
                        offset = i * 12 + j * 4
                        value = parser.read('float', s1_address, offset)
                        v.append(value)
                    self.s1.append(v)

            else:
                self.s1 = None

            if self.s3:
                s3_address = self.s3
                self.s3 = []
                for i in range(self.n - 1):
                    v = []
                    for j in range(5):
                        offset = i * 20 + j * 4
                        value = parser.read('float', s3_address, offset)
                        v.append(value)
                    self.s3.append(v)

            else:
                self.s3 = None

        else:
            pass

        if self.s2:
            s2_address = self.s2
            self.s2 = []
            for i in range(self.n):
                offset = i * 4
                value = parser.read('float', s2_address, offset)
                self.s2.append(value)

        else:
            self.s2 = None

    def writePrivateData(self, builder):
        super().writePrivateData(builder)

        # Write s1 float array (3 floats per control point)
        if isinstance(self.s1, list) and self.s1:
            builder.seek(0, 'end')
            addr = builder._currentRelativeAddress()
            for pt in self.s1:
                for v in pt:
                    builder.write(v, 'float')
            self.s1 = addr
            self._raw_pointer_fields.add('s1')
        else:
            self.s1 = 0

        # Write s2 float array (1 float per knot/weight)
        if isinstance(self.s2, list) and self.s2:
            builder.seek(0, 'end')
            addr = builder._currentRelativeAddress()
            for v in self.s2:
                builder.write(v, 'float')
            self.s2 = addr
            self._raw_pointer_fields.add('s2')
        else:
            self.s2 = 0

        # Write s3 float array (5 floats per entry)
        if isinstance(self.s3, list) and self.s3:
            builder.seek(0, 'end')
            addr = builder._currentRelativeAddress()
            for entry in self.s3:
                for v in entry:
                    builder.write(v, 'float')
            self.s3 = addr
            self._raw_pointer_fields.add('s3')
        else:
            self.s3 = 0

