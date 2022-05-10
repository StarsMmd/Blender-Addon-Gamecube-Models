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




