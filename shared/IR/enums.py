from enum import Enum


class CoordType(Enum):
    """Texture coordinate generation mode."""
    UV = "UV"
    REFLECTION = "REFLECTION"
    SPECULAR_HIGHLIGHT = "SPECULAR_HIGHLIGHT"
    SHADOW = "SHADOW"
    CEL_SHADING = "CEL_SHADING"
    GRADATION = "GRADATION"


class WrapMode(Enum):
    """Texture wrapping mode."""
    CLAMP = "CLAMP"
    REPEAT = "REPEAT"
    MIRROR = "MIRROR"


class Interpolation(Enum):
    """Keyframe interpolation type."""
    CONSTANT = "CONSTANT"
    LINEAR = "LINEAR"
    BEZIER = "BEZIER"


class TextureInterpolation(Enum):
    """Texture sampling interpolation."""
    CLOSEST = "Closest"
    LINEAR = "Linear"
    CUBIC = "Cubic"


class LightType(Enum):
    """Light source type."""
    AMBIENT = "AMBIENT"
    SUN = "SUN"
    POINT = "POINT"
    SPOT = "SPOT"


class CameraProjection(Enum):
    """Camera projection mode."""
    PERSPECTIVE = "PERSPECTIVE"
    ORTHO = "ORTHO"


class SkinType(Enum):
    """Mesh skinning/deformation mode."""
    WEIGHTED = "WEIGHTED"
    SINGLE_BONE = "SINGLE_BONE"
    RIGID = "RIGID"


class ScaleInheritance(Enum):
    """Bone scale inheritance mode."""
    ALIGNED = "ALIGNED"


class ColorSource(Enum):
    """Where the base diffuse color or alpha comes from."""
    MATERIAL = "MATERIAL"
    VERTEX = "VERTEX"
    BOTH = "BOTH"


class LightingModel(Enum):
    """How the surface responds to scene lighting."""
    LIT = "LIT"
    UNLIT = "UNLIT"


class LayerBlendMode(Enum):
    """How a texture layer composites onto the accumulated color or alpha."""
    NONE = "NONE"
    PASS = "PASS"
    REPLACE = "REPLACE"
    MULTIPLY = "MULTIPLY"
    ADD = "ADD"
    SUBTRACT = "SUBTRACT"
    MIX = "MIX"
    ALPHA_MASK = "ALPHA_MASK"
    RGB_MASK = "RGB_MASK"


class LightmapChannel(Enum):
    """Which lighting channel a texture contributes to."""
    NONE = "NONE"
    DIFFUSE = "DIFFUSE"
    SPECULAR = "SPECULAR"
    AMBIENT = "AMBIENT"
    EXTENSION = "EXTENSION"
    SHADOW = "SHADOW"


class CombinerInputSource(Enum):
    """What value feeds into a color combiner input slot."""
    ZERO = "ZERO"
    ONE = "ONE"
    HALF = "HALF"
    TEXTURE_COLOR = "TEXTURE_COLOR"
    TEXTURE_ALPHA = "TEXTURE_ALPHA"
    CONSTANT = "CONSTANT"
    REGISTER_0 = "REGISTER_0"
    REGISTER_1 = "REGISTER_1"


class CombinerOp(Enum):
    """Color combiner arithmetic operation."""
    ADD = "ADD"
    SUBTRACT = "SUBTRACT"
    COMPARE_R8_GT = "COMPARE_R8_GT"
    COMPARE_R8_EQ = "COMPARE_R8_EQ"
    COMPARE_GR16_GT = "COMPARE_GR16_GT"
    COMPARE_GR16_EQ = "COMPARE_GR16_EQ"
    COMPARE_BGR24_GT = "COMPARE_BGR24_GT"
    COMPARE_BGR24_EQ = "COMPARE_BGR24_EQ"
    COMPARE_RGB8_GT = "COMPARE_RGB8_GT"
    COMPARE_RGB8_EQ = "COMPARE_RGB8_EQ"


class CombinerBias(Enum):
    """Bias added after the combiner operation."""
    ZERO = "ZERO"
    PLUS_HALF = "+0.5"
    MINUS_HALF = "-0.5"


class CombinerScale(Enum):
    """Scale factor applied to the combiner result."""
    SCALE_1 = "1"
    SCALE_2 = "2"
    SCALE_4 = "4"
    SCALE_HALF = "0.5"


class OutputBlendEffect(Enum):
    """Resolved semantic blend effect for framebuffer compositing."""
    OPAQUE = "OPAQUE"
    ALPHA_BLEND = "ALPHA_BLEND"
    INVERSE_ALPHA_BLEND = "INVERSE_ALPHA_BLEND"
    ADDITIVE = "ADDITIVE"
    ADDITIVE_ALPHA = "ADDITIVE_ALPHA"
    ADDITIVE_INV_ALPHA = "ADDITIVE_INV_ALPHA"
    MULTIPLY = "MULTIPLY"
    SRC_ALPHA_ONLY = "SRC_ALPHA_ONLY"
    INV_SRC_ALPHA_ONLY = "INV_SRC_ALPHA_ONLY"
    INVISIBLE = "INVISIBLE"
    BLACK = "BLACK"
    WHITE = "WHITE"
    INVERT = "INVERT"
    CUSTOM = "CUSTOM"


class BlendFactor(Enum):
    """Source/destination blend factor for fragment blending."""
    ZERO = "ZERO"
    ONE = "ONE"
    SRC_COLOR = "SRC_COLOR"
    INV_SRC_COLOR = "INV_SRC_COLOR"
    SRC_ALPHA = "SRC_ALPHA"
    INV_SRC_ALPHA = "INV_SRC_ALPHA"
    DST_ALPHA = "DST_ALPHA"
    INV_DST_ALPHA = "INV_DST_ALPHA"


class ShinyChannel(Enum):
    """Source channel for shiny color filter routing."""
    RED = 0
    GREEN = 1
    BLUE = 2
    ALPHA = 3


class GXTextureFormat(Enum):
    """GX texture format for export encoding."""
    AUTO = "AUTO"
    I4 = "I4"
    I8 = "I8"
    IA4 = "IA4"
    IA8 = "IA8"
    RGB565 = "RGB565"
    RGB5A3 = "RGB5A3"
    RGBA8 = "RGBA8"
    CMPR = "CMPR"
    C4 = "C4"
    C8 = "C8"
    C14X2 = "C14X2"
