"""sRGB <-> linear color space conversion utilities."""


def srgb_to_linear(c: float) -> float:
    """Convert a single sRGB channel value (0-1) to linear."""
    if c <= 0.0404482362771082:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    """Convert a single linear channel value (0-1) to sRGB."""
    if c <= 0.00313066844250063:
        return c * 12.92
    return 1.055 * (c ** (1.0 / 2.4)) - 0.055
