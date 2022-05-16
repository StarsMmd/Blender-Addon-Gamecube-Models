from ...Node import Node
from .Color import Color

# RGB Color
class RGBColor(Node, Color):
    class_name = "RGB Color"
    is_cachable = False
    fields = [
        ('red', 'uchar'),
        ('green', 'uchar'),
        ('blue', 'uchar'),
        ('padding', 'uchar')
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        self.alpha = 0xFF