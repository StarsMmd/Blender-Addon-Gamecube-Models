"""IR materials → BR materials conversion.

Pure — no bpy. Every TEV stage, per-axis wrap, pixel-engine effect, and
output-shader wiring gets turned into a ``BRNodeGraph`` spec that the
build phase can replay mechanically. The shader-graph decisions
(previously scattered across ~900 lines of ``build_material``) live here
so they can be unit-tested against synthetic IR inputs.

Node naming preserved for downstream consumers:
  - ``DiffuseColor`` / ``AlphaValue`` — bound by material-animation fcurves.
  - ``dat_ambient_emission`` / ``dat_ambient_add`` — read by the exporter.
  - ``TexMapping_N`` / ``wrap_*`` — pattern-matched by UV-animation and
    wrap-mode export logic.
"""
import math

try:
    from .....shared.BR.materials import (
        BRMaterial, BRNodeGraph, BRNode, BRLink, BRImage,
    )
    from .....shared.IR.enums import (
        ColorSource, LightingModel, CoordType, WrapMode, TextureInterpolation,
        LayerBlendMode, LightmapChannel, CombinerInputSource, CombinerOp,
        CombinerBias, CombinerScale, OutputBlendEffect, BlendFactor,
    )
    from .....shared.helpers.srgb import srgb_to_linear
except (ImportError, SystemError):
    from shared.BR.materials import (
        BRMaterial, BRNodeGraph, BRNode, BRLink, BRImage,
    )
    from shared.IR.enums import (
        ColorSource, LightingModel, CoordType, WrapMode, TextureInterpolation,
        LayerBlendMode, LightmapChannel, CombinerInputSource, CombinerOp,
        CombinerBias, CombinerScale, OutputBlendEffect, BlendFactor,
    )
    from shared.helpers.srgb import srgb_to_linear


# ---------------------------------------------------------------------------
# Graph builder — mutable helper that accumulates nodes + links during
# planning. Node names are auto-generated unless explicitly provided; the
# builder returns the generated name so callers can target links.
# ---------------------------------------------------------------------------


class BRGraphBuilder:
    def __init__(self):
        """Initialise an empty graph with auto-generated-name counter at 0.

        In: (self).
        Out: None.
        """
        self._nodes = []
        self._links = []
        self._counter = 0

    def add_node(self, node_type, name=None, properties=None,
                 input_defaults=None, image_ref=None, location=None):
        """Append a new BRNode to the graph and return its name.

        In: node_type (str, bl_idname); name (str|None, auto-gen '_nN' if None);
            properties (dict|None); input_defaults (dict|None);
            image_ref (BRImage|None, only for ShaderNodeTexImage);
            location (tuple[float, float]|None, editor canvas coords).
        Out: str, the resolved node name for use in add_link targets.
        """
        if name is None:
            name = '_n%d' % self._counter
            self._counter += 1
        self._nodes.append(BRNode(
            node_type=node_type,
            name=name,
            properties=dict(properties) if properties else {},
            input_defaults=dict(input_defaults) if input_defaults else {},
            image_ref=image_ref,
            location=location,
        ))
        return name

    def add_link(self, from_node, from_output, to_node, to_input):
        """Record a socket-to-socket link between two already-added nodes.

        In: from_node (str, BRNode name); from_output (int|str, socket key);
            to_node (str, BRNode name); to_input (int|str, socket key).
        Out: None.
        """
        self._links.append(BRLink(
            from_node=from_node,
            from_output=from_output,
            to_node=to_node,
            to_input=to_input,
        ))

    def set_input_default(self, node_name, socket_key, value):
        """Set an input socket's default_value on an already-added node.

        In: node_name (str, must match an added BRNode.name);
            socket_key (int|str); value (object).
        Out: None. Raises KeyError if node_name isn't found.
        """
        for n in self._nodes:
            if n.name == node_name:
                n.input_defaults[socket_key] = value
                return
        raise KeyError("node %r not found" % node_name)

    def set_property(self, node_name, key, value):
        """Set a type-specific attribute (applied via setattr at build time).

        In: node_name (str); key (str, bpy attribute name); value (object).
        Out: None. Raises KeyError if node_name isn't found.
        """
        for n in self._nodes:
            if n.name == node_name:
                n.properties[key] = value
                return
        raise KeyError("node %r not found" % node_name)

    def finalize(self):
        """Snapshot accumulated nodes+links into an immutable BRNodeGraph.

        In: (self only).
        Out: BRNodeGraph with defensive copies of nodes and links lists.
        """
        return BRNodeGraph(nodes=list(self._nodes), links=list(self._links))


def _linearize_rgb(rgba):
    """Convert IR-side sRGB to linear for Blender shader defaults (alpha untouched).

    In: rgba (tuple[float, float, float, float], sRGB [0, 1]).
    Out: tuple[float, float, float, float] — linear RGB + unchanged alpha.
    """
    return (
        srgb_to_linear(rgba[0]),
        srgb_to_linear(rgba[1]),
        srgb_to_linear(rgba[2]),
        rgba[3],
    )


# ---------------------------------------------------------------------------
# Top-level: plan_material
# ---------------------------------------------------------------------------


def plan_material(ir_material, name, has_color_animation=False,
                  cull_front=False, cull_back=False, dedup_key=None):
    """Build a BRMaterial spec from IRMaterial.

    In: ir_material (IRMaterial); name (str, Blender material name);
        has_color_animation (bool, force DiffuseColor RGB node);
        cull_front (bool); cull_back (bool);
        dedup_key (object|None, identity for bpy-material sharing).
    Out: BRMaterial with a fully baked BRNodeGraph, blend_method, and
         use_backface_culling set.
    """
    g = BRGraphBuilder()

    output = g.add_node('ShaderNodeOutputMaterial', name='Material Output')

    color_ref, alpha_ref = _plan_base_color_alpha(
        g, ir_material, has_color_animation=has_color_animation,
    )

    bump_ref = None
    for tex_idx, tex_layer in enumerate(ir_material.texture_layers):
        cur_color, cur_alpha, _uv_ref = _plan_texture_sampling(g, tex_layer, tex_idx)

        if tex_layer.combiner:
            if tex_layer.combiner.color:
                cur_color = _plan_tev_stage(g, tex_layer.combiner.color,
                                            cur_color, cur_alpha, is_color=True)
            if tex_layer.combiner.alpha:
                cur_alpha = _plan_tev_stage(g, tex_layer.combiner.alpha,
                                            cur_color, cur_alpha, is_color=False)

        if tex_layer.is_bump:
            if bump_ref is not None:
                mix = g.add_node('ShaderNodeMixRGB',
                                 properties={'blend_type': 'MIX'},
                                 input_defaults={0: tex_layer.blend_factor})
                g.add_link(bump_ref[0], bump_ref[1], mix, 1)
                g.add_link(cur_color[0], cur_color[1], mix, 2)
                bump_ref = (mix, 0)
            else:
                bump_ref = cur_color
        else:
            lmc = tex_layer.lightmap_channel
            if lmc in (LightmapChannel.NONE, LightmapChannel.DIFFUSE,
                       LightmapChannel.AMBIENT, LightmapChannel.EXTENSION):
                color_ref = _plan_apply_blend(
                    g, color_ref, cur_color, cur_alpha,
                    tex_layer.color_blend, tex_layer.blend_factor, is_color=True,
                )
                alpha_ref = _plan_apply_blend(
                    g, alpha_ref, cur_alpha, cur_alpha,
                    tex_layer.alpha_blend, tex_layer.blend_factor, is_color=False,
                )

    # Post-texture vertex-color multiply for lit materials.
    if ir_material.lighting == LightingModel.LIT:
        if ir_material.color_source in (ColorSource.VERTEX, ColorSource.BOTH):
            color_ref = _plan_vertex_color_mult(g, color_ref, 'color_0')
        if ir_material.alpha_source in (ColorSource.VERTEX, ColorSource.BOTH):
            alpha_ref = _plan_vertex_color_mult(g, alpha_ref, 'alpha_0')

    # Pixel engine / fragment blending.
    color_ref, alpha_ref, transparent_shader, alt_blend_mode, blend_method = \
        _plan_pixel_engine(g, ir_material, color_ref, alpha_ref)

    # Output shader wiring.
    shader_ref, blend_method = _plan_output_shader(
        g, ir_material, color_ref, alpha_ref, bump_ref,
        transparent_shader, alt_blend_mode, blend_method,
    )

    # Ambient — hidden emission node for round-trip export + add-shader wiring.
    shader_ref = _plan_ambient_emission(g, ir_material, shader_ref)

    # Connect final shader to Material Output.
    g.add_link(shader_ref[0], shader_ref[1], output, 0)

    _plan_auto_layout(g)

    return BRMaterial(
        name=name,
        node_graph=g.finalize(),
        use_backface_culling=bool(cull_front or cull_back),
        blend_method=blend_method,
        dedup_key=dedup_key,
    )


# ---------------------------------------------------------------------------
# Base color + alpha
# ---------------------------------------------------------------------------


def _plan_base_color_alpha(g, ir_mat, has_color_animation):
    """Emit the base-color + alpha nodes and return their output refs.

    In: g (BRGraphBuilder, mutated); ir_mat (IRMaterial);
        has_color_animation (bool, force DiffuseColor node for unlit materials).
    Out: ((str, int|str), (str, int|str)) — (color_ref, alpha_ref) socket refs
         that subsequent stages chain from.
    """
    dc = _linearize_rgb(ir_mat.diffuse_color)

    if ir_mat.lighting == LightingModel.LIT:
        # ShaderNodeRGB / ShaderNodeValue don't have input sockets —
        # their constant lives on outputs[0].default_value. Build walker
        # reads the ``_output_default`` property and applies it there.
        color = g.add_node('ShaderNodeRGB', name='DiffuseColor')
        if ir_mat.color_source == ColorSource.VERTEX:
            g.set_property(color, '_output_default', [1.0, 1.0, 1.0, 1.0])
        else:
            g.set_property(color, '_output_default', list(dc))

        alpha = g.add_node('ShaderNodeValue', name='AlphaValue')
        if ir_mat.alpha_source == ColorSource.VERTEX:
            g.set_property(alpha, '_output_default', 1.0)
        else:
            g.set_property(alpha, '_output_default', float(ir_mat.alpha))

        return (color, 0), (alpha, 0)

    # Unlit: vertex color is the base.
    color_ref = _plan_unlit_base_color(g, ir_mat, dc, has_color_animation)
    alpha_ref = _plan_unlit_base_alpha(g, ir_mat)
    return color_ref, alpha_ref


def _plan_unlit_base_color(g, ir_mat, dc, has_color_animation):
    """Unlit-path base color — material-only, vertex-only, or combined.

    In: g (BRGraphBuilder, mutated); ir_mat (IRMaterial);
        dc (tuple[float, float, float, float], linearised diffuse);
        has_color_animation (bool).
    Out: (str, int|str) — output socket ref feeding the rest of the color chain.
    """
    if ir_mat.color_source == ColorSource.MATERIAL or has_color_animation:
        color = g.add_node('ShaderNodeRGB', name='DiffuseColor')
        g.set_property(color, '_output_default', list(dc))
        if ir_mat.color_source != ColorSource.MATERIAL:
            vtx = g.add_node('ShaderNodeAttribute',
                             properties={'attribute_name': 'color_0'})
            mix = g.add_node('ShaderNodeMixRGB',
                             properties={'blend_type': 'MULTIPLY'},
                             input_defaults={0: 1.0})
            g.add_link(vtx, 0, mix, 1)
            g.add_link(color, 0, mix, 2)
            return (mix, 0)
        return (color, 0)

    color = g.add_node('ShaderNodeAttribute',
                       properties={'attribute_name': 'color_0'})
    if ir_mat.color_source == ColorSource.BOTH:
        diff = g.add_node('ShaderNodeRGB', name='DiffuseColor')
        g.set_property(diff, '_output_default', list(dc))
        mix = g.add_node('ShaderNodeMixRGB',
                         properties={'blend_type': 'ADD'},
                         input_defaults={0: 1.0})
        g.add_link(color, 0, mix, 1)
        g.add_link(diff, 0, mix, 2)
        return (mix, 0)
    return (color, 0)


def _plan_unlit_base_alpha(g, ir_mat):
    """Unlit-path alpha — material-only, vertex-only, or multiplied combination.

    In: g (BRGraphBuilder, mutated); ir_mat (IRMaterial).
    Out: (str, int|str) — output socket ref feeding the alpha chain.
    """
    if ir_mat.alpha_source == ColorSource.MATERIAL:
        alpha = g.add_node('ShaderNodeValue', name='AlphaValue')
        g.set_property(alpha, '_output_default', float(ir_mat.alpha))
        return (alpha, 0)

    alpha = g.add_node('ShaderNodeAttribute',
                       properties={'attribute_name': 'alpha_0'})
    if ir_mat.alpha_source == ColorSource.BOTH:
        mat_alpha = g.add_node('ShaderNodeValue', name='AlphaValue')
        g.set_property(mat_alpha, '_output_default', float(ir_mat.alpha))
        mix = g.add_node('ShaderNodeMath',
                         properties={'operation': 'MULTIPLY'})
        g.add_link(alpha, 0, mix, 0)
        g.add_link(mat_alpha, 0, mix, 1)
        return (mix, 0)
    return (alpha, 0)


def _plan_vertex_color_mult(g, prev_ref, attribute_name):
    """Multiply the current color/alpha chain by a named vertex attribute.

    In: g (BRGraphBuilder, mutated); prev_ref ((str, int|str), upstream socket);
        attribute_name (str, e.g. 'color_0' or 'alpha_0').
    Out: (str, int|str) — MixRGB MULTIPLY output socket.
    """
    vtx = g.add_node('ShaderNodeAttribute',
                     properties={'attribute_name': attribute_name})
    mult = g.add_node('ShaderNodeMixRGB',
                      properties={'blend_type': 'MULTIPLY'},
                      input_defaults={0: 1.0})
    g.add_link(vtx, 0, mult, 1)
    g.add_link(prev_ref[0], prev_ref[1], mult, 2)
    return (mult, 0)


# ---------------------------------------------------------------------------
# Texture sampling
# ---------------------------------------------------------------------------


def _plan_texture_sampling(g, tex_layer, tex_idx):
    """Emit the UV → Mapping → (optional wrap chain) → Image Texture pipeline.

    In: g (BRGraphBuilder, mutated); tex_layer (IRTextureLayer); tex_idx (int).
    Out: ((str, int), (str, int), (str, int|str)|None) —
         (tex_color_ref, tex_alpha_ref, uv_source_ref).
    """
    uv_ref = None
    if tex_layer.coord_type == CoordType.UV:
        uv = g.add_node('ShaderNodeUVMap',
                        properties={'uv_map': 'uvtex_%d' % tex_layer.uv_index})
        uv_ref = (uv, 0)
    elif tex_layer.coord_type == CoordType.REFLECTION:
        uv = g.add_node('ShaderNodeTexCoord')
        uv_ref = (uv, 6)

    mapping_name = 'TexMapping_%d' % tex_idx
    rotation = list(tex_layer.rotation) if hasattr(tex_layer.rotation, '__iter__') else tex_layer.rotation
    # Blender's Mapping rotation input takes a Vector; IR may carry scalar or tuple.
    rot_value = list(rotation) if isinstance(rotation, (list, tuple)) else [0.0, 0.0, rotation]

    mapping_props = {'vector_type': 'TEXTURE'}
    mapping_defaults = {
        1: list(tex_layer.translation),
        2: list(rot_value),
        3: list(tex_layer.scale),
    }
    if tex_layer.coord_type == CoordType.REFLECTION:
        # Mirror the original behaviour: subtract π/2 from X rotation for reflection maps.
        adjusted = list(rot_value)
        adjusted[0] = adjusted[0] - math.pi / 2
        mapping_defaults[2] = adjusted
    mapping = g.add_node('ShaderNodeMapping', name=mapping_name,
                         properties=mapping_props,
                         input_defaults=mapping_defaults)

    if uv_ref and (tex_layer.repeat_s > 1 or tex_layer.repeat_t > 1):
        multiply = g.add_node(
            'ShaderNodeVectorMath',
            properties={'operation': 'MULTIPLY'},
            input_defaults={1: (
                tex_layer.repeat_s if tex_layer.repeat_s > 1 else 1,
                tex_layer.repeat_t if tex_layer.repeat_t > 1 else 1,
                1,
            )},
        )
        g.add_link(uv_ref[0], uv_ref[1], multiply, 0)
        g.add_link(multiply, 0, mapping, 0)
    elif uv_ref:
        g.add_link(uv_ref[0], uv_ref[1], mapping, 0)

    # Image texture.
    image_ref = _to_br_image(tex_layer.image)
    tex_properties = {}
    ws, wt = tex_layer.wrap_s, tex_layer.wrap_t
    needs_math = (ws != wt) or ws == WrapMode.MIRROR or wt == WrapMode.MIRROR
    if needs_math:
        tex_properties['extension'] = 'EXTEND'
    elif ws == WrapMode.REPEAT:
        tex_properties['extension'] = 'REPEAT'
    else:
        tex_properties['extension'] = 'EXTEND'

    if tex_layer.interpolation:
        tex_properties['interpolation'] = tex_layer.interpolation.value

    tex_node = g.add_node('ShaderNodeTexImage',
                          properties=tex_properties,
                          image_ref=image_ref)

    if needs_math:
        wrap_output = _plan_per_axis_wrap(g, mapping, tex_idx, ws, wt)
        g.add_link(wrap_output[0], wrap_output[1], tex_node, 0)
    else:
        g.add_link(mapping, 0, tex_node, 0)

    return (tex_node, 0), (tex_node, 1), uv_ref


def _plan_per_axis_wrap(g, mapping_name, tex_idx, wrap_s, wrap_t):
    """Separate → per-axis op → Combine chain. Exporter pattern-matches
    against this to recover wrap mode per axis.

    In: g (BRGraphBuilder, mutated); mapping_name (str, upstream ShaderNodeMapping name);
        tex_idx (int, for node naming); wrap_s/wrap_t (WrapMode enum).
    Out: (str, int) — CombineXYZ output socket feeding the texture node.
    """
    sep = g.add_node('ShaderNodeSeparateXYZ', name='wrap_sep_%d' % tex_idx)
    g.add_link(mapping_name, 0, sep, 0)

    s_out = _plan_wrap_axis(g, sep, 0, wrap_s, 's', tex_idx)
    t_out = _plan_wrap_axis(g, sep, 1, wrap_t, 't', tex_idx)

    comb = g.add_node('ShaderNodeCombineXYZ', name='wrap_comb_%d' % tex_idx)
    g.add_link(s_out[0], s_out[1], comb, 0)
    g.add_link(t_out[0], t_out[1], comb, 1)
    g.add_link(sep, 2, comb, 2)
    return (comb, 0)


def _plan_wrap_axis(g, sep_name, axis_idx, wrap, axis_label, tex_idx):
    """Emit the per-axis wrap op matching a single GX WrapMode.

    MIRROR → PINGPONG; REPEAT → FRACT; CLAMP → Max(Min(u, 1), 0) chain.

    In: g (BRGraphBuilder, mutated); sep_name (str, SeparateXYZ node name);
        axis_idx (int, 0 or 1); wrap (WrapMode); axis_label (str, 's' or 't');
        tex_idx (int, for node naming).
    Out: (str, int) — final op's output socket for the axis.
    """
    if wrap == WrapMode.MIRROR:
        n = g.add_node('ShaderNodeMath',
                       name='wrap_pp_%s_%d' % (axis_label, tex_idx),
                       properties={'operation': 'PINGPONG'},
                       input_defaults={1: 1.0})
        g.add_link(sep_name, axis_idx, n, 0)
        return (n, 0)
    if wrap == WrapMode.REPEAT:
        n = g.add_node('ShaderNodeMath',
                       name='wrap_fract_%s_%d' % (axis_label, tex_idx),
                       properties={'operation': 'FRACT'})
        g.add_link(sep_name, axis_idx, n, 0)
        return (n, 0)
    # CLAMP — Max(Min(u, 1), 0).
    max0 = g.add_node('ShaderNodeMath',
                      name='wrap_clamp_max_%s_%d' % (axis_label, tex_idx),
                      properties={'operation': 'MAXIMUM'},
                      input_defaults={1: 0.0})
    g.add_link(sep_name, axis_idx, max0, 0)
    min1 = g.add_node('ShaderNodeMath',
                      name='wrap_clamp_min_%s_%d' % (axis_label, tex_idx),
                      properties={'operation': 'MINIMUM'},
                      input_defaults={1: 1.0})
    g.add_link(max0, 0, min1, 0)
    return (min1, 0)


def _to_br_image(ir_image):
    """Convert IRImage → BRImage (or pass None through).

    In: ir_image (IRImage|None).
    Out: BRImage|None. cache_key is (image_id, palette_id).
    """
    if ir_image is None:
        return None
    return BRImage(
        name=ir_image.name,
        width=ir_image.width,
        height=ir_image.height,
        pixels=ir_image.pixels,
        cache_key=(ir_image.image_id, ir_image.palette_id),
        gx_format_override=(ir_image.gx_format_override.value
                            if ir_image.gx_format_override else None),
    )


# ---------------------------------------------------------------------------
# Layer blending
# ---------------------------------------------------------------------------


_LAYER_BLEND_OPS = {
    LayerBlendMode.MULTIPLY: 'MULTIPLY',
    LayerBlendMode.ADD: 'ADD',
    LayerBlendMode.SUBTRACT: 'SUBTRACT',
    LayerBlendMode.MIX: 'MIX',
    LayerBlendMode.ALPHA_MASK: 'MIX',
    LayerBlendMode.RGB_MASK: 'MIX',
    LayerBlendMode.REPLACE: 'ADD',
}


def _plan_apply_blend(g, last_ref, cur_color, cur_alpha, blend_mode, blend_factor, is_color):
    """Insert a MixRGB node applying one IR LayerBlendMode to the running chain.

    In: g (BRGraphBuilder, mutated); last_ref ((str, int|str), upstream chain output);
        cur_color ((str, int|str), current texture color output);
        cur_alpha ((str, int|str), current texture alpha output);
        blend_mode (LayerBlendMode); blend_factor (float);
        is_color (bool, True for color chain, False for alpha chain).
    Out: (str, int|str) — output ref of the inserted mix node, or the original
         last_ref unchanged for NONE/PASS/unknown modes.
    """
    if blend_mode in (LayerBlendMode.NONE, LayerBlendMode.PASS):
        return last_ref

    op = _LAYER_BLEND_OPS.get(blend_mode)
    if op is None:
        return last_ref

    mix = g.add_node('ShaderNodeMixRGB',
                     properties={'blend_type': op},
                     input_defaults={0: 1.0})

    if is_color:
        if blend_mode == LayerBlendMode.REPLACE:
            g.add_link(cur_color[0], cur_color[1], mix, 1)
            g.set_input_default(mix, 0, 0.0)
        else:
            g.add_link(last_ref[0], last_ref[1], mix, 1)
            g.add_link(cur_color[0], cur_color[1], mix, 2)

        if blend_mode == LayerBlendMode.ALPHA_MASK:
            g.add_link(cur_alpha[0], cur_alpha[1], mix, 0)
        elif blend_mode == LayerBlendMode.RGB_MASK:
            g.add_link(cur_color[0], cur_color[1], mix, 0)
        elif blend_mode == LayerBlendMode.MIX:
            g.set_input_default(mix, 0, blend_factor)
    else:
        if blend_mode == LayerBlendMode.REPLACE:
            g.add_link(cur_alpha[0], cur_alpha[1], mix, 1)
        else:
            g.add_link(last_ref[0], last_ref[1], mix, 1)
            g.add_link(cur_alpha[0], cur_alpha[1], mix, 2)
        if blend_mode == LayerBlendMode.ALPHA_MASK:
            g.add_link(cur_alpha[0], cur_alpha[1], mix, 0)
        elif blend_mode == LayerBlendMode.MIX:
            g.set_input_default(mix, 0, blend_factor)

    return (mix, 0)


# ---------------------------------------------------------------------------
# TEV stages
# ---------------------------------------------------------------------------


def _plan_tev_stage(g, stage, cur_color, cur_alpha, is_color):
    """Emit one full TEV combiner stage (add/sub + bias + scale + clamp).

    In: g (BRGraphBuilder, mutated); stage (CombinerStage);
        cur_color/cur_alpha ((str, int|str), current chain sockets);
        is_color (bool, color vs alpha stage).
    Out: (str, int) — final scaled/clamped output socket. Comparison ops
         are stubbed to return input A unchanged.
    """
    inputs = [
        _plan_tev_input(g, ci, cur_color, cur_alpha, is_color)
        for ci in (stage.input_a, stage.input_b, stage.input_c, stage.input_d)
    ]

    if stage.operation not in (CombinerOp.ADD, CombinerOp.SUBTRACT):
        return inputs[0]  # comparison ops — stub, return A

    last = _plan_tev_add_sub(g, inputs, stage, is_color)

    # Bias
    if stage.bias != CombinerBias.ZERO:
        bias_val = 0.5 if stage.bias == CombinerBias.PLUS_HALF else -0.5
        if is_color:
            bias = g.add_node('ShaderNodeMixRGB',
                              properties={'blend_type': 'ADD' if bias_val > 0 else 'SUBTRACT'},
                              input_defaults={0: 1.0, 2: [abs(bias_val)] * 4})
            g.add_link(last[0], last[1], bias, 1)
            last = (bias, 0)
        else:
            bias = g.add_node('ShaderNodeMath',
                              properties={'operation': 'ADD'},
                              input_defaults={1: bias_val})
            g.add_link(last[0], last[1], bias, 0)
            last = (bias, 0)

    # Scale + clamp
    scale_val = {'1': 1, '2': 2, '4': 4, '0.5': 0.5}.get(stage.scale.value, 1)
    if is_color:
        scale_props = {'blend_type': 'MULTIPLY'}
        if stage.clamp:
            scale_props['use_clamp'] = True
        scale = g.add_node('ShaderNodeMixRGB',
                           properties=scale_props,
                           input_defaults={0: 1.0, 2: [scale_val] * 4})
        g.add_link(last[0], last[1], scale, 1)
        return (scale, 0)
    scale_props = {'operation': 'MULTIPLY'}
    if stage.clamp:
        scale_props['use_clamp'] = True
    scale = g.add_node('ShaderNodeMath',
                       properties=scale_props,
                       input_defaults={1: scale_val})
    g.add_link(last[0], last[1], scale, 0)
    return (scale, 0)


def _plan_tev_input(g, combiner_input, cur_color, cur_alpha, is_color):
    """Resolve one TEV combiner input to a shader socket reference.

    Returns the current texture output for TEXTURE_COLOR/TEXTURE_ALPHA;
    creates a new constant RGB/Value node for CONSTANT/REGISTER/ZERO/ONE/HALF
    sources honouring the GX channel selector (RGB/RRR/GGG/BBB/AAA).

    In: g (BRGraphBuilder, mutated); combiner_input (CombinerInput);
        cur_color/cur_alpha ((str, int|str)); is_color (bool).
    Out: (str, int|str) — socket ref usable as a link source.
    """
    src = combiner_input.source

    if src == CombinerInputSource.TEXTURE_COLOR:
        return cur_color
    if src == CombinerInputSource.TEXTURE_ALPHA:
        return cur_alpha

    if src in (CombinerInputSource.CONSTANT,
               CombinerInputSource.REGISTER_0,
               CombinerInputSource.REGISTER_1):
        val = combiner_input.value or (0, 0, 0, 1)
        lv = _linearize_rgb(val)
        ch = combiner_input.channel
        if is_color:
            color = g.add_node('ShaderNodeRGB')
            if ch == "RGB":
                g.set_property(color, '_output_default', list(lv))
            elif ch == "RRR":
                g.set_property(color, '_output_default', [lv[0], lv[0], lv[0], lv[3]])
            elif ch == "GGG":
                g.set_property(color, '_output_default', [lv[1], lv[1], lv[1], lv[3]])
            elif ch == "BBB":
                g.set_property(color, '_output_default', [lv[2], lv[2], lv[2], lv[3]])
            elif ch == "AAA":
                g.set_property(color, '_output_default', [lv[3], lv[3], lv[3], lv[3]])
            else:
                g.set_property(color, '_output_default', list(lv))
            return (color, 0)

        alpha = g.add_node('ShaderNodeValue')
        if ch == "A":
            g.set_property(alpha, '_output_default', float(val[3]))
        elif ch == "R":
            g.set_property(alpha, '_output_default', float(lv[0]))
        elif ch == "G":
            g.set_property(alpha, '_output_default', float(lv[1]))
        elif ch == "B":
            g.set_property(alpha, '_output_default', float(lv[2]))
        else:
            g.set_property(alpha, '_output_default', float(val[3]))
        return (alpha, 0)

    # ZERO / ONE / HALF
    if is_color:
        color = g.add_node('ShaderNodeRGB')
        if src == CombinerInputSource.ZERO:
            g.set_property(color, '_output_default', [0, 0, 0, 1])
        elif src == CombinerInputSource.ONE:
            g.set_property(color, '_output_default', [1, 1, 1, 1])
        elif src == CombinerInputSource.HALF:
            g.set_property(color, '_output_default', [0.5, 0.5, 0.5, 1])
        return (color, 0)

    alpha = g.add_node('ShaderNodeValue')
    if src == CombinerInputSource.ZERO:
        g.set_property(alpha, '_output_default', 0.0)
    elif src == CombinerInputSource.ONE:
        g.set_property(alpha, '_output_default', 1.0)
    elif src == CombinerInputSource.HALF:
        g.set_property(alpha, '_output_default', 0.5)
    return (alpha, 0)


def _plan_tev_add_sub(g, inputs, stage, is_color):
    """TEV add/sub body: ``lerp(A, B, C) ± D`` expanded as individual nodes.

    In: g (BRGraphBuilder, mutated); inputs (list of 4 (str, int|str), A/B/C/D);
        stage (CombinerStage, only .operation is read); is_color (bool).
    Out: (str, int) — final MixRGB (color path) or Math (alpha path) output socket.
    """
    is_sub = (stage.operation == CombinerOp.SUBTRACT)

    if is_color:
        # (1 - C)
        sub0 = g.add_node('ShaderNodeMixRGB',
                          properties={'blend_type': 'SUBTRACT'},
                          input_defaults={0: 1.0, 1: [1, 1, 1, 1]})
        g.add_link(inputs[2][0], inputs[2][1], sub0, 2)
        # B * C
        mul0 = g.add_node('ShaderNodeMixRGB',
                          properties={'blend_type': 'MULTIPLY'},
                          input_defaults={0: 1.0})
        g.add_link(inputs[1][0], inputs[1][1], mul0, 1)
        g.add_link(inputs[2][0], inputs[2][1], mul0, 2)
        # A * (1 - C)
        mul1 = g.add_node('ShaderNodeMixRGB',
                          properties={'blend_type': 'MULTIPLY'},
                          input_defaults={0: 1.0})
        g.add_link(inputs[0][0], inputs[0][1], mul1, 1)
        g.add_link(sub0, 0, mul1, 2)
        # A*(1-C) + B*C
        add0 = g.add_node('ShaderNodeMixRGB',
                          properties={'blend_type': 'ADD'},
                          input_defaults={0: 1.0})
        g.add_link(mul1, 0, add0, 1)
        g.add_link(mul0, 0, add0, 2)
        # ± D
        final = g.add_node('ShaderNodeMixRGB',
                           properties={'blend_type': 'SUBTRACT' if is_sub else 'ADD'},
                           input_defaults={0: 1.0})
        g.add_link(inputs[3][0], inputs[3][1], final, 1)
        g.add_link(add0, 0, final, 2)
        return (final, 0)

    # Alpha path — Math nodes (note: original code has socket-index quirks
    # preserved here for byte-identical output).
    sub0 = g.add_node('ShaderNodeMath',
                      properties={'operation': 'SUBTRACT'},
                      input_defaults={1: 1.0})
    g.add_link(inputs[2][0], inputs[2][1], sub0, 2)
    mul0 = g.add_node('ShaderNodeMath', properties={'operation': 'MULTIPLY'})
    g.add_link(inputs[1][0], inputs[1][1], mul0, 1)
    g.add_link(inputs[2][0], inputs[2][1], mul0, 2)
    mul1 = g.add_node('ShaderNodeMath', properties={'operation': 'MULTIPLY'})
    g.add_link(inputs[0][0], inputs[0][1], mul1, 1)
    g.add_link(sub0, 0, mul1, 2)
    add0 = g.add_node('ShaderNodeMath', properties={'operation': 'ADD'})
    g.add_link(mul1, 0, add0, 1)
    g.add_link(mul0, 0, add0, 2)
    final = g.add_node('ShaderNodeMath',
                       properties={'operation': 'SUBTRACT' if is_sub else 'ADD'})
    g.add_link(inputs[3][0], inputs[3][1], final, 1)
    g.add_link(add0, 0, final, 2)
    return (final, 0)


# ---------------------------------------------------------------------------
# Pixel engine / fragment blending
# ---------------------------------------------------------------------------


def _plan_pixel_engine(g, ir_mat, color_ref, alpha_ref):
    """Apply fragment-blending effects; returns updated chain refs + flags.

    In: g (BRGraphBuilder, mutated); ir_mat (IRMaterial);
        color_ref/alpha_ref ((str, int|str), current chain sockets).
    Out: (color_ref, alpha_ref, transparent_shader, alt_blend_mode, blend_method):
         color_ref/alpha_ref: possibly-replaced socket refs ((str, int|str)).
         transparent_shader (bool): wire Alpha input on Principled BSDF.
         alt_blend_mode (str): 'NOTHING' / 'ADD' / 'ADD_ALPHA' / 'MULTIPLY' — picked
             up by _plan_output_shader for post-shader wiring.
         blend_method (str|None): 'OPAQUE' / 'HASHED' / 'BLEND' / None (no change).
    """
    transparent = False
    alt_blend = 'NOTHING'
    blend_method = None

    fb = ir_mat.fragment_blending
    if fb is None:
        if ir_mat.is_translucent:
            transparent = True
            blend_method = 'HASHED'
        return color_ref, alpha_ref, transparent, alt_blend, blend_method

    effect = fb.effect
    sf, df = fb.source_factor, fb.dest_factor

    if effect == OutputBlendEffect.OPAQUE:
        pass
    elif effect == OutputBlendEffect.ALPHA_BLEND:
        transparent = True
        blend_method = 'HASHED'
    elif effect == OutputBlendEffect.INVERSE_ALPHA_BLEND:
        transparent = True
        blend_method = 'HASHED'
        factor = g.add_node('ShaderNodeMath',
                            properties={'operation': 'SUBTRACT', 'use_clamp': True},
                            input_defaults={0: 1.0})
        g.add_link(alpha_ref[0], alpha_ref[1], factor, 1)
        alpha_ref = (factor, 0)
    elif effect == OutputBlendEffect.ADDITIVE:
        alt_blend = 'ADD'
    elif effect == OutputBlendEffect.ADDITIVE_ALPHA:
        transparent = True
        alt_blend = 'ADD_ALPHA'
    elif effect == OutputBlendEffect.ADDITIVE_INV_ALPHA:
        transparent = True
        alt_blend = 'ADD'
        blend = g.add_node('ShaderNodeMixRGB',
                           input_defaults={2: [0, 0, 0, 0xFF]})
        g.add_link(alpha_ref[0], alpha_ref[1], blend, 0)
        g.add_link(color_ref[0], color_ref[1], blend, 1)
        color_ref = (blend, 0)
    elif effect == OutputBlendEffect.MULTIPLY:
        alt_blend = 'MULTIPLY'
    elif effect == OutputBlendEffect.SRC_ALPHA_ONLY:
        blend = g.add_node('ShaderNodeMixRGB',
                           input_defaults={1: [0, 0, 0, 0xFF]})
        g.add_link(alpha_ref[0], alpha_ref[1], blend, 0)
        g.add_link(color_ref[0], color_ref[1], blend, 2)
        color_ref = (blend, 0)
    elif effect == OutputBlendEffect.INV_SRC_ALPHA_ONLY:
        blend = g.add_node('ShaderNodeMixRGB',
                           input_defaults={2: [0, 0, 0, 0xFF]})
        g.add_link(alpha_ref[0], alpha_ref[1], blend, 0)
        g.add_link(color_ref[0], color_ref[1], blend, 1)
        color_ref = (blend, 0)
    elif effect == OutputBlendEffect.INVISIBLE:
        transparent = True
        blend_method = 'HASHED'
        invisible = g.add_node('ShaderNodeValue')
        g.set_property(invisible, '_output_default', 0.0)
        alpha_ref = (invisible, 0)
    elif effect == OutputBlendEffect.BLACK:
        black = g.add_node('ShaderNodeRGB')
        g.set_property(black, '_output_default', [0, 0, 0, 1])
        color_ref = (black, 0)
    elif effect == OutputBlendEffect.WHITE:
        white = g.add_node('ShaderNodeRGB')
        g.set_property(white, '_output_default', [1, 1, 1, 1])
        color_ref = (white, 0)
    elif effect == OutputBlendEffect.INVERT:
        invert = g.add_node('ShaderNodeInvert')
        g.add_link(color_ref[0], color_ref[1], invert, 1)
        color_ref = (invert, 0)
    elif effect == OutputBlendEffect.CUSTOM:
        if df == BlendFactor.ZERO:
            if sf == BlendFactor.SRC_ALPHA:
                blend = g.add_node('ShaderNodeMixRGB',
                                   input_defaults={1: [0, 0, 0, 0xFF]})
                g.add_link(alpha_ref[0], alpha_ref[1], blend, 0)
                g.add_link(color_ref[0], color_ref[1], blend, 2)
                color_ref = (blend, 0)
            elif sf == BlendFactor.INV_SRC_ALPHA:
                blend = g.add_node('ShaderNodeMixRGB',
                                   input_defaults={2: [0, 0, 0, 0xFF]})
                g.add_link(alpha_ref[0], alpha_ref[1], blend, 0)
                g.add_link(color_ref[0], color_ref[1], blend, 1)
                color_ref = (blend, 0)

    return color_ref, alpha_ref, transparent, alt_blend, blend_method


# ---------------------------------------------------------------------------
# Output shader
# ---------------------------------------------------------------------------


def _plan_output_shader(g, ir_mat, color_ref, alpha_ref, bump_ref,
                        transparent_shader, alt_blend_mode, blend_method):
    """Wire the Principled BSDF (+ optional emission / add-shader / bump).

    In: g (BRGraphBuilder, mutated); ir_mat (IRMaterial);
        color_ref/alpha_ref/bump_ref ((str, int|str)|None);
        transparent_shader (bool); alt_blend_mode (str);
        blend_method (str|None, incoming from _plan_pixel_engine).
    Out: (shader_ref, blend_method): shader_ref ((str, int|str)) feeds the final
         add-shader that receives the ambient emission; blend_method may be
         upgraded to 'BLEND' by alt_blend_mode.
    """
    # Principled BSDF. Specular computations mirror the original math.
    tint = _compute_specular_tint(ir_mat)
    shader_props = {}
    shader_defaults = {
        'Specular IOR Level': (ir_mat.shininess / 50) if ir_mat.enable_specular else 0.0,
        'Specular Tint': tint,
        'Roughness': 0.5,
    }
    shader = g.add_node('ShaderNodeBsdfPrincipled',
                        properties=shader_props,
                        input_defaults=shader_defaults)

    if ir_mat.lighting == LightingModel.LIT:
        g.add_link(color_ref[0], color_ref[1], shader, 'Base Color')
        if transparent_shader:
            g.add_link(alpha_ref[0], alpha_ref[1], shader, 'Alpha')
        diffuse_ref = (shader, 0)
    else:
        # Unlit — emission for flat appearance.
        g.set_input_default(shader, 'Base Color', [0, 0, 0, 1])
        emission = g.add_node('ShaderNodeEmission')
        g.add_link(color_ref[0], color_ref[1], emission, 'Color')
        diffuse_ref = (emission, 0)

        if transparent_shader:
            mixshader = g.add_node('ShaderNodeMixShader')
            transparent_sh = g.add_node('ShaderNodeBsdfTransparent')
            g.add_link(alpha_ref[0], alpha_ref[1], mixshader, 0)
            g.add_link(transparent_sh, 0, mixshader, 1)
            g.add_link(diffuse_ref[0], diffuse_ref[1], mixshader, 2)
            diffuse_ref = (mixshader, 0)

        addshader = g.add_node('ShaderNodeAddShader')
        g.add_link(diffuse_ref[0], diffuse_ref[1], addshader, 0)
        g.add_link(shader, 0, addshader, 1)
        shader = addshader
        diffuse_ref = (addshader, 0)

    shader_ref = (shader, 0)

    if bump_ref is not None:
        bump = g.add_node('ShaderNodeBump', input_defaults={1: 1.0})
        g.add_link(bump_ref[0], bump_ref[1], bump, 2)
        # Bump's output feeds the Principled BSDF's Normal input. Only
        # valid when shader is still the BSDF — for unlit path with add
        # shader we skip.
        if ir_mat.lighting == LightingModel.LIT:
            g.add_link(bump, 0, shader, 'Normal')

    if alt_blend_mode in ('ADD', 'ADD_ALPHA'):
        blend_method = 'BLEND'
        e = g.add_node('ShaderNodeEmission')
        t = g.add_node('ShaderNodeBsdfTransparent')
        add = g.add_node('ShaderNodeAddShader')
        g.add_link(color_ref[0], color_ref[1], e, 0)
        if alt_blend_mode == 'ADD_ALPHA':
            strength = g.add_node('ShaderNodeMath',
                                  properties={'operation': 'MULTIPLY'},
                                  input_defaults={1: 1.9})
            g.add_link(alpha_ref[0], alpha_ref[1], strength, 0)
            g.add_link(strength, 0, e, 1)
        else:
            g.set_input_default(e, 1, 1.9)
        g.add_link(e, 0, add, 0)
        g.add_link(t, 0, add, 1)
        shader_ref = (add, 0)
    elif alt_blend_mode == 'MULTIPLY':
        blend_method = 'BLEND'
        t = g.add_node('ShaderNodeBsdfTransparent')
        g.add_link(color_ref[0], color_ref[1], t, 0)
        shader_ref = (t, 0)

    return shader_ref, blend_method


def _compute_specular_tint(ir_mat):
    """Tint = (spec - 1) / (diff - 1) per channel, clamped to [0, 1].

    Blender 4's Principled BSDF computes specular as mix(white, base_color, tint);
    the formula inverts that so our IR specular color survives the mapping.

    In: ir_mat (IRMaterial).
    Out: list[float, float, float, float] — per-channel tint with alpha=1.0.
    """
    tint = [0.0, 0.0, 0.0, 1.0]
    for c in range(3):
        diff = srgb_to_linear(ir_mat.diffuse_color[c])
        spec = srgb_to_linear(ir_mat.specular_color[c])
        if abs(diff - 1.0) > 0.01:
            tint[c] = max(0.0, min(1.0, (spec - 1.0) / (diff - 1.0)))
        else:
            tint[c] = 0.0
    return tint


# ---------------------------------------------------------------------------
# Ambient
# ---------------------------------------------------------------------------


def _plan_ambient_emission(g, ir_mat, shader_ref):
    """Add the hidden ambient emission + add-shader pair for round-trip export.

    The ambient emission has Strength=0 (disconnected visually) but exporter
    reads the Color back by node name.

    In: g (BRGraphBuilder, mutated); ir_mat (IRMaterial); shader_ref ((str, int|str)).
    Out: (str, int) — final add-shader output that should feed Material Output.
    """
    ambient_emission = g.add_node(
        'ShaderNodeEmission',
        name='dat_ambient_emission',
        input_defaults={
            'Color': _linearize_rgb(ir_mat.ambient_color),
            'Strength': 0.0,
        },
    )
    ambient_add = g.add_node('ShaderNodeAddShader', name='dat_ambient_add')
    g.add_link(shader_ref[0], shader_ref[1], ambient_add, 0)
    g.add_link(ambient_emission, 0, ambient_add, 1)
    return (ambient_add, 0)


# ---------------------------------------------------------------------------
# Auto-layout (pure — mirrors build-phase version)
# ---------------------------------------------------------------------------


def _plan_auto_layout(g):
    """Assign each BRNode a canvas location via BFS depth from the output.

    Columns go right→left (output at column 0, right edge); within a column
    nodes are sorted by name for stable vertical order.

    In: g (BRGraphBuilder, nodes mutated in place).
    Out: None. Each BRNode.location gets a (x, y) tuple.
    """
    NODE_WIDTH = 300
    NODE_HEIGHT = 200

    nodes = g._nodes  # intentional access — builder hasn't finalized yet
    links = g._links

    # Find output
    output = None
    for n in nodes:
        if n.node_type == 'ShaderNodeOutputMaterial':
            output = n
            break
    if output is None:
        return

    # Reverse adjacency (target → source list)
    inputs_of = {}
    for link in links:
        inputs_of.setdefault(link.to_node, [])
        if link.from_node not in inputs_of[link.to_node]:
            inputs_of[link.to_node].append(link.from_node)

    # BFS by depth from output
    column_of = {output.name: 0}
    queue = [output.name]
    while queue:
        current = queue.pop(0)
        col = column_of[current]
        for source in inputs_of.get(current, []):
            new_col = col + 1
            if source not in column_of or column_of[source] < new_col:
                column_of[source] = new_col
                queue.append(source)

    max_col = max(column_of.values()) if column_of else 0
    for n in nodes:
        if n.name not in column_of:
            max_col += 1
            column_of[n.name] = max_col

    # Group + stable sort within column
    columns = {}
    for name, col in column_of.items():
        columns.setdefault(col, []).append(name)
    for col in columns:
        columns[col].sort()

    max_column = max(columns.keys()) if columns else 0
    by_name = {n.name: n for n in nodes}
    for col, names in columns.items():
        x = (max_column - col) * NODE_WIDTH
        for i, name in enumerate(names):
            by_name[name].location = (x, -i * NODE_HEIGHT)
