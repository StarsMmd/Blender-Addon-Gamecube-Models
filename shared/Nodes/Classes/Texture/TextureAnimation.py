from ...Node import Node
from ....Constants import *
from ....helpers.logger import StubLogger
from ..Animation.Frame import read_fobjdesc

# Mapping: HSD texture animation track type → (Mapping node input index, component index)
# Mapping node inputs: 0=Vector, 1=Location, 2=Rotation, 3=Scale
_tex_uv_map = {
    HSD_A_T_TRAU: (1, 0),  # Location X
    HSD_A_T_TRAV: (1, 1),  # Location Y
    HSD_A_T_SCAU: (3, 0),  # Scale X
    HSD_A_T_SCAV: (3, 1),  # Scale Y
    HSD_A_T_ROTX: (2, 0),  # Rotation X
    HSD_A_T_ROTY: (2, 1),  # Rotation Y
    HSD_A_T_ROTZ: (2, 2),  # Rotation Z
}

# Texture Animation
class TextureAnimation(Node):
    class_name = "Texture Animation"
    fields = [
        ('next', 'TextureAnimation'),
        ('id', 'uint'),
        ('animation', 'Animation'),
        ('image_table', '*(Image[image_table_count])'),
        ('palette_table', '*(Palette[palette_table_count])'),
        ('image_table_count', 'ushort'),
        ('palette_table_count', 'ushort'),
    ]

