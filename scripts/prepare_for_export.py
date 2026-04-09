"""Standalone Blender script: Prepare a scene for Colosseum/XD export.

Run this from Blender's Scripting panel (Text Editor > Run Script) before
exporting. It ensures all objects in the scene have the custom properties
the exporter expects.

The script operates on all objects in the scene — no selection required:
  1. Creates a Battle_Camera if none exists
  2. Limits vertex bone weights to 3 per vertex (GameCube constraint)
  3. Splits oversized meshes by body region if >25 estimated PObjects
  4. Applies default PKX metadata to all armatures that don't have it
  5. Auto-derives animation timing from action durations
  6. Auto-selects GX texture formats for all armature textures
  7. Inserts shiny filter nodes into all materials (identity defaults, toggle off)
  8. Creates standard battle lighting (1 ambient + 3 directional)

After running, the scene can be exported via File > Export > Gamecube model (.dat).

Requires the DAT plugin addon to be enabled (for registered shiny properties).

This script is fully standalone — no imports from the plugin codebase.
"""
import bpy
import math


# ---------------------------------------------------------------------------
# Battle camera
# ---------------------------------------------------------------------------

BATTLE_CAMERA_NAME = "Battle_Camera"
BATTLE_CAMERA_TARGET = "Battle_Camera_target"


def _model_display_size():
    """Compute a display size for empties: 3% of the scene's model bounding box diagonal."""
    from mathutils import Vector
    min_co = [float('inf')] * 3
    max_co = [float('-inf')] * 3
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            for corner in obj.bound_box:
                world = obj.matrix_world @ Vector(corner)
                for i in range(3):
                    min_co[i] = min(min_co[i], world[i])
                    max_co[i] = max(max_co[i], world[i])
    if min_co[0] == float('inf'):
        return 0.5
    diag = (Vector(max_co) - Vector(min_co)).length
    return max(0.1, min(3.0, diag * 0.03))


def prepare_camera():
    """Create a default battle camera if none exists, and set aspect on all cameras.

    Returns the number of cameras created (0 or 1).
    """
    created = 0

    # Create Battle_Camera if it doesn't exist
    if bpy.data.objects.get(BATTLE_CAMERA_NAME) is None:
        # Compute model bounding box to position camera intelligently
        from mathutils import Vector
        min_co = [float('inf')] * 3
        max_co = [float('-inf')] * 3
        for obj in bpy.data.objects:
            if obj.type == 'MESH':
                for corner in obj.bound_box:
                    world = obj.matrix_world @ Vector(corner)
                    for i in range(3):
                        min_co[i] = min(min_co[i], world[i])
                        max_co[i] = max(max_co[i], world[i])

        if min_co[0] != float('inf'):
            center_x = (min_co[0] + max_co[0]) / 2
            center_y = (min_co[1] + max_co[1]) / 2
            center_z = (min_co[2] + max_co[2]) / 2
            height = max_co[2] - min_co[2]
            depth = max_co[1] - min_co[1]
        else:
            # No meshes — use sensible defaults
            center_x, center_y, center_z = 0.0, 0.0, 0.5
            height = 1.0
            depth = 1.0

        # Target at halfway up the model's max height
        target_z = max_co[2] * 0.5

        # Camera in front of the model (negative Y), at target height,
        # pulled back ~2.5× the model's height (matches typical game framing)
        cam_distance = max(height * 2.5, 1.5)
        cam_pos = (center_x, center_y - cam_distance, target_z)
        target_pos = (center_x, center_y, target_z)

        cam_data = bpy.data.cameras.new(BATTLE_CAMERA_NAME)
        cam_data.type = 'PERSP'
        cam_data.lens = 37.5       # ~27° vertical FOV (most common across all PKX models)
        cam_data.clip_start = 0.01
        cam_data.clip_end = 3277.0

        cam_obj = bpy.data.objects.new(BATTLE_CAMERA_NAME, cam_data)
        cam_obj.location = cam_pos
        cam_obj["dat_camera_aspect"] = 1.18
        bpy.context.scene.collection.objects.link(cam_obj)

        # Create target empty at model center
        target = bpy.data.objects.new(BATTLE_CAMERA_TARGET, None)
        target.empty_display_type = 'PLAIN_AXES'
        target.empty_display_size = _model_display_size()
        target.location = target_pos
        bpy.context.scene.collection.objects.link(target)

        # Add TRACK_TO constraint
        track = cam_obj.constraints.new('TRACK_TO')
        track.target = target
        track.track_axis = 'TRACK_NEGATIVE_Z'
        track.up_axis = 'UP_Y'

        created = 1
        print("  Created '%s' in front of model, targeting center" % BATTLE_CAMERA_NAME)
        print("    Position: (%.2f, %.2f, %.2f)" % cam_pos)
        print("    Target: (%.2f, %.2f, %.2f)" % target_pos)
        print("    Lens: 37.5mm (~27° FOV), aspect: 1.18")
        print("    Adjust position/FOV to frame your model. Smaller models need wider FOV.")

    # Set dat_camera_aspect on any cameras that don't have it
    for obj in bpy.data.objects:
        if obj.type == 'CAMERA' and "dat_camera_aspect" not in obj:
            obj["dat_camera_aspect"] = 1.18
            print("  Camera '%s': set dat_camera_aspect = 1.18" % obj.name)

    return created


# ---------------------------------------------------------------------------
# PKX metadata
# ---------------------------------------------------------------------------

def _find_head_bone(armature):
    """Auto-detect the head bone by name heuristic."""
    for bone in armature.data.bones:
        if 'head' in bone.name.lower():
            return bone.name
    root_bones = [b for b in armature.data.bones if b.parent is None]
    if root_bones:
        root = root_bones[0]
        if root.children:
            return root.children[0].name
        return root.name
    return ""


def apply_pkx_metadata(armature, format='XD', model_type='POKEMON', species_id=0):
    """Apply default PKX metadata to an armature."""
    is_xd = (format == 'XD')

    # --- General ---
    armature["dat_pkx_format"] = format
    armature["dat_pkx_species_id"] = species_id
    armature["dat_pkx_model_type"] = model_type
    armature["dat_pkx_particle_orientation"] = 0
    armature["dat_pkx_distortion_param"] = 0
    armature["dat_pkx_distortion_type"] = 0

    # Head bone
    head_bone_name = _find_head_bone(armature)
    armature["dat_pkx_head_bone"] = head_bone_name

    # --- Flags (all off) ---
    armature["dat_pkx_flag_flying"] = False
    armature["dat_pkx_flag_skip_frac_frames"] = False
    armature["dat_pkx_flag_no_root_anim"] = False
    armature["dat_pkx_flag_bit7"] = False

    # Shiny registered properties — set identity defaults
    armature.dat_pkx_shiny = False
    armature.dat_pkx_shiny_route_r = '0'
    armature.dat_pkx_shiny_route_g = '1'
    armature.dat_pkx_shiny_route_b = '2'
    armature.dat_pkx_shiny_route_a = '3'
    armature.dat_pkx_shiny_brightness_r = 0.0
    armature.dat_pkx_shiny_brightness_g = 0.0
    armature.dat_pkx_shiny_brightness_b = 0.0

    # --- Sub-animations (all inactive) ---
    sub_triggers = ["sleep_on", "sleep_off", "extra", "unused"]
    for i in range(4):
        prefix = "dat_pkx_sub_anim_%d" % i
        armature[prefix + "_type"] = "none"
        armature[prefix + "_trigger"] = sub_triggers[i]
        armature[prefix + "_anim_ref"] = ""

    # --- Body map bones ---
    bones = list(armature.data.bones)
    root_name = bones[0].name if bones else ""
    armature["dat_pkx_body_root"] = root_name
    armature["dat_pkx_body_head"] = head_bone_name
    armature["dat_pkx_body_center"] = ""
    for key in ["body_3", "neck", "head_top", "limb_a", "limb_b",
                "secondary_8", "secondary_9", "secondary_10", "secondary_11",
                "attach_a", "attach_b", "attach_c", "attach_d"]:
        armature["dat_pkx_body_%s" % key] = ""

    # --- Animation entries (17 slots) ---
    anim_count = 17
    armature["dat_pkx_anim_count"] = anim_count

    # Slot types: 0=idle(loop), 8=damage(hit), 9=damageB(compound), 10=faint(hit), rest=action
    _SLOT_TYPES = {0: "loop", 8: "hit_reaction", 9: "compound", 10: "hit_reaction"}

    for i in range(anim_count):
        prefix = "dat_pkx_anim_%02d" % i
        anim_type = _SLOT_TYPES.get(i, "action")

        armature[prefix + "_type"] = anim_type
        armature[prefix + "_sub_0_anim"] = ""
        armature[prefix + "_sub_count"] = 2 if anim_type == "compound" else 1
        armature[prefix + "_damage_flags"] = 0
        armature[prefix + "_terminator"] = 3 if is_xd else 1

        # Timing defaults (will be recalculated by derive_timing below)
        armature[prefix + "_timing_1"] = 0.0
        armature[prefix + "_timing_2"] = 0.0
        armature[prefix + "_timing_3"] = 0.0
        armature[prefix + "_timing_4"] = 0.0

    print("  PKX metadata applied to '%s':" % armature.name)
    print("    Format: %s, Species: %d, Head bone: '%s'" % (format, species_id, head_bone_name))
    print("    17 animation slots (slot 0 = idle loop)")
    print("    Shiny params available in PKX Metadata panel (default: identity)")


def _get_action_duration(action_name):
    """Get an action's duration in seconds (frame count / 60fps). Returns 0 if not found."""
    action = bpy.data.actions.get(action_name)
    if not action or not action.fcurves:
        return 0.0
    max_frame = max(kp.co[0] for fc in action.fcurves for kp in fc.keyframe_points)
    return max_frame / 60.0


def derive_timing(armature):
    """Auto-derive animation timing fields from action durations.

    Timing semantics per anim_type:
      loop:         T1 = duration
      action:       T1 = wind-up (33%), T2 = hit (66%), T3 = duration
      hit_reaction: T1 = reaction start (50%), T2 = duration
      compound:     T1 = sub1 mid, T2 = sub1 end, T3 = sub2 mid, T4 = sub2 end

    Returns the number of entries updated.
    """
    anim_count = armature.get("dat_pkx_anim_count", 0)
    updated = 0

    for i in range(anim_count):
        prefix = "dat_pkx_anim_%02d" % i
        anim_type = armature.get(prefix + "_type", "action")
        action_name = armature.get(prefix + "_sub_0_anim", "")
        dur = _get_action_duration(action_name) if action_name else 0.0

        if dur <= 0:
            continue

        if anim_type == "loop":
            armature[prefix + "_timing_1"] = dur
        elif anim_type == "action":
            armature[prefix + "_timing_1"] = dur / 3.0
            armature[prefix + "_timing_2"] = dur * 2.0 / 3.0
            armature[prefix + "_timing_3"] = dur
        elif anim_type == "hit_reaction":
            armature[prefix + "_timing_1"] = dur * 0.5
            armature[prefix + "_timing_2"] = dur
        elif anim_type == "compound":
            # Two sub-anims: get duration of second if available
            action2_name = armature.get(prefix + "_sub_1_anim", "")
            dur2 = _get_action_duration(action2_name) if action2_name else dur
            armature[prefix + "_timing_1"] = dur * 0.5
            armature[prefix + "_timing_2"] = dur
            armature[prefix + "_timing_3"] = dur2 * 0.5
            armature[prefix + "_timing_4"] = dur2

        updated += 1

    return updated


# ---------------------------------------------------------------------------
# Texture formats
# ---------------------------------------------------------------------------

def _analyze_texture(img):
    """Analyze an image's pixels and return a suitable GX format name.

    Checks for grayscale, alpha usage, and color count to pick the most
    efficient format. Returns a format string like 'CMPR', 'I8', etc.
    """
    w, h = img.size[0], img.size[1]
    if w == 0 or h == 0:
        return None

    pixels = img.pixels[:]
    num_pixels = w * h

    is_gray = True
    has_alpha = False
    unique_colors = set()
    max_unique = 260  # stop counting after we know it's > 256

    for i in range(num_pixels):
        base = i * 4
        r, g, b, a = pixels[base], pixels[base+1], pixels[base+2], pixels[base+3]

        if a < 0.998:
            has_alpha = True

        if is_gray and (abs(r - g) > 0.004 or abs(r - b) > 0.004):
            is_gray = False

        if len(unique_colors) < max_unique:
            ri = min(255, int(r * 255 + 0.5))
            gi = min(255, int(g * 255 + 0.5))
            bi = min(255, int(b * 255 + 0.5))
            ai = min(255, int(a * 255 + 0.5))
            unique_colors.add((ri, gi, bi, ai))

    n_colors = len(unique_colors)

    # Format selection logic (matches shared/texture_encoder.py)
    if is_gray:
        if has_alpha:
            return 'IA8'
        else:
            return 'I8'
    elif n_colors <= 16:
        return 'C4'
    elif n_colors <= 256:
        return 'C8'
    elif has_alpha:
        return 'RGB5A3'
    else:
        return 'CMPR'


def prepare_texture_formats(armature):
    """Auto-select GX texture formats for textures that don't have one set.

    Returns the number of textures that were assigned a format.
    """
    images_seen = set()
    count = 0

    for child in armature.children:
        if child.type != 'MESH':
            continue
        for slot in child.material_slots:
            if not slot.material or not slot.material.use_nodes:
                continue
            for node in slot.material.node_tree.nodes:
                if node.bl_idname == 'ShaderNodeTexImage' and node.image:
                    img = node.image
                    if img.name in images_seen:
                        continue
                    images_seen.add(img.name)

                    # Skip textures that already have a format set
                    if hasattr(img, 'dat_gx_format') and img.dat_gx_format != 'AUTO':
                        continue

                    fmt = _analyze_texture(img)
                    if fmt:
                        img.dat_gx_format = fmt
                        count += 1
                        print("    %s (%dx%d): %s" % (img.name, img.size[0], img.size[1], fmt))

    return count


# ---------------------------------------------------------------------------
# Shiny filter
# ---------------------------------------------------------------------------

_SHINY_ROUTE_GROUP = "DATPlugin_ShinyRoute"
_SHINY_BRIGHT_GROUP = "DATPlugin_ShinyBright"


def _shiny_auto_layout(nodes, links, output_type='OUTPUT_MATERIAL'):
    """Arrange shader nodes left-to-right via topological sort from output."""
    _W, _H = 300, 200
    output = next((n for n in nodes if n.type == output_type), None)
    if output is None:
        return
    inputs_of = {}
    for link in links:
        inputs_of.setdefault(link.to_node, [])
        if link.from_node not in inputs_of[link.to_node]:
            inputs_of[link.to_node].append(link.from_node)
    column_of = {output: 0}
    queue = [output]
    while queue:
        node = queue.pop(0)
        col = column_of[node]
        for source in inputs_of.get(node, []):
            new_col = col + 1
            if source not in column_of or column_of[source] < new_col:
                column_of[source] = new_col
                queue.append(source)
    max_col = max(column_of.values()) if column_of else 0
    for node in nodes:
        if node not in column_of:
            max_col += 1
            column_of[node] = max_col
    columns = {}
    for node, col in column_of.items():
        columns.setdefault(col, []).append(node)
    for col in columns:
        columns[col].sort(key=lambda n: n.name)
    max_column = max(columns.keys()) if columns else 0
    for col, col_nodes in columns.items():
        x = (max_column - col) * _W
        for i, node in enumerate(col_nodes):
            node.location = (x, -i * _H)


def _shiny_build_route_group(routing, name):
    """Create/rebuild the ShinyRoute node group (channel swizzle)."""
    group = bpy.data.node_groups.get(name)
    if group is None:
        group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
        group.interface.new_socket('Color', in_out='INPUT', socket_type='NodeSocketColor')
        group.interface.new_socket('Color', in_out='OUTPUT', socket_type='NodeSocketColor')
    group.nodes.clear()
    gi = group.nodes.new('NodeGroupInput')
    go = group.nodes.new('NodeGroupOutput')
    sep = group.nodes.new('ShaderNodeSeparateColor')
    sep.mode = 'RGB'
    group.links.new(gi.outputs[0], sep.inputs[0])
    srcs = {0: sep.outputs[0], 1: sep.outputs[1], 2: sep.outputs[2]}
    comb = group.nodes.new('ShaderNodeCombineColor')
    comb.mode = 'RGB'
    for i in range(3):
        if routing[i] in srcs:
            group.links.new(srcs[routing[i]], comb.inputs[i])
        else:
            v = group.nodes.new('ShaderNodeValue')
            v.outputs[0].default_value = 0.0
            group.links.new(v.outputs[0], comb.inputs[i])
    group.links.new(comb.outputs[0], go.inputs[0])
    _shiny_auto_layout(group.nodes, group.links, output_type='GROUP_OUTPUT')
    return group


def _shiny_build_bright_group(brightness, name):
    """Create/rebuild the ShinyBright node group (per-channel brightness)."""
    group = bpy.data.node_groups.get(name)
    if group is None:
        group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
        group.interface.new_socket('Color', in_out='INPUT', socket_type='NodeSocketColor')
        group.interface.new_socket('Color', in_out='OUTPUT', socket_type='NodeSocketColor')
    group.nodes.clear()
    gi = group.nodes.new('NodeGroupInput')
    go = group.nodes.new('NodeGroupOutput')
    to_srgb = group.nodes.new('ShaderNodeGamma')
    to_srgb.inputs[1].default_value = 1.0 / 2.2
    group.links.new(gi.outputs[0], to_srgb.inputs[0])
    sep = group.nodes.new('ShaderNodeSeparateColor')
    sep.mode = 'RGB'
    group.links.new(to_srgb.outputs[0], sep.inputs[0])
    scaled = []
    for i, ch in enumerate(['R', 'G', 'B']):
        mult = group.nodes.new('ShaderNodeMath')
        mult.operation = 'MULTIPLY'
        mult.name = 'Brightness_%s' % ch
        group.links.new(sep.outputs[i], mult.inputs[0])
        mult.inputs[1].default_value = brightness[i] + 1.0
        scaled.append(mult.outputs[0])
    comb = group.nodes.new('ShaderNodeCombineColor')
    comb.mode = 'RGB'
    for i in range(3):
        group.links.new(scaled[i], comb.inputs[i])
    to_lin = group.nodes.new('ShaderNodeGamma')
    to_lin.inputs[1].default_value = 2.2
    group.links.new(comb.outputs[0], to_lin.inputs[0])
    group.links.new(to_lin.outputs[0], go.inputs[0])
    _shiny_auto_layout(group.nodes, group.links, output_type='GROUP_OUTPUT')
    return group


def _shiny_find_color_input(nodes):
    """Find the main color input on the output shader."""
    for node in nodes:
        if node.type == 'BSDF_PRINCIPLED':
            bc = node.inputs['Base Color']
            if bc.is_linked:
                return node, bc
    for node in nodes:
        if node.type == 'EMISSION':
            return node, node.inputs['Color']
    for node in nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node, node.inputs['Base Color']
    return None, None


def _shiny_insert_stage(nodes, links, target_node, target_input,
                        node_group, group_name, mix_name, armature):
    """Insert a shiny stage between a source and a shader input."""
    source_link = None
    for link in links:
        if link.to_node == target_node and link.to_socket == target_input:
            source_link = link
            break
    if source_link is None:
        rgb = nodes.new('ShaderNodeRGB')
        rgb.outputs[0].default_value[:] = list(target_input.default_value)
        source_out = rgb.outputs[0]
    else:
        source_out = source_link.from_socket
        links.remove(source_link)
    gn = nodes.new('ShaderNodeGroup')
    gn.node_tree = node_group
    gn.name = group_name
    links.new(source_out, gn.inputs[0])
    mix = nodes.new('ShaderNodeMixRGB')
    mix.blend_type = 'MIX'
    mix.name = mix_name
    mix.inputs[0].default_value = 0.0
    links.new(source_out, mix.inputs[1])
    links.new(gn.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], target_input)
    # Driver for shiny toggle
    mix.inputs[0].default_value = 0.0
    dd = mix.inputs[0].driver_add("default_value")
    dd.driver.type = 'AVERAGE'
    var = dd.driver.variables.new()
    var.name = "shiny"
    var.type = 'SINGLE_PROP'
    var.targets[0].id_type = 'OBJECT'
    var.targets[0].id = armature
    var.targets[0].data_path = 'dat_pkx_shiny'


def prepare_shiny_filter(armature):
    """Set up shiny filter node groups and insert into all materials.

    Builds ShinyRoute and ShinyBright node groups, inserts them into every
    material on the armature's child meshes, and adds drivers for the
    shiny toggle. Skips materials that already have shiny nodes.

    Returns the number of materials that had shiny filter added.
    """
    route = [
        int(armature.dat_pkx_shiny_route_r),
        int(armature.dat_pkx_shiny_route_g),
        int(armature.dat_pkx_shiny_route_b),
        int(armature.dat_pkx_shiny_route_a),
    ]
    brightness = [
        armature.dat_pkx_shiny_brightness_r,
        armature.dat_pkx_shiny_brightness_g,
        armature.dat_pkx_shiny_brightness_b,
    ]

    route_group = _shiny_build_route_group(route, _SHINY_ROUTE_GROUP)
    bright_group = _shiny_build_bright_group(brightness, _SHINY_BRIGHT_GROUP)

    count = 0
    for child in armature.children:
        if child.type != 'MESH':
            continue
        for slot in child.material_slots:
            mat = slot.material
            if not mat or not mat.use_nodes:
                continue
            nodes = mat.node_tree.nodes
            if any(n.name in ('shiny_route_mix', 'shiny_bright_mix') for n in nodes):
                continue
            target_node, target_input = _shiny_find_color_input(nodes)
            if target_node is None:
                continue
            links = mat.node_tree.links
            _shiny_insert_stage(nodes, links, target_node, target_input,
                                route_group, 'shiny_route_shader', 'shiny_route_mix', armature)
            _shiny_insert_stage(nodes, links, target_node, target_input,
                                bright_group, 'shiny_bright_shader', 'shiny_bright_mix', armature)
            _shiny_auto_layout(nodes, links)
            count += 1

    return count


# ---------------------------------------------------------------------------
# Ambient light
# ---------------------------------------------------------------------------

def _srgb_to_linear(c):
    """Convert a single sRGB channel value (0-1) to linear."""
    if c <= 0.0404482362771082:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


# ---------------------------------------------------------------------------
# Mesh weight limiting and splitting
# ---------------------------------------------------------------------------

MAX_WEIGHTS_PER_VERTEX = 3
MAX_POBJS_PER_MESH = 25


def _estimate_pobj_count(mesh_obj, bone_names):
    """Estimate how many PObjects envelope splitting will create.

    Counts the unique sets of bones influencing each vertex. The exporter
    creates one PObject per 10 unique bone sets, so dividing by 10 gives
    the estimate.
    """
    combos = set()
    for v in mesh_obj.data.vertices:
        combo = tuple(sorted(
            (mesh_obj.vertex_groups[g.group].name, round(g.weight, 1))
            for g in v.groups
            if g.weight > 0.0 and g.group < len(mesh_obj.vertex_groups)
            and mesh_obj.vertex_groups[g.group].name in bone_names
        ))
        if combo:
            combos.add(combo)
    return max(1, (len(combos) + 9) // 10)


def _get_bone_region(bone, root_children):
    """Find which root-child subtree a bone belongs to.

    Walks up the hierarchy until hitting a direct child of the skeleton
    root. Returns that child's name as the region identifier.
    """
    current = bone
    while current.parent is not None:
        if current.parent.parent is None or current in root_children:
            return current.name
        current = current.parent
    return current.name


def prepare_mesh_weights(armature):
    """Limit vertex weights and split oversized meshes.

    1. Limits all mesh vertices to MAX_WEIGHTS_PER_VERTEX influences.
    2. Normalizes weights after limiting.
    3. If a mesh would produce >MAX_POBJS_PER_MESH PObjects from envelope
       splitting, splits it into body regions based on the bone hierarchy.

    Returns (weights_limited, meshes_split) counts.
    """
    bone_names = {b.name for b in armature.data.bones}
    meshes = [obj for obj in bpy.data.objects
              if obj.type == 'MESH' and obj.parent == armature]

    total_limited = 0
    total_split = 0

    # Step 1: Limit weights on all meshes
    for mesh_obj in meshes:
        # Select only this mesh
        bpy.ops.object.select_all(action='DESELECT')
        mesh_obj.select_set(True)
        bpy.context.view_layer.objects.active = mesh_obj

        # Count vertices that will be affected
        affected = 0
        for v in mesh_obj.data.vertices:
            bone_groups = [g for g in v.groups
                          if g.group < len(mesh_obj.vertex_groups)
                          and mesh_obj.vertex_groups[g.group].name in bone_names
                          and g.weight > 0.0]
            if len(bone_groups) > MAX_WEIGHTS_PER_VERTEX:
                affected += 1

        if affected > 0:
            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
            bpy.ops.object.vertex_group_limit_total(limit=MAX_WEIGHTS_PER_VERTEX)
            bpy.ops.object.mode_set(mode='OBJECT')
            total_limited += affected
            print("    %s: limited %d vertices to %d weights" %
                  (mesh_obj.name, affected, MAX_WEIGHTS_PER_VERTEX))

        # Quantize weights to 10% steps (matching game model precision).
        # Smooth weight painting gives every joint vertex a unique ratio —
        # without quantization a 6000-vertex model can have 1000+ unique combos,
        # each requiring a separate hardware draw call (PObject).
        # We normalize first, THEN quantize, THEN normalize again — this avoids
        # re-normalization creating new non-round values.
        bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
        bpy.ops.object.vertex_group_normalize_all(lock_active=False)
        bpy.ops.object.mode_set(mode='OBJECT')

        mesh_data = mesh_obj.data
        quantized = 0
        for v in mesh_data.vertices:
            for g in v.groups:
                if g.group < len(mesh_obj.vertex_groups):
                    if mesh_obj.vertex_groups[g.group].name in bone_names:
                        q = round(g.weight, 1)
                        if abs(q - g.weight) > 0.001:
                            g.weight = q
                            quantized += 1

        if quantized > 0:
            # Final normalize pass
            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
            bpy.ops.object.vertex_group_normalize_all(lock_active=False)
            bpy.ops.object.mode_set(mode='OBJECT')

            # Second quantize pass — normalization may have un-rounded values
            for v in mesh_data.vertices:
                for g in v.groups:
                    if g.group < len(mesh_obj.vertex_groups):
                        if mesh_obj.vertex_groups[g.group].name in bone_names:
                            g.weight = round(g.weight, 1)

            print("    %s: quantized %d weight values to 10%% steps" %
                  (mesh_obj.name, quantized))

    # Step 2: Split oversized meshes by body region (one pass)
    meshes = [obj for obj in bpy.data.objects
              if obj.type == 'MESH' and obj.parent == armature]

    for mesh_obj in list(meshes):
        est = _estimate_pobj_count(mesh_obj, bone_names)
        if est <= MAX_POBJS_PER_MESH:
            continue

        print("    %s: estimated %d PObjects (threshold %d), splitting by body region..." %
              (mesh_obj.name, est, MAX_POBJS_PER_MESH))

        split_count = _split_mesh_by_region(mesh_obj, armature, bone_names)
        if split_count > 1:
            total_split += split_count
            print("    Split into %d region meshes" % split_count)
        else:
            print("    Could not split further — consider splitting manually")

    return total_limited, total_split


def _split_mesh_by_region(mesh_obj, armature, bone_names):
    """Split a mesh into body regions based on the bone hierarchy.

    Groups vertices by which root-child subtree their dominant bone
    belongs to, then separates into one mesh per region.

    Returns the number of resulting meshes.
    """
    # Find the body root for THIS mesh — the deepest bone in the hierarchy
    # that is an ancestor of all dominant bones used by this mesh, and has
    # >1 child subtree with mesh vertices. This enables recursive splitting:
    # the first pass splits at the hips/spine level, the second pass splits
    # the upper body at the shoulder/head level, etc.

    # Collect bones actually used by this mesh
    mesh_bones = set()
    for v in mesh_obj.data.vertices:
        best_bone = None
        best_weight = -1
        for g in v.groups:
            if g.group < len(mesh_obj.vertex_groups):
                name = mesh_obj.vertex_groups[g.group].name
                if name in bone_names and g.weight > best_weight:
                    best_weight = g.weight
                    best_bone = name
        if best_bone:
            mesh_bones.add(best_bone)

    if len(mesh_bones) < 2:
        return 1

    # Find the lowest common ancestor of all mesh bones, then walk down
    # to the first node with >1 child subtree that has mesh bones
    def _descendants(bone):
        result = {bone.name}
        for c in bone.children:
            result.update(_descendants(c))
        return result

    roots = [b for b in armature.data.bones if b.parent is None]
    if not roots:
        return 1

    body_root = roots[0]
    while True:
        children_with_mesh = [
            c for c in body_root.children
            if _descendants(c) & mesh_bones
        ]
        if len(children_with_mesh) == 1:
            body_root = children_with_mesh[0]
        else:
            break

    if len(children_with_mesh) < 2:
        return 1

    root_children = set(children_with_mesh)

    # Build bone → region map
    bone_to_region = {}
    for bone in armature.data.bones:
        bone_to_region[bone.name] = _get_bone_region(bone, root_children)

    # Assign each vertex to a region based on its dominant (highest weight) bone
    mesh_data = mesh_obj.data
    vertex_regions = {}
    for v in mesh_data.vertices:
        best_bone = None
        best_weight = -1
        for g in v.groups:
            if g.group < len(mesh_obj.vertex_groups):
                vg_name = mesh_obj.vertex_groups[g.group].name
                if vg_name in bone_names and g.weight > best_weight:
                    best_weight = g.weight
                    best_bone = vg_name
        if best_bone and best_bone in bone_to_region:
            vertex_regions[v.index] = bone_to_region[best_bone]
        else:
            vertex_regions[v.index] = '_default'

    # Count regions
    regions = set(vertex_regions.values())
    if len(regions) <= 1:
        return 1

    # Split by selecting vertices per region and separating
    bpy.ops.object.select_all(action='DESELECT')
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj

    # We separate all-but-one region (keep the largest in the original mesh)
    region_vert_counts = {}
    for vi, region in vertex_regions.items():
        region_vert_counts[region] = region_vert_counts.get(region, 0) + 1
    largest_region = max(region_vert_counts, key=region_vert_counts.get)

    regions_to_split = [r for r in regions if r != largest_region]
    split_count = 1  # The original mesh counts as one

    for region in regions_to_split:
        # Re-get mesh_obj reference (may have changed after splits)
        mesh_obj = bpy.context.view_layer.objects.active
        if mesh_obj is None or mesh_obj.type != 'MESH':
            break

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')

        # Select vertices belonging to this region
        mesh_data = mesh_obj.data
        selected = 0
        for v in mesh_data.vertices:
            if vertex_regions.get(v.index) == region:
                v.select = True
                selected += 1
            else:
                v.select = False

        if selected == 0:
            continue

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.separate(type='SELECTED')
        bpy.ops.object.mode_set(mode='OBJECT')

        split_count += 1

        # The newly created mesh is the last selected object
        for obj in bpy.context.selected_objects:
            if obj != mesh_obj and obj.type == 'MESH':
                obj.name = "%s_%s" % (mesh_obj.name, region)
                # Ensure armature modifier exists
                if not any(m.type == 'ARMATURE' for m in obj.modifiers):
                    mod = obj.modifiers.new('Armature', 'ARMATURE')
                    mod.object = armature

        # Rebuild vertex_regions for the remaining mesh (indices shifted)
        new_regions = {}
        for v in mesh_obj.data.vertices:
            # After split, vertex indices are renumbered — use position matching
            # Actually, after separate, the remaining vertices keep their region
            new_regions[v.index] = largest_region
        vertex_regions = new_regions

    return split_count


# ---------------------------------------------------------------------------
# Scene lights
# ---------------------------------------------------------------------------

def prepare_ambient_light():
    """Add an ambient light if none exists in the scene.

    Creates a no-op POINT light with energy=0 (invisible in Blender) and
    a dat_light_type="AMBIENT" custom property. The color controls
    scene-level fill lighting in-game — applied uniformly to all materials.

    Returns the number of ambient lights created (0 or 1).
    """
    # Check for existing ambient light
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT' and obj.get('dat_light_type') == 'AMBIENT':
            return 0

    # Default: (76, 76, 76) / 255 ≈ 0.298 sRGB — the most common
    # ambient color across all tested Pokémon models.
    srgb_val = 76 / 255.0
    linear_val = _srgb_to_linear(srgb_val)

    light_data = bpy.data.lights.new(name='Ambient_Light', type='POINT')
    light_data.energy = 0
    light_data.color = (linear_val, linear_val, linear_val)

    lamp = bpy.data.objects.new(name='Ambient_Light', object_data=light_data)
    lamp["dat_light_type"] = "AMBIENT"
    bpy.context.scene.collection.objects.link(lamp)

    return 1


def prepare_lights():
    """Ensure the scene has the standard 4-light battle setup.

    All game models have exactly 4 LightSets:
      [0] Ambient (76, 76, 76) — uniform fill, POINT with energy=0
      [1] Main directional (204, 204, 204) — brightest, SUN from above-front
      [2] Fill directional (102, 102, 102) — medium, SUN from the side
      [3] Back/rim directional (76, 76, 76) — darker, SUN from behind

    Creates any missing lights. Returns the number of lights created.
    """
    created = 0

    # [0] Ambient — delegate to existing function
    created += prepare_ambient_light()

    # Standard directional lights — (name, color_u8, rotation_euler_degrees)
    _DIRECTIONAL_LIGHTS = [
        ('Main_Light',  204, (math.radians(-45), 0, math.radians(30))),
        ('Fill_Light',  102, (math.radians(-30), 0, math.radians(-60))),
        ('Back_Light',   76, (math.radians(-20), 0, math.radians(150))),
    ]

    for name, color_u8, rotation in _DIRECTIONAL_LIGHTS:
        # Skip if a SUN light with this name already exists
        existing = bpy.data.objects.get(name)
        if existing and existing.type == 'LIGHT' and existing.data.type == 'SUN':
            continue

        srgb_val = color_u8 / 255.0
        linear_val = _srgb_to_linear(srgb_val)

        light_data = bpy.data.lights.new(name=name, type='SUN')
        light_data.energy = 1.0
        light_data.color = (linear_val, linear_val, linear_val)

        lamp = bpy.data.objects.new(name=name, object_data=light_data)
        lamp.rotation_euler = rotation
        bpy.context.scene.collection.objects.link(lamp)
        created += 1

    return created


# ---------------------------------------------------------------------------
# PKX Metadata Panel (registered if addon isn't loaded)
# ---------------------------------------------------------------------------

_SHINY_CHANNEL_ITEMS = [
    ('0', 'Red', 'Red channel (0)'),
    ('1', 'Green', 'Green channel (1)'),
    ('2', 'Blue', 'Blue channel (2)'),
    ('3', 'Alpha', 'Alpha channel (3)'),
]

_FORMAT_ITEMS = [("XD", "XD"), ("COLOSSEUM", "Colosseum")]
_MODEL_TYPE_ITEMS = [("POKEMON", "Pokémon"), ("TRAINER", "Trainer")]
_PARTICLE_ORIENT_ITEMS = [
    ("-2", "Back 180°"), ("-1", "Back 90°"), ("0", "Default"),
    ("1", "Forward 90°"), ("2", "Forward 180°"),
]
_ANIM_TYPE_ITEMS = [
    ("loop", "Loop"), ("hit_reaction", "Hit Reaction"),
    ("action", "Action"), ("compound", "Compound"),
]
_SUB_ANIM_TRIGGER_ITEMS = [
    ("sleep_on", "Sleep On"), ("sleep_off", "Sleep Off"),
    ("extra", "Extra"), ("unused", "Unused"),
]
_BODY_MAP_KEYS = [
    "root", "head", "center", "body_3", "neck", "head_top",
    "limb_a", "limb_b", "secondary_8", "secondary_9",
    "secondary_10", "secondary_11", "attach_a", "attach_b",
    "attach_c", "attach_d",
]
_BODY_MAP_NAMES = [
    "Root", "Head", "Center", "Body Part 3", "Neck", "Head Top",
    "Limb Left", "Limb Right", "Secondary 8", "Secondary 9",
    "Secondary 10", "Secondary 11", "Attachment A", "Attachment B",
    "Attachment C", "Attachment D",
]
_XD_POKEMON_ANIM_NAMES = [
    "Idle", "Special A", "Physical A", "Physical B", "Physical C",
    "Physical D", "Special B", "Physical E", "Damage", "Damage+Faint",
    "Faint", "Idle B", "Special C", "Physical F", "Physical G",
    "Physical H", "Idle Loop B",
]
_XD_TRAINER_ANIM_NAMES = [
    "Idle", "Poké Ball Throw", "Victory", "Battle Intro", "Frustrated",
    "Victory 2", "Slot 6", "Slot 7", "Slot 8", "Slot 9",
    "Defeat", "Slot 11", "Slot 12", "Slot 13", "Slot 14",
    "Slot 15", "Slot 16",
]


def _on_shiny_update(obj, context):
    """Rebuild shiny node groups when toggle or params change."""
    if not obj.dat_pkx_shiny:
        obj.update_tag()
        if context and context.area:
            context.area.tag_redraw()
        return
    route = [int(obj.dat_pkx_shiny_route_r), int(obj.dat_pkx_shiny_route_g),
             int(obj.dat_pkx_shiny_route_b), int(obj.dat_pkx_shiny_route_a)]
    brightness = [obj.dat_pkx_shiny_brightness_r, obj.dat_pkx_shiny_brightness_g,
                  obj.dat_pkx_shiny_brightness_b]
    _shiny_build_route_group(route, _SHINY_ROUTE_GROUP)
    _shiny_build_bright_group(brightness, _SHINY_BRIGHT_GROUP)
    obj.update_tag()
    for child in obj.children:
        if child.type == 'MESH' and child.active_material:
            child.active_material.node_tree.update_tag()
    if context and context.area:
        context.area.tag_redraw()


def _draw_enum_dropdown(layout, obj, prop_key, items, label="", as_int=False):
    """Draw a row of toggle buttons for a custom property enum."""
    current = str(obj.get(prop_key, ""))
    row = layout.row(align=True)
    if label:
        row.label(text=label)
    sub = row.row(align=True)
    for val, lbl in items:
        op = sub.operator("dat.set_enum_prop", text=lbl, depress=(val == current))
        op.prop_key = prop_key
        op.value = val
        op.as_int = as_int


def _prop_row(layout, label, value):
    row = layout.row()
    row.label(text="%s:" % label)
    row.label(text=str(value))


def _register_pkx_panel():
    """Register the PKX Metadata panel and properties if not already registered."""
    from bpy.props import (StringProperty, BoolProperty, EnumProperty,
                           FloatProperty, BoolVectorProperty)

    # Check if already registered (by the addon or a previous script run)
    if hasattr(bpy.types.Object, 'dat_pkx_shiny'):
        return

    # --- Operator for enum dropdowns ---
    class DAT_OT_SetEnumProp(bpy.types.Operator):
        """Set a custom property from an enum dropdown."""
        bl_idname = "dat.set_enum_prop"
        bl_label = "Set Property"
        bl_options = {'UNDO', 'INTERNAL'}
        prop_key: StringProperty()
        value: StringProperty()
        as_int: BoolProperty(default=False)
        def execute(self, context):
            obj = context.active_object
            if obj and self.prop_key:
                obj[self.prop_key] = int(self.value) if self.as_int else self.value
            return {'FINISHED'}

    # --- Panel ---
    class DAT_PT_PKXPanel(bpy.types.Panel):
        """PKX model metadata panel."""
        bl_label = "PKX Metadata"
        bl_idname = "OBJECT_PT_dat_pkx"
        bl_space_type = 'PROPERTIES'
        bl_region_type = 'WINDOW'
        bl_context = "object"

        @classmethod
        def poll(cls, context):
            obj = context.active_object
            return (obj is not None and obj.type == 'ARMATURE'
                    and obj.get("dat_pkx_format") is not None)

        def draw(self, context):
            obj = context.active_object
            layout = self.layout

            # === General ===
            box = layout.box()
            box.label(text="General", icon='INFO')
            _draw_enum_dropdown(box, obj, "dat_pkx_format", _FORMAT_ITEMS, label="Format:")
            if "dat_pkx_species_id" in obj:
                box.prop(obj, '["dat_pkx_species_id"]', text="Species ID")
            _draw_enum_dropdown(box, obj, "dat_pkx_model_type", _MODEL_TYPE_ITEMS, label="Model Type:")
            if "dat_pkx_head_bone" in obj:
                box.prop_search(obj, '["dat_pkx_head_bone"]', obj.data, "bones", text="Head Bone")
            if "dat_pkx_particle_orientation" in obj:
                _draw_enum_dropdown(box, obj, "dat_pkx_particle_orientation",
                                    _PARTICLE_ORIENT_ITEMS, label="Particle Orientation:", as_int=True)

            # === Shiny Variant ===
            box = layout.box()
            box.label(text="Shiny Variant", icon='COLOR')
            box.prop(obj, "dat_pkx_shiny", text="Enable Shiny Preview")
            col = box.column(align=True)
            col.label(text="Channel Routing:")
            row = col.row(align=True)
            row.prop(obj, "dat_pkx_shiny_route_r", text="R")
            row.prop(obj, "dat_pkx_shiny_route_g", text="G")
            row = col.row(align=True)
            row.prop(obj, "dat_pkx_shiny_route_b", text="B")
            row.prop(obj, "dat_pkx_shiny_route_a", text="A")
            col = box.column(align=True)
            col.label(text="Brightness:")
            col.prop(obj, "dat_pkx_shiny_brightness_r", text="Red")
            col.prop(obj, "dat_pkx_shiny_brightness_g", text="Green")
            col.prop(obj, "dat_pkx_shiny_brightness_b", text="Blue")

            # === Flags ===
            box = layout.box()
            box.label(text="Flags", icon='PREFERENCES')
            col = box.column(align=True)
            for flag_key, flag_label in [
                ("dat_pkx_flag_flying", "Flying Mode"),
                ("dat_pkx_flag_skip_frac_frames", "Skip Fractional Frames"),
                ("dat_pkx_flag_no_root_anim", "No Root Joint Animation"),
                ("dat_pkx_flag_bit7", "Unknown (bit 7)"),
            ]:
                if flag_key in obj:
                    col.prop(obj, '["%s"]' % flag_key, text=flag_label)

            # === Body Map ===
            box = layout.box()
            box.label(text="Body Map", icon='BONE_DATA')
            col = box.column(align=True)
            for j, jk in enumerate(_BODY_MAP_KEYS):
                key = "dat_pkx_body_%s" % jk
                if key in obj:
                    label = _BODY_MAP_NAMES[j] if j < len(_BODY_MAP_NAMES) else jk
                    col.prop_search(obj, '["%s"]' % key, obj.data, "bones", text=label)

            # === Animation Slots ===
            anim_count = obj.get("dat_pkx_anim_count", 0)
            if anim_count:
                box = layout.box()
                box.label(text="Animation Slots", icon='ACTION')
                model_type = obj.get("dat_pkx_model_type", "POKEMON")
                slot_names = _XD_TRAINER_ANIM_NAMES if model_type == "TRAINER" else _XD_POKEMON_ANIM_NAMES
                for i in range(anim_count):
                    slot_label = slot_names[i] if i < len(slot_names) else "Slot %d" % i
                    prefix = "dat_pkx_anim_%02d" % i
                    is_expanded = obj.dat_pkx_anim_expand[i] if i < 17 else False
                    header = box.row(align=True)
                    icon = 'TRIA_DOWN' if is_expanded else 'TRIA_RIGHT'
                    header.prop(obj, "dat_pkx_anim_expand", index=i, icon=icon,
                                text=slot_label, emboss=False)
                    sub_count = obj.get(prefix + "_sub_count", 1)
                    first_ref = ""
                    for s in range(min(sub_count, 3)):
                        ref = obj.get(prefix + "_sub_%d_anim" % s, "")
                        if ref:
                            first_ref = ref
                            break
                    if first_ref:
                        header.label(text=first_ref.split('_', 1)[-1] if '_' in first_ref else first_ref)
                    if not is_expanded:
                        continue
                    sub_box = box.box()
                    _draw_enum_dropdown(sub_box, obj, prefix + "_type", _ANIM_TYPE_ITEMS, label="Type:")
                    for s in range(min(sub_count, 3)):
                        anim_key = prefix + "_sub_%d_anim" % s
                        row = sub_box.row(align=True)
                        row.label(text="Action %d:" % (s + 1) if sub_count > 1 else "Action:")
                        if anim_key in obj:
                            row.prop_search(obj, '["%s"]' % anim_key, bpy.data, "actions", text="")
                    anim_type = obj.get(prefix + "_type", "action")
                    if anim_type == "loop":
                        _timing_labels = {1: "Duration"}
                    elif anim_type == "action":
                        _timing_labels = {1: "Wind-up", 2: "Hit", 3: "Duration"}
                    elif anim_type == "hit_reaction":
                        _timing_labels = {1: "Reaction", 2: "Duration"}
                    elif anim_type == "compound":
                        _timing_labels = {1: "Sub 1 Mid", 2: "Sub 1 End", 3: "Sub 2 Mid", 4: "Sub 2 End"}
                    else:
                        _timing_labels = {}
                    if _timing_labels:
                        col = sub_box.column(align=True)
                        for t, label in _timing_labels.items():
                            tk = prefix + "_timing_%d" % t
                            if tk in obj:
                                col.prop(obj, '["%s"]' % tk, text=label)

    # --- Register properties ---
    props = [
        ('dat_pkx_shiny', BoolProperty(
            name="Shiny Preview", default=False, update=_on_shiny_update,
            description="Toggle shiny color variant preview",
        )),
        ('dat_pkx_shiny_route_r', EnumProperty(
            name="Route R", items=_SHINY_CHANNEL_ITEMS, default='0', update=_on_shiny_update,
        )),
        ('dat_pkx_shiny_route_g', EnumProperty(
            name="Route G", items=_SHINY_CHANNEL_ITEMS, default='1', update=_on_shiny_update,
        )),
        ('dat_pkx_shiny_route_b', EnumProperty(
            name="Route B", items=_SHINY_CHANNEL_ITEMS, default='2', update=_on_shiny_update,
        )),
        ('dat_pkx_shiny_route_a', EnumProperty(
            name="Route A", items=_SHINY_CHANNEL_ITEMS, default='3', update=_on_shiny_update,
        )),
        ('dat_pkx_shiny_brightness_r', FloatProperty(
            name="Brightness R", default=0.0, min=-1.0, max=1.0, step=1, precision=3,
            update=_on_shiny_update,
        )),
        ('dat_pkx_shiny_brightness_g', FloatProperty(
            name="Brightness G", default=0.0, min=-1.0, max=1.0, step=1, precision=3,
            update=_on_shiny_update,
        )),
        ('dat_pkx_shiny_brightness_b', FloatProperty(
            name="Brightness B", default=0.0, min=-1.0, max=1.0, step=1, precision=3,
            update=_on_shiny_update,
        )),
        ('dat_pkx_anim_expand', BoolVectorProperty(
            name="Expand Animation Slots", size=17, default=[False] * 17,
        )),
    ]

    for prop_name, prop in props:
        setattr(bpy.types.Object, prop_name, prop)

    bpy.utils.register_class(DAT_OT_SetEnumProp)
    bpy.utils.register_class(DAT_PT_PKXPanel)
    print("  Registered PKX Metadata panel")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__" or True:
    print("=== Prepare for Colosseum/XD Export ===")

    # 0. Register panel + properties if the addon isn't loaded
    _register_pkx_panel()

    # 1. Camera
    cam_created = prepare_camera()
    if not cam_created:
        print("  Battle camera already exists")

    # 2-4. Per-armature steps: PKX metadata, timing, texture formats
    armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE']
    if not armatures:
        print("  No armatures in scene (PKX/timing/texture steps skipped)")

    for arm in armatures:
        # Mesh weight limiting and splitting (before other steps)
        limited, split = prepare_mesh_weights(arm)
        if limited:
            print("  Limited %d vertex weights on '%s'" % (limited, arm.name))
        if split:
            print("  Split meshes into %d regions on '%s'" % (split, arm.name))

        # PKX metadata
        if arm.get("dat_pkx_format"):
            print("  Armature '%s' already has PKX metadata (skipped)" % arm.name)
        else:
            apply_pkx_metadata(arm, format='XD', model_type='POKEMON', species_id=0)

        # Derive animation timing from action durations
        timing_count = derive_timing(arm)
        if timing_count:
            print("  Derived timing for %d animation slot(s) on '%s'" % (timing_count, arm.name))

        # Texture formats
        fmt_count = prepare_texture_formats(arm)
        if fmt_count:
            print("  Set GX format on %d texture(s) on '%s'" % (fmt_count, arm.name))

        # Shiny filter
        shiny_count = prepare_shiny_filter(arm)
        if shiny_count:
            print("  Shiny filter added to %d material(s) on '%s'" % (shiny_count, arm.name))

    # 6. Scene lights (ambient + 3 directional)
    light_count = prepare_lights()
    if light_count:
        print("  Added %d battle light(s)" % light_count)

    print("=== Done ===")
