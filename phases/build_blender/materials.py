"""Build Blender materials from IRMaterial dataclasses.

Constructs the shader node tree matching the legacy MaterialObject.build(),
reading entirely from IR types instead of parsed nodes.
"""
import math
import bpy
from mathutils import Vector

try:
    from ...shared.IR.enums import (
        ColorSource, LightingModel, CoordType, WrapMode, TextureInterpolation,
        LayerBlendMode, LightmapChannel, CombinerInputSource, CombinerOp,
        CombinerBias, CombinerScale, OutputBlendEffect, BlendFactor,
    )
    from ...shared.BlenderVersion import BlenderVersion
except (ImportError, SystemError):
    from shared.IR.enums import (
        ColorSource, LightingModel, CoordType, WrapMode, TextureInterpolation,
        LayerBlendMode, LightmapChannel, CombinerInputSource, CombinerOp,
        CombinerBias, CombinerScale, OutputBlendEffect, BlendFactor,
    )
    from shared.BlenderVersion import BlenderVersion


def build_material(ir_material, image_cache=None):
    """Create a Blender material from IRMaterial.

    Args:
        ir_material: IRMaterial dataclass.
        image_cache: dict for caching bpy.data.images by (image_id, palette_id).

    Returns:
        bpy.types.Material.
    """
    if image_cache is None:
        image_cache = {}

    mat = bpy.data.materials.new('')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    for node in nodes:
        nodes.remove(node)
    output = nodes.new('ShaderNodeOutputMaterial')

    # --- Base color and alpha ---
    color_out, alpha_out = _build_base_color_alpha(ir_material, nodes, links)

    last_color = color_out
    last_alpha = alpha_out
    bump_map = None

    # --- Texture chain ---
    for tex_layer in ir_material.texture_layers:
        cur_color, cur_alpha, uv_output = _build_texture_sampling(tex_layer, nodes, links, image_cache)

        # TEV combiner
        if tex_layer.combiner:
            if tex_layer.combiner.color:
                cur_color = _build_tev_stage(nodes, links, tex_layer.combiner.color, cur_color, cur_alpha, is_color=True)
            if tex_layer.combiner.alpha:
                cur_alpha = _build_tev_stage(nodes, links, tex_layer.combiner.alpha, cur_color, cur_alpha, is_color=False)

        if tex_layer.is_bump:
            if bump_map:
                mix = nodes.new('ShaderNodeMixRGB')
                mix.blend_type = 'MIX'
                mix.inputs[0].default_value = tex_layer.blend_factor
                links.new(bump_map, mix.inputs[1])
                links.new(cur_color, mix.inputs[2])
                bump_map = mix.outputs[0]
            else:
                bump_map = cur_color
        else:
            # Apply color/alpha blending for textures with appropriate lightmap type
            lmc = tex_layer.lightmap_channel
            if lmc == LightmapChannel.NONE or lmc in (LightmapChannel.DIFFUSE, LightmapChannel.AMBIENT, LightmapChannel.SPECULAR, LightmapChannel.EXTENSION):
                last_color = _apply_blend(nodes, links, last_color, cur_color, cur_alpha, tex_layer.color_blend, tex_layer.blend_factor, is_color=True)
                last_alpha = _apply_blend(nodes, links, last_alpha, cur_alpha, cur_alpha, tex_layer.alpha_blend, tex_layer.blend_factor, is_color=False)

    # --- Post-texture vertex color multiply ---
    if ir_material.lighting == LightingModel.LIT:
        if ir_material.color_source in (ColorSource.VERTEX, ColorSource.BOTH):
            vtx_color = nodes.new('ShaderNodeAttribute')
            vtx_color.attribute_name = 'color_0'
            mult = nodes.new('ShaderNodeMixRGB')
            mult.inputs[0].default_value = 1
            mult.blend_type = 'MULTIPLY'
            links.new(vtx_color.outputs[0], mult.inputs[1])
            links.new(last_color, mult.inputs[2])
            last_color = mult.outputs[0]

        if ir_material.alpha_source in (ColorSource.VERTEX, ColorSource.BOTH):
            vtx_alpha = nodes.new('ShaderNodeAttribute')
            vtx_alpha.attribute_name = 'alpha_0'
            mult = nodes.new('ShaderNodeMixRGB')
            mult.inputs[0].default_value = 1
            mult.blend_type = 'MULTIPLY'
            links.new(vtx_alpha.outputs[0], mult.inputs[1])
            links.new(last_alpha, mult.inputs[2])
            last_alpha = mult.outputs[0]

    # --- Pixel engine / fragment blending ---
    transparent_shader = False
    alt_blend_mode = 'NOTHING'
    last_color, last_alpha, transparent_shader, alt_blend_mode = _build_pixel_engine(
        ir_material, nodes, links, last_color, last_alpha, mat
    )

    # --- Output shader ---
    shader = _build_output_shader(
        ir_material, nodes, links, last_color, last_alpha, bump_map,
        transparent_shader, alt_blend_mode, mat
    )

    links.new(shader.outputs[0], output.inputs[0])
    return mat


def _build_base_color_alpha(ir_mat, nodes, links):
    """Build base color and alpha nodes from IRMaterial source flags."""
    dc = ir_mat.diffuse_color

    if ir_mat.lighting == LightingModel.LIT:
        # RENDER_DIFFUSE set
        color = nodes.new('ShaderNodeRGB')
        color.name = 'DiffuseColor'
        if ir_mat.color_source == ColorSource.VERTEX:
            color.outputs[0].default_value[:] = [1, 1, 1, 1]
        else:
            color.outputs[0].default_value[:] = list(dc)

        alpha = nodes.new('ShaderNodeValue')
        alpha.name = 'AlphaValue'
        if ir_mat.alpha_source == ColorSource.VERTEX:
            alpha.outputs[0].default_value = 1
        else:
            alpha.outputs[0].default_value = ir_mat.alpha

    else:
        # RENDER_DIFFUSE not set — vertex color is the base
        if ir_mat.color_source == ColorSource.MATERIAL:
            color = nodes.new('ShaderNodeRGB')
            color.name = 'DiffuseColor'
            color.outputs[0].default_value[:] = list(dc)
        else:
            color = nodes.new('ShaderNodeAttribute')
            color.attribute_name = 'color_0'
            if ir_mat.color_source == ColorSource.BOTH:
                diff = nodes.new('ShaderNodeRGB')
                diff.name = 'DiffuseColor'
                diff.outputs[0].default_value[:] = list(dc)
                mix = nodes.new('ShaderNodeMixRGB')
                mix.blend_type = 'ADD'
                mix.inputs[0].default_value = 1
                links.new(color.outputs[0], mix.inputs[1])
                links.new(diff.outputs[0], mix.inputs[2])
                color = mix

        if ir_mat.alpha_source == ColorSource.MATERIAL:
            alpha = nodes.new('ShaderNodeValue')
            alpha.name = 'AlphaValue'
            alpha.outputs[0].default_value = ir_mat.alpha
        else:
            alpha = nodes.new('ShaderNodeAttribute')
            alpha.attribute_name = 'alpha_0'
            if ir_mat.alpha_source == ColorSource.BOTH:
                mat_alpha = nodes.new('ShaderNodeValue')
                mat_alpha.name = 'AlphaValue'
                mat_alpha.outputs[0].default_value = ir_mat.alpha
                mix = nodes.new('ShaderNodeMath')
                mix.operation = 'MULTIPLY'
                links.new(alpha.outputs[0], mix.inputs[0])
                links.new(mat_alpha.outputs[0], mix.inputs[1])
                alpha = mix

    return color.outputs[0], alpha.outputs[0]


def _build_texture_sampling(tex_layer, nodes, links, image_cache):
    """Build UV mapping + texture sampling nodes for one texture layer."""
    # UV coordinate source
    uv_output = None
    if tex_layer.coord_type == CoordType.UV:
        uv = nodes.new('ShaderNodeUVMap')
        uv.uv_map = f'uvtex_{tex_layer.uv_index}'
        uv_output = uv.outputs[0]
    elif tex_layer.coord_type == CoordType.REFLECTION:
        uv = nodes.new('ShaderNodeTexCoord')
        uv_output = uv.outputs[6]

    # Mapping node
    mapping = nodes.new('ShaderNodeMapping')
    mapping.vector_type = 'TEXTURE'
    mapping.inputs[2].default_value = tex_layer.rotation
    mapping.inputs[1].default_value = list(tex_layer.translation)
    mapping.inputs[3].default_value = tex_layer.scale

    # Blender UV origin is bottom-left; GX is top-left — flip V
    mapping.inputs[1].default_value[1] = 1 - tex_layer.scale[1] - tex_layer.translation[1]

    if tex_layer.coord_type == CoordType.REFLECTION:
        mapping.inputs[2].default_value[0] -= math.pi / 2

    # Repeat UV scaling
    if uv_output and (tex_layer.repeat_s > 1 or tex_layer.repeat_t > 1):
        multiply = nodes.new('ShaderNodeVectorMath')
        multiply.operation = 'MULTIPLY'
        multiply.inputs[1].default_value = (
            tex_layer.repeat_s if tex_layer.repeat_s > 1 else 1,
            tex_layer.repeat_t if tex_layer.repeat_t > 1 else 1,
            1)
        links.new(uv_output, multiply.inputs[0])
        links.new(multiply.outputs[0], mapping.inputs[0])
    elif uv_output:
        links.new(uv_output, mapping.inputs[0])

    # Texture image node
    tex_node = nodes.new('ShaderNodeTexImage')
    tex_node.image = _get_or_create_bpy_image(tex_layer.image, image_cache)

    # Wrap / extension
    has_repeat = tex_layer.wrap_s == WrapMode.REPEAT or tex_layer.wrap_t == WrapMode.REPEAT
    has_mirror = tex_layer.wrap_s == WrapMode.MIRROR or tex_layer.wrap_t == WrapMode.MIRROR
    if has_repeat or has_mirror:
        tex_node.extension = 'REPEAT'
    else:
        tex_node.extension = 'EXTEND'

    # Interpolation
    if tex_layer.interpolation:
        tex_node.interpolation = tex_layer.interpolation.value

    links.new(mapping.outputs[0], tex_node.inputs[0])

    return tex_node.outputs[0], tex_node.outputs[1], uv_output


def _get_or_create_bpy_image(ir_image, image_cache):
    """Get or create a bpy.data.images from an IRImage."""
    if ir_image is None:
        return None

    cache_key = (ir_image.image_id, ir_image.palette_id)
    if cache_key in image_cache:
        return image_cache[cache_key]

    bpy_image = bpy.data.images.new(
        ir_image.name, ir_image.width, ir_image.height, alpha=True
    )

    # IRImage.pixels can be raw u8 bytes or pre-normalized floats
    pixels = ir_image.pixels
    if isinstance(pixels, (bytes, bytearray)):
        pixels = [b / 255.0 for b in pixels]
    bpy_image.pixels = pixels

    bpy_image.alpha_mode = 'CHANNEL_PACKED'
    bpy_image.pack()

    image_cache[cache_key] = bpy_image
    return bpy_image


def _apply_blend(nodes, links, last_out, cur_color, cur_alpha, blend_mode, blend_factor, is_color):
    """Apply a layer blend operation."""
    if blend_mode in (LayerBlendMode.NONE, LayerBlendMode.PASS):
        return last_out

    BLEND_OPS = {
        LayerBlendMode.MULTIPLY: 'MULTIPLY',
        LayerBlendMode.ADD: 'ADD',
        LayerBlendMode.SUBTRACT: 'SUBTRACT',
        LayerBlendMode.MIX: 'MIX',
        LayerBlendMode.ALPHA_MASK: 'MIX',
        LayerBlendMode.RGB_MASK: 'MIX',
        LayerBlendMode.REPLACE: 'ADD',
    }

    op = BLEND_OPS.get(blend_mode)
    if op is None:
        return last_out

    if is_color:
        mix = nodes.new('ShaderNodeMixRGB')
        mix.blend_type = op
        mix.inputs[0].default_value = 1

        if blend_mode == LayerBlendMode.REPLACE:
            links.new(cur_color, mix.inputs[1])
            mix.inputs[0].default_value = 0.0
        else:
            links.new(last_out, mix.inputs[1])
            links.new(cur_color, mix.inputs[2])

        if blend_mode == LayerBlendMode.ALPHA_MASK:
            links.new(cur_alpha, mix.inputs[0])
        elif blend_mode == LayerBlendMode.RGB_MASK:
            links.new(cur_color, mix.inputs[0])
        elif blend_mode == LayerBlendMode.MIX:
            mix.inputs[0].default_value = blend_factor

        return mix.outputs[0]
    else:
        mix = nodes.new('ShaderNodeMixRGB')
        mix.blend_type = op
        mix.inputs[0].default_value = 1

        if blend_mode == LayerBlendMode.REPLACE:
            links.new(cur_alpha, mix.inputs[1])
        else:
            links.new(last_out, mix.inputs[1])
            links.new(cur_alpha, mix.inputs[2])

        if blend_mode == LayerBlendMode.ALPHA_MASK:
            links.new(cur_alpha, mix.inputs[0])
        elif blend_mode == LayerBlendMode.MIX:
            mix.inputs[0].default_value = blend_factor

        return mix.outputs[0]


def _build_tev_stage(nodes, links, stage, cur_color, cur_alpha, is_color):
    """Build TEV combiner stage as shader nodes."""
    inputs = []
    for ci in [stage.input_a, stage.input_b, stage.input_c, stage.input_d]:
        inp = _build_tev_input(nodes, ci, cur_color, cur_alpha, is_color)
        inputs.append(inp)

    # Compute: lerp(A, B, C) op D
    # lerp(A, B, C) = A * (1 - C) + B * C
    if stage.operation in (CombinerOp.ADD, CombinerOp.SUBTRACT):
        last = _build_tev_add_sub(nodes, links, inputs, stage, is_color)

        # Bias
        if stage.bias != CombinerBias.ZERO:
            bias_val = 0.5 if stage.bias == CombinerBias.PLUS_HALF else -0.5
            if is_color:
                bias = nodes.new('ShaderNodeMixRGB')
                bias.inputs[0].default_value = 1
                bias.blend_type = 'ADD' if bias_val > 0 else 'SUBTRACT'
                links.new(last, bias.inputs[1])
                bias.inputs[2].default_value = [abs(bias_val)] * 4
                last = bias.outputs[0]
            else:
                bias = nodes.new('ShaderNodeMath')
                bias.operation = 'ADD'
                links.new(last, bias.inputs[0])
                bias.inputs[1].default_value = bias_val
                last = bias.outputs[0]

        # Scale + clamp
        scale_val = {'1': 1, '2': 2, '4': 4, '0.5': 0.5}.get(stage.scale.value, 1)
        if is_color:
            scale = nodes.new('ShaderNodeMixRGB')
            scale.blend_type = 'MULTIPLY'
            scale.inputs[0].default_value = 1
            if stage.clamp:
                scale.use_clamp = True
            links.new(last, scale.inputs[1])
            scale.inputs[2].default_value = [scale_val] * 4
            last = scale.outputs[0]
        else:
            scale = nodes.new('ShaderNodeMath')
            scale.operation = 'MULTIPLY'
            if stage.clamp:
                scale.use_clamp = True
            links.new(last, scale.inputs[0])
            scale.inputs[1].default_value = scale_val
            last = scale.outputs[0]
        return last
    else:
        # Comparison ops — stub, return input A
        return inputs[0]


def _build_tev_input(nodes, combiner_input, cur_color, cur_alpha, is_color):
    """Create a shader node output for a TEV combiner input."""
    src = combiner_input.source

    if src == CombinerInputSource.TEXTURE_COLOR:
        return cur_color
    elif src == CombinerInputSource.TEXTURE_ALPHA:
        return cur_alpha
    elif src in (CombinerInputSource.CONSTANT, CombinerInputSource.REGISTER_0, CombinerInputSource.REGISTER_1):
        val = combiner_input.value or (0, 0, 0, 1)
        ch = combiner_input.channel
        if is_color:
            color = nodes.new('ShaderNodeRGB')
            if ch == "RGB":
                color.outputs[0].default_value[:] = list(val)
            elif ch == "RRR":
                color.outputs[0].default_value[:] = [val[0], val[0], val[0], val[3]]
            elif ch == "GGG":
                color.outputs[0].default_value[:] = [val[1], val[1], val[1], val[3]]
            elif ch == "BBB":
                color.outputs[0].default_value[:] = [val[2], val[2], val[2], val[3]]
            elif ch == "AAA":
                color.outputs[0].default_value[:] = [val[3], val[3], val[3], val[3]]
            else:
                color.outputs[0].default_value[:] = list(val)
            return color.outputs[0]
        else:
            alpha = nodes.new('ShaderNodeValue')
            if ch == "A":
                alpha.outputs[0].default_value = val[3]
            elif ch == "R":
                alpha.outputs[0].default_value = val[0]
            elif ch == "G":
                alpha.outputs[0].default_value = val[1]
            elif ch == "B":
                alpha.outputs[0].default_value = val[2]
            else:
                alpha.outputs[0].default_value = val[3]
            return alpha.outputs[0]

    # ZERO, ONE, HALF
    if is_color:
        color = nodes.new('ShaderNodeRGB')
        if src == CombinerInputSource.ZERO:
            color.outputs[0].default_value[:] = [0, 0, 0, 1]
        elif src == CombinerInputSource.ONE:
            color.outputs[0].default_value[:] = [1, 1, 1, 1]
        elif src == CombinerInputSource.HALF:
            color.outputs[0].default_value[:] = [0.5, 0.5, 0.5, 1]
        return color.outputs[0]
    else:
        alpha = nodes.new('ShaderNodeValue')
        if src == CombinerInputSource.ZERO:
            alpha.outputs[0].default_value = 0.0
        elif src == CombinerInputSource.ONE:
            alpha.outputs[0].default_value = 1.0
        elif src == CombinerInputSource.HALF:
            alpha.outputs[0].default_value = 0.5
        return alpha.outputs[0]


def _build_tev_add_sub(nodes, links, inputs, stage, is_color):
    """Build TEV add/subtract: lerp(A, B, C) ± D."""
    is_sub = (stage.operation == CombinerOp.SUBTRACT)

    if is_color:
        # (1-C)
        sub0 = nodes.new('ShaderNodeMixRGB')
        sub0.inputs[0].default_value = 1
        sub0.blend_type = 'SUBTRACT'
        sub0.inputs[1].default_value = [1, 1, 1, 1]
        links.new(inputs[2], sub0.inputs[2])

        # B * C
        mul0 = nodes.new('ShaderNodeMixRGB')
        mul0.inputs[0].default_value = 1
        mul0.blend_type = 'MULTIPLY'
        links.new(inputs[1], mul0.inputs[1])
        links.new(inputs[2], mul0.inputs[2])

        # A * (1-C)
        mul1 = nodes.new('ShaderNodeMixRGB')
        mul1.inputs[0].default_value = 1
        mul1.blend_type = 'MULTIPLY'
        links.new(inputs[0], mul1.inputs[1])
        links.new(sub0.outputs[0], mul1.inputs[2])

        # A*(1-C) + B*C
        add0 = nodes.new('ShaderNodeMixRGB')
        add0.inputs[0].default_value = 1
        add0.blend_type = 'ADD'
        links.new(mul1.outputs[0], add0.inputs[1])
        links.new(mul0.outputs[0], add0.inputs[2])

        # ± D
        final = nodes.new('ShaderNodeMixRGB')
        final.inputs[0].default_value = 1
        final.blend_type = 'SUBTRACT' if is_sub else 'ADD'
        links.new(inputs[3], final.inputs[1])
        links.new(add0.outputs[0], final.inputs[2])
        return final.outputs[0]
    else:
        sub0 = nodes.new('ShaderNodeMath')
        sub0.operation = 'SUBTRACT'
        sub0.inputs[1].default_value = 1.0
        links.new(inputs[2], sub0.inputs[2])

        mul0 = nodes.new('ShaderNodeMath')
        mul0.operation = 'MULTIPLY'
        links.new(inputs[1], mul0.inputs[1])
        links.new(inputs[2], mul0.inputs[2])

        mul1 = nodes.new('ShaderNodeMath')
        mul1.operation = 'MULTIPLY'
        links.new(inputs[0], mul1.inputs[1])
        links.new(sub0.outputs[0], mul1.inputs[2])

        add0 = nodes.new('ShaderNodeMath')
        add0.operation = 'ADD'
        links.new(mul1.outputs[0], add0.inputs[1])
        links.new(mul0.outputs[0], add0.inputs[2])

        final = nodes.new('ShaderNodeMath')
        final.operation = 'SUBTRACT' if is_sub else 'ADD'
        links.new(inputs[3], final.inputs[1])
        links.new(add0.outputs[0], final.inputs[2])
        return final.outputs[0]


def _build_pixel_engine(ir_mat, nodes, links, last_color, last_alpha, mat):
    """Apply pixel engine / fragment blending effects."""
    transparent_shader = False
    alt_blend_mode = 'NOTHING'

    fb = ir_mat.fragment_blending
    if fb is None:
        if ir_mat.is_translucent:
            transparent_shader = True
            mat.blend_method = 'BLEND'
        return last_color, last_alpha, transparent_shader, alt_blend_mode

    effect = fb.effect
    sf, df = fb.source_factor, fb.dest_factor

    if effect == OutputBlendEffect.OPAQUE:
        pass

    elif effect == OutputBlendEffect.ALPHA_BLEND:
        transparent_shader = True
        mat.blend_method = 'HASHED'

    elif effect == OutputBlendEffect.INVERSE_ALPHA_BLEND:
        transparent_shader = True
        mat.blend_method = 'HASHED'
        factor = nodes.new('ShaderNodeMath')
        factor.operation = 'SUBTRACT'
        factor.inputs[0].default_value = 1
        factor.use_clamp = True
        links.new(last_alpha, factor.inputs[1])
        last_alpha = factor.outputs[0]

    elif effect == OutputBlendEffect.ADDITIVE:
        alt_blend_mode = 'ADD'

    elif effect == OutputBlendEffect.ADDITIVE_ALPHA:
        transparent_shader = True
        alt_blend_mode = 'ADD'
        blend = nodes.new('ShaderNodeMixRGB')
        links.new(last_alpha, blend.inputs[0])
        blend.inputs[1].default_value = [0, 0, 0, 0xFF]
        links.new(last_color, blend.inputs[2])
        last_color = blend.outputs[0]

    elif effect == OutputBlendEffect.ADDITIVE_INV_ALPHA:
        transparent_shader = True
        alt_blend_mode = 'ADD'
        blend = nodes.new('ShaderNodeMixRGB')
        links.new(last_alpha, blend.inputs[0])
        blend.inputs[2].default_value = [0, 0, 0, 0xFF]
        links.new(last_color, blend.inputs[1])
        last_color = blend.outputs[0]

    elif effect == OutputBlendEffect.MULTIPLY:
        alt_blend_mode = 'MULTIPLY'

    elif effect == OutputBlendEffect.SRC_ALPHA_ONLY:
        blend = nodes.new('ShaderNodeMixRGB')
        links.new(last_alpha, blend.inputs[0])
        blend.inputs[1].default_value = [0, 0, 0, 0xFF]
        links.new(last_color, blend.inputs[2])
        last_color = blend.outputs[0]

    elif effect == OutputBlendEffect.INV_SRC_ALPHA_ONLY:
        blend = nodes.new('ShaderNodeMixRGB')
        links.new(last_alpha, blend.inputs[0])
        blend.inputs[2].default_value = [0, 0, 0, 0xFF]
        links.new(last_color, blend.inputs[1])
        last_color = blend.outputs[0]

    elif effect == OutputBlendEffect.INVISIBLE:
        transparent_shader = True
        mat.blend_method = 'HASHED'
        invisible = nodes.new('ShaderNodeValue')
        invisible.outputs[0].default_value = 0
        last_alpha = invisible.outputs[0]

    elif effect == OutputBlendEffect.BLACK:
        black = nodes.new('ShaderNodeRGB')
        black.outputs[0].default_value[:] = [0, 0, 0, 1]
        last_color = black.outputs[0]

    elif effect == OutputBlendEffect.WHITE:
        white = nodes.new('ShaderNodeRGB')
        white.outputs[0].default_value[:] = [1, 1, 1, 1]
        last_color = white.outputs[0]

    elif effect == OutputBlendEffect.INVERT:
        invert = nodes.new('ShaderNodeInvert')
        links.new(last_color, invert.inputs[1])
        last_color = invert.outputs[0]

    elif effect == OutputBlendEffect.CUSTOM:
        # Best-effort for custom blend modes
        if df == BlendFactor.ZERO:
            if sf == BlendFactor.SRC_ALPHA:
                blend = nodes.new('ShaderNodeMixRGB')
                links.new(last_alpha, blend.inputs[0])
                blend.inputs[1].default_value = [0, 0, 0, 0xFF]
                links.new(last_color, blend.inputs[2])
                last_color = blend.outputs[0]
            elif sf == BlendFactor.INV_SRC_ALPHA:
                blend = nodes.new('ShaderNodeMixRGB')
                links.new(last_alpha, blend.inputs[0])
                blend.inputs[2].default_value = [0, 0, 0, 0xFF]
                links.new(last_color, blend.inputs[1])
                last_color = blend.outputs[0]

    return last_color, last_alpha, transparent_shader, alt_blend_mode


def _build_output_shader(ir_mat, nodes, links, last_color, last_alpha, bump_map,
                         transparent_shader, alt_blend_mode, mat):
    """Build the final output shader (Principled BSDF + emission for unlit)."""
    shader = nodes.new('ShaderNodeBsdfPrincipled')

    spec_name = "Specular IOR Level" if bpy.app.version >= BlenderVersion(4, 0, 0) else "Specular"
    if ir_mat.enable_specular:
        shader.inputs[spec_name].default_value = ir_mat.shininess / 50
    else:
        shader.inputs[spec_name].default_value = 0

    if bpy.app.version >= BlenderVersion(4, 0, 0):
        shader.inputs["Specular Tint"].default_value = (0.5, 0.5, 0.5, 1.0)
    else:
        shader.inputs["Specular Tint"].default_value = 0.5
    shader.inputs['Roughness'].default_value = 0.5

    if ir_mat.lighting == LightingModel.LIT:
        links.new(last_color, shader.inputs['Base Color'])
        if transparent_shader:
            links.new(last_alpha, shader.inputs['Alpha'])
    else:
        # Unlit: use emission for flat appearance
        shader.inputs['Base Color'].default_value = [0, 0, 0, 1]
        emission = nodes.new('ShaderNodeEmission')
        links.new(last_color, emission.inputs['Color'])
        diffuse = emission

        if transparent_shader:
            mixshader = nodes.new('ShaderNodeMixShader')
            transparent_sh = nodes.new('ShaderNodeBsdfTransparent')
            links.new(last_alpha, mixshader.inputs[0])
            links.new(transparent_sh.outputs[0], mixshader.inputs[1])
            links.new(diffuse.outputs[0], mixshader.inputs[2])
            diffuse = mixshader

        addshader = nodes.new('ShaderNodeAddShader')
        links.new(diffuse.outputs[0], addshader.inputs[0])
        links.new(shader.outputs[0], addshader.inputs[1])
        shader = addshader

    if bump_map:
        bump = nodes.new('ShaderNodeBump')
        bump.inputs[1].default_value = 1
        links.new(bump_map, bump.inputs[2])
        links.new(bump.outputs[0], shader.inputs['Normal'])

    if alt_blend_mode == 'ADD':
        mat.blend_method = 'BLEND'
        e = nodes.new('ShaderNodeEmission')
        e.inputs[1].default_value = 1.9
        t = nodes.new('ShaderNodeBsdfTransparent')
        add = nodes.new('ShaderNodeAddShader')
        links.new(last_color, e.inputs[0])
        links.new(e.outputs[0], add.inputs[0])
        links.new(t.outputs[0], add.inputs[1])
        shader = add
    elif alt_blend_mode == 'MULTIPLY':
        mat.blend_method = 'BLEND'
        t = nodes.new('ShaderNodeBsdfTransparent')
        links.new(last_color, t.inputs[0])
        shader = t

    return shader
