from __future__ import annotations
from dataclasses import dataclass, field

from .enums import (
    ColorSource, LightingModel, CoordType, WrapMode, TextureInterpolation,
    LayerBlendMode, LightmapChannel, CombinerInputSource, CombinerOp,
    CombinerBias, CombinerScale, OutputBlendEffect, BlendFactor,
)


@dataclass
class IRMaterial:
    """Complete material description."""
    diffuse_color: tuple[float, float, float, float]
    ambient_color: tuple[float, float, float, float]
    specular_color: tuple[float, float, float, float]
    alpha: float
    shininess: float
    color_source: ColorSource
    alpha_source: ColorSource
    lighting: LightingModel
    enable_specular: bool
    is_translucent: bool
    texture_layers: list[IRTextureLayer] = field(default_factory=list)
    fragment_blending: FragmentBlending | None = None


@dataclass
class IRTextureLayer:
    """One texture in the material's layer stack."""
    image: IRImage
    coord_type: CoordType
    uv_index: int
    # Transform
    rotation: tuple[float, float, float]
    scale: tuple[float, float, float]
    translation: tuple[float, float, float]
    # Wrapping
    wrap_s: WrapMode
    wrap_t: WrapMode
    repeat_s: int
    repeat_t: int
    # Sampling
    interpolation: TextureInterpolation | None
    # Compositing
    color_blend: LayerBlendMode
    alpha_blend: LayerBlendMode
    blend_factor: float
    lightmap_channel: LightmapChannel
    is_bump: bool
    # Optional color combiner
    combiner: ColorCombiner | None = None


@dataclass
class IRImage:
    """Decoded image data ready for use."""
    name: str
    width: int
    height: int
    pixels: bytes | list[float]  # raw RGBA u8 bytes or normalized floats, row-major
    image_id: int
    palette_id: int


@dataclass
class CombinerInput:
    """One input to the color combiner formula."""
    source: CombinerInputSource
    channel: str | None = None
    value: tuple[float, float, float, float] | None = None


@dataclass
class CombinerStage:
    """One channel (color or alpha) of the color combiner.
    Computes: clamp(scale * (lerp(input_a, input_b, input_c) +/- input_d + bias))"""
    input_a: CombinerInput
    input_b: CombinerInput
    input_c: CombinerInput
    input_d: CombinerInput
    operation: CombinerOp
    bias: CombinerBias
    scale: CombinerScale
    clamp: bool


@dataclass
class ColorCombiner:
    """Per-texture color/alpha combiner configuration."""
    color: CombinerStage | None = None
    alpha: CombinerStage | None = None


@dataclass
class FragmentBlending:
    """How the material's output composites with the framebuffer."""
    effect: OutputBlendEffect
    source_factor: BlendFactor
    dest_factor: BlendFactor
    alpha_test_threshold_0: int
    alpha_test_threshold_1: int
    alpha_test_op: int
    depth_compare: int
