"""Standalone Blender script: Prepare a scene for Colosseum/XD export.

Run this from Blender's Scripting panel (Text Editor > Run Script) before
exporting. It ensures all objects in the scene have the custom properties
the exporter expects.

The script operates on all objects in the scene — no selection required:
  1. Bakes loc/rot/scale on all armatures and their child meshes so
     `matrix_world` is identity. The exporter rejects unbaked transforms
     because the SRT decomposition of bone matrices loses any shear that
     a non-uniform armature scale combined with edit-bone rotation would
     introduce, drifting bones away from mesh vertices the further you
     walk down the bone chain.
  2. Creates a Debug_Camera if none exists (the PKX camera appears to be
     unused by the game engine; kept for format fidelity pending a confirmed
     camera-less export test — see CLAUDE.md TODO)
  3. Limits vertex bone weights to 3 per vertex (GameCube constraint)
  4. Splits oversized meshes by body region if >25 estimated PObjects
  5. Applies default PKX metadata to all armatures that don't have it
  6. Auto-derives animation timing from action durations
  7. Downscales textures larger than 512×512 proportionally, then
     auto-selects GX texture formats for all armature textures
  8. Inserts shiny filter nodes into all materials (identity defaults, toggle off)
  9. Creates standard battle lighting (1 ambient + 3 directional)

After running, the scene can be exported via File > Export > Gamecube model (.dat).

Requires the DAT plugin addon to be enabled (for registered shiny properties).

This script is fully standalone — no imports from the plugin codebase.
"""
import bpy
import math


# ---------------------------------------------------------------------------
# Bake transforms
# ---------------------------------------------------------------------------
#
# The exporter requires every armature and every mesh parented to one to
# have identity `matrix_world`. Without this, `describe_skeleton` ends up
# decomposing a sheared root-bone world matrix into SRT, silently dropping
# the shear, while `describe_meshes` keeps the same shear baked into vertex
# coordinates via a plain matmul. The two paths then disagree about where
# every bone-skinned vertex sits — small near the root, growing the deeper
# the bone chain goes. Baking transforms upfront via Blender's own
# `transform_apply` removes the asymmetry at its source.

def _is_identity_matrix(m, tol=1e-5):
    """Mirrors the export-side validator's tolerance check so a successful
    bake here cannot fail validation there."""
    for i in range(4):
        for j in range(4):
            expected = 1.0 if i == j else 0.0
            if abs(m[i][j] - expected) > tol:
                return False
    return True


def _apply_world_to_data(obj, world):
    """Bake `world` into obj's data (vertex coords for meshes, bone
    head/tail/roll for armatures). Resolves multi-user data by copying
    the datablock first. Does not touch obj.matrix_basis.

    Both `Mesh.transform()` and `Armature.transform()` are direct data-
    level operations — they don't go through bpy.ops, don't require the
    object to be selected/active/visible, and don't need any particular
    context. Critically for armatures, `Armature.transform()` correctly
    scales bone lengths along with head positions; the previous
    edit-mode `bone.matrix = world @ bone.matrix` approach left lengths
    unchanged, which collapsed the whole skeleton into a tiny region
    (Greninja's 0.01 scale piled all 100+ bones on top of each other,
    visible as "a couple of giant bones").

    Returns True if data was mutated, False if obj has no applicable data.
    """
    if obj.type == 'MESH':
        if obj.data is None:
            return False
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        obj.data.transform(world)
        return True
    elif obj.type == 'ARMATURE':
        if obj.data is None:
            return False
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        obj.data.transform(world)
        return True
    return False


def _ensure_bone_marker_object():
    """Create (or reuse) a 1 cm octahedron object used as the
    `custom_shape` for every pose bone post-bake. Mirrors the default
    OCTAHEDRAL bone display look ("diamondy" shape) but at a fixed 1×1×1
    cm size that does not scale with bone length. The mesh isn't linked
    into any collection — it just needs to exist as a datablock for
    `pose_bone.custom_shape` to reference. Reused across runs by name."""
    name = 'DATPlugin_BoneMarker'
    obj = bpy.data.objects.get(name)
    if obj is not None:
        return obj
    mesh = bpy.data.meshes.get(name)
    if mesh is None or not mesh.vertices:
        if mesh is None:
            mesh = bpy.data.meshes.new(name)
        # Regular octahedron: 6 vertices on the ±X / ±Y / ±Z axes,
        # 8 triangular faces forming a diamond. Total bbox is 1×1×1 cm.
        s = 0.005
        verts = [
            ( s, 0, 0), (-s, 0, 0),
            (0,  s, 0), (0, -s, 0),
            (0, 0,  s), (0, 0, -s),
        ]
        faces = [
            (0, 2, 4), (0, 4, 3), (0, 3, 5), (0, 5, 2),
            (1, 4, 2), (1, 3, 4), (1, 5, 3), (1, 2, 5),
        ]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
    return bpy.data.objects.new(name, mesh)


def _collect_armature_actions(arm):
    """Actions that this armature's animation_data references — active +
    every NLA strip's action. We only scale fcurves on these, not on
    every action in bpy.data.actions, so a second armature's actions
    don't get over-scaled when its scale factor differs."""
    if not arm.animation_data:
        return set()
    actions = set()
    if arm.animation_data.action:
        actions.add(arm.animation_data.action)
    for tr in arm.animation_data.nla_tracks:
        for st in tr.strips:
            if st.action:
                actions.add(st.action)
    return actions


def bake_transforms():
    """Bake loc/rot/scale on every armature and its child meshes so each
    `matrix_world` is identity.

    The naive approach (apply world matrix to data, set matrix_basis to I)
    is *almost* right but breaks animations in two non-obvious ways:

      1. `Armature.transform()` while the action is evaluating leaves the
         pose-matrix cache stale — even after view_layer.update(), pose
         evaluation reads the old rest matrix and produces wildly wrong
         bone positions (Greninja: pose-bone Waist ended up at world Y=94
         instead of Y=0.06). Fix: mute the action and reset all pose-bone
         TRS to identity *before* baking, restore *after*.

      2. PoseBone.location values are in bone-local rest-frame coordinates.
         Pre-bake, the bone's rest frame is scaled by the armature's world
         scale (e.g. 0.01 for Greninja); a pose-loc of 50 means 0.5 m of
         world translation. Post-bake the rest frame has scale 1.0; the
         same 50 now means 50 m. Fix: multiply every pose.bones[].location
         fcurve keyframe by the armature's pre-bake scale factor. Pose
         rotations and scales are dimensionless and need no adjustment.

    Also handles per-view-layer hidden objects (`hide_get() == True`) by
    temporarily unhiding them, since several Blender ops — and even
    `Armature.transform()` in some contexts — silently no-op on objects
    that aren't `visible_get()`.

    Returns the number of objects baked.
    """
    from mathutils import Matrix as _Matrix
    import re

    armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE']
    if not armatures:
        return 0

    # ------------------------------------------------------------------
    # Step 0: snapshot animation + visibility state, then neutralise it.
    # ------------------------------------------------------------------
    saved_anim = []     # one entry per armature
    saved_hide = []     # (obj, was_hidden_per_view_layer)
    for arm in armatures:
        ad = arm.animation_data
        anim_snapshot = {
            'arm': arm,
            'scale': arm.matrix_world.to_scale().x,  # uniform scale assumed
            'actions': _collect_armature_actions(arm),
            'action': ad.action if ad else None,
            'use_nla': ad.use_nla if ad else None,
            'pose': [
                (pb.name,
                 pb.location.copy(),
                 pb.rotation_quaternion.copy(),
                 pb.rotation_euler.copy(),
                 pb.rotation_axis_angle[:],
                 pb.scale.copy())
                for pb in arm.pose.bones
            ],
        }
        saved_anim.append(anim_snapshot)
        # Mute the animation source of pose evaluation
        if ad:
            ad.action = None
            ad.use_nla = False
        for pb in arm.pose.bones:
            pb.location = (0, 0, 0)
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.rotation_euler = (0, 0, 0)
            pb.rotation_axis_angle = (0, 0, 1, 0)
            pb.scale = (1, 1, 1)

    # Force-unhide every relevant object so silent visibility-gated no-ops
    # can't bite us. We restore at the end.
    for arm in armatures:
        if arm.hide_get():
            saved_hide.append((arm, True))
            arm.hide_set(False)
        for obj in bpy.data.objects:
            if obj.parent is arm and obj.type == 'MESH' and obj.hide_get():
                saved_hide.append((obj, True))
                obj.hide_set(False)

    bpy.context.view_layer.update()

    # ------------------------------------------------------------------
    # Step 1: capture world matrices BEFORE mutation. matrix_world is
    # cached and re-reading it after a sibling object is baked returns
    # half-stale values.
    # ------------------------------------------------------------------
    targets = []
    for arm in armatures:
        targets.append((arm, arm.matrix_world.copy()))
        for obj in bpy.data.objects:
            if obj.parent is arm and obj.type == 'MESH':
                targets.append((obj, obj.matrix_world.copy()))

    # ------------------------------------------------------------------
    # Step 2: bake each target using its captured world.
    # ------------------------------------------------------------------
    baked = 0
    identity = _Matrix.Identity(4)
    for obj, world in targets:
        if _is_identity_matrix(world):
            obj.matrix_basis = identity
            if obj.parent is not None:
                obj.matrix_parent_inverse = identity
            continue
        if not _apply_world_to_data(obj, world):
            continue
        obj.matrix_basis = identity
        if obj.parent is not None:
            obj.matrix_parent_inverse = identity
        baked += 1

    # ------------------------------------------------------------------
    # Step 2b: replace each bone's display with a 1 cm cube custom shape.
    # OCTAHEDRAL/BBONE/STICK all extend the bone display along its full
    # head→tail length — for Greninja's 95 cm Origin bone that's a 95 cm-
    # tall display element, visually dominant over the 1.7 m mesh. A
    # custom_shape with use_custom_shape_bone_size=False renders a fixed-
    # size cube at each joint regardless of bone length, restoring the
    # tidy "tiny markers" look the pre-bake 0.01-scale armature gave by
    # accident.
    bone_marker = _ensure_bone_marker_object()
    for arm in armatures:
        for pb in arm.pose.bones:
            pb.custom_shape = bone_marker
            # `use_custom_shape_bone_size` defaults to False in Blender 4.x
            # (shape NOT scaled by bone length). Set explicitly anyway in
            # case a future Blender flips the default.
            pb.use_custom_shape_bone_size = False
            pb.custom_shape_scale_xyz = (1.0, 1.0, 1.0)

    # ------------------------------------------------------------------
    # Step 3: scale every pose.bones[...].location fcurve by the
    # armature's pre-bake world scale. Pose rotations and scales need no
    # adjustment (they're dimensionless).
    # ------------------------------------------------------------------
    loc_re = re.compile(r'^pose\.bones\[".*"\]\.location$')
    for snap in saved_anim:
        s = snap['scale']
        if abs(s - 1.0) < 1e-6:
            continue  # armature was already at unit scale, nothing to do
        for action in snap['actions']:
            for fc in action.fcurves:
                if not loc_re.match(fc.data_path):
                    continue
                for kp in fc.keyframe_points:
                    kp.co.y *= s
                    kp.handle_left.y *= s
                    kp.handle_right.y *= s
        # Also scale the snapshotted pose-loc values we'll restore below
        snap['pose'] = [
            (name, (loc[0]*s, loc[1]*s, loc[2]*s), quat, eul, aa, scl)
            for (name, loc, quat, eul, aa, scl) in snap['pose']
        ]

    # ------------------------------------------------------------------
    # Step 4: restore animation + pose state.
    # ------------------------------------------------------------------
    for snap in saved_anim:
        arm = snap['arm']
        ad = arm.animation_data
        if ad:
            ad.action = snap['action']
            if snap['use_nla'] is not None:
                ad.use_nla = snap['use_nla']
        for (name, loc, quat, eul, aa, scl) in snap['pose']:
            pb = arm.pose.bones.get(name)
            if pb is None:
                continue
            pb.location = loc
            pb.rotation_quaternion = quat
            pb.rotation_euler = eul
            pb.rotation_axis_angle = aa
            pb.scale = scl

    # Restore visibility
    for obj, _was_hidden in saved_hide:
        obj.hide_set(True)

    bpy.context.view_layer.update()

    # ------------------------------------------------------------------
    # Step 5: verify.
    # ------------------------------------------------------------------
    offenders = [
        obj.name for obj, _ in targets
        if not _is_identity_matrix(obj.matrix_world)
    ]
    if offenders:
        raise RuntimeError(
            "Failed to bake transforms to identity on: "
            + ", ".join(offenders) + ". The object's data may be linked "
            "from another .blend, or its data is None. Open the offending "
            "object in the Outliner to investigate."
        )

    return baked


# ---------------------------------------------------------------------------
# Debug camera
# ---------------------------------------------------------------------------
#
# Both the XD and Colosseum disassemblies show no real consumer of the PKX
# model's embedded camera — battles, summary screens, PC box, and overworld
# all use hardcoded or bounding-box-derived cameras. The camera section is
# most likely a SysDolphin-era debug/preview camera that the format
# preserves but the game ignores. We still emit one to keep the DAT
# structure identical to official models until a camera-less export is
# confirmed working in-game.

DEBUG_CAMERA_NAME = "Debug_Camera"
DEBUG_CAMERA_TARGET = "Debug_Camera_target"


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
    """Create a default debug camera if none exists, and set aspect on all cameras.

    Returns the number of cameras created (0 or 1).
    """
    created = 0

    # Create Debug_Camera if it doesn't exist
    if bpy.data.objects.get(DEBUG_CAMERA_NAME) is None:
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

        cam_data = bpy.data.cameras.new(DEBUG_CAMERA_NAME)
        cam_data.type = 'PERSP'
        cam_data.lens = 37.5       # ~27° vertical FOV (most common across all PKX models)
        cam_data.clip_start = 0.01
        cam_data.clip_end = 3277.0

        cam_obj = bpy.data.objects.new(DEBUG_CAMERA_NAME, cam_data)
        cam_obj.location = cam_pos
        cam_obj["dat_camera_aspect"] = 1.18
        bpy.context.scene.collection.objects.link(cam_obj)

        # Create target empty at model center
        target = bpy.data.objects.new(DEBUG_CAMERA_TARGET, None)
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
        print("  Created '%s' in front of model, targeting center" % DEBUG_CAMERA_NAME)
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

    # Shiny registered properties — cyclic RGB swap (R→G→B→R) with a warm
    # brightness boost, so fresh exports ship with a visible shiny variant.
    armature.dat_pkx_shiny = False
    armature.dat_pkx_shiny_route_r = '2'
    armature.dat_pkx_shiny_route_g = '0'
    armature.dat_pkx_shiny_route_b = '1'
    armature.dat_pkx_shiny_route_a = '3'
    armature.dat_pkx_shiny_brightness_r = 0.2
    armature.dat_pkx_shiny_brightness_g = 0.2
    armature.dat_pkx_shiny_brightness_b = 0.0

    # --- Sub-animations (all inactive) ---
    sub_triggers = ["sleep_on", "sleep_off", "extra", "unused"]
    for i in range(4):
        prefix = "dat_pkx_sub_anim_%d" % i
        armature[prefix + "_type"] = "none"
        armature[prefix + "_trigger"] = sub_triggers[i]
        armature[prefix + "_anim_ref"] = ""

    # --- Body map bones ---
    # The game uses 16 slots but only slots 0-7 are actively referenced by the
    # XD battle code (root, head tracking, particle/effect attachment points).
    # Slots 8-15 are unreferenced and always exported as -1 (skip).
    bones = list(armature.data.bones)
    root_name = bones[0].name if bones else ""
    armature["dat_pkx_body_root"] = root_name
    armature["dat_pkx_body_head"] = head_bone_name
    armature["dat_pkx_body_center"] = ""
    for key in ["body_3", "neck", "head_top", "limb_a", "limb_b"]:
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
# Texture sizing
# ---------------------------------------------------------------------------

MAX_TEXTURE_DIM = 512


def prepare_texture_sizes(armature):
    """Downscale any texture larger than MAX_TEXTURE_DIM on either axis.

    Scales proportionally so the larger dimension becomes MAX_TEXTURE_DIM.
    UVs are in normalized [0, 1] space in Blender, so no UV remap is needed.

    Returns the number of images that were rescaled.
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
                if node.bl_idname != 'ShaderNodeTexImage' or not node.image:
                    continue
                img = node.image
                if img.name in images_seen:
                    continue
                images_seen.add(img.name)

                w, h = img.size[0], img.size[1]
                if w <= MAX_TEXTURE_DIM and h <= MAX_TEXTURE_DIM:
                    continue
                if w == 0 or h == 0:
                    continue

                ratio = min(MAX_TEXTURE_DIM / w, MAX_TEXTURE_DIM / h)
                new_w = max(1, int(w * ratio))
                new_h = max(1, int(h * ratio))
                img.scale(new_w, new_h)
                count += 1
                print("    %s: %dx%d -> %dx%d" %
                      (img.name, w, h, new_w, new_h))

    return count


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


def _shiny_no_texture_in_color_chain(target_input):
    """True when no ShaderNodeTexImage is reachable from the shader color input.

    The in-game shiny color swap operates on GX texture swap tables; without
    a texture sample in the chain there is nothing to swizzle, and the
    brightness modulation on a constant-colour chain reads as untouched
    compared to the saturated re-tint textured materials get. Materials
    matching this shape are skipped so the shader-side simulation matches
    the in-game behaviour.

    An unlinked target input (default-valued Base Color) is also treated
    as "no texture" — still a pure constant-colour chain.
    """
    if not target_input.is_linked:
        return True
    visited = set()
    stack = [target_input]
    while stack:
        sock = stack.pop()
        for link in sock.links:
            node = link.from_node
            if id(node) in visited:
                continue
            visited.add(id(node))
            if node.type == 'TEX_IMAGE':
                return False
            for inp in node.inputs:
                if inp.is_linked:
                    stack.append(inp)
    return True


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
            if _shiny_no_texture_in_color_chain(target_input):
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

# Opt-in knob (HSDLib parity, `POBJ_Generator.ClampWeight`). When True, any
# vertex weight below 0.1 is removed and its slack redistributed to the
# dominant bone before quantization — prevents GLB-rip long-tail weight
# distributions from collapsing to sum<1.0 after 10% rounding. Leave False
# to preserve exact game-model round-trips; flip to True when testing
# arbitrary rips that exhibit shrunken / floating vertices.
REDISTRIBUTE_SUB_0_1_WEIGHTS = False


def prepare_mesh_weights(armature):
    """Optimize mesh weights for GameCube export.

    1. Limits all vertices to MAX_WEIGHTS_PER_VERTEX bone influences.
    2. Quantizes weights to 10% steps (matching game model precision).
    3. Separates single-bone vertices into rigid meshes per bone,
       leaving only multi-bone vertices in the envelope mesh.

    This produces the same structure as game models: many small RIGID
    meshes (1 PObject each, no envelope overhead) + smaller envelope
    meshes at joints.

    Returns (weights_limited, rigid_meshes_created) counts.
    """
    bone_names = {b.name for b in armature.data.bones}
    meshes = [obj for obj in bpy.data.objects
              if obj.type == 'MESH' and obj.parent == armature]

    total_limited = 0
    total_rigid = 0

    for mesh_obj in meshes:
        bpy.ops.object.select_all(action='DESELECT')
        mesh_obj.select_set(True)
        bpy.context.view_layer.objects.active = mesh_obj

        # Step 1: Limit weights
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

        # Step 2a: Drop sub-0.1 weights and redistribute their slack to the
        # dominant bone of each vertex (opt-in, HSDLib ClampWeight parity).
        if REDISTRIBUTE_SUB_0_1_WEIGHTS:
            redistributed = 0
            for v in mesh_obj.data.vertices:
                bone_groups = [g for g in v.groups
                               if g.group < len(mesh_obj.vertex_groups)
                               and mesh_obj.vertex_groups[g.group].name in bone_names
                               and g.weight > 0.0]
                small = [g for g in bone_groups if g.weight < 0.1]
                if not small or len(small) == len(bone_groups):
                    continue
                slack = sum(g.weight for g in small)
                dominant = max(bone_groups, key=lambda g: g.weight)
                for g in small:
                    g.weight = 0.0
                dominant.weight = min(1.0, dominant.weight + slack)
                redistributed += 1
            if redistributed:
                print("    %s: redistributed sub-0.1 weights on %d vertices" %
                      (mesh_obj.name, redistributed))

        # Step 2: Quantize weights to 10% steps
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
            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
            bpy.ops.object.vertex_group_normalize_all(lock_active=False)
            bpy.ops.object.mode_set(mode='OBJECT')
            for v in mesh_data.vertices:
                for g in v.groups:
                    if g.group < len(mesh_obj.vertex_groups):
                        if mesh_obj.vertex_groups[g.group].name in bone_names:
                            g.weight = round(g.weight, 1)
            print("    %s: quantized %d weight values to 10%% steps" %
                  (mesh_obj.name, quantized))

    return total_limited, 0


def _split_rigid_from_envelope(mesh_obj, armature, bone_names):
    """Separate single-bone vertices into per-bone rigid meshes.

    Vertices weighted to exactly one bone are grouped by that bone and
    separated into individual mesh objects. The remaining multi-bone
    vertices stay in the original mesh for envelope skinning.

    Returns the number of rigid meshes created.
    """
    mesh_data = mesh_obj.data

    # Classify each vertex: single-bone → bone name, multi-bone → None
    vertex_bone = {}  # {vertex_index: bone_name or None}
    for v in mesh_data.vertices:
        bones = [(mesh_obj.vertex_groups[g.group].name, g.weight)
                 for g in v.groups
                 if g.group < len(mesh_obj.vertex_groups)
                 and mesh_obj.vertex_groups[g.group].name in bone_names
                 and g.weight > 0.0]
        if len(bones) == 1:
            vertex_bone[v.index] = bones[0][0]
        else:
            vertex_bone[v.index] = None

    # Group single-bone vertices by bone name
    bone_vertices = {}  # {bone_name: set of vertex indices}
    for vi, bone_name in vertex_bone.items():
        if bone_name is not None:
            if bone_name not in bone_vertices:
                bone_vertices[bone_name] = set()
            bone_vertices[bone_name].add(vi)

    if not bone_vertices:
        return 0

    # Only split bones that have enough vertices to form faces.
    # A bone group needs at least 3 vertices to possibly form a triangle.
    splittable = {bn: vis for bn, vis in bone_vertices.items() if len(vis) >= 3}
    if not splittable:
        return 0

    # Check which bone groups actually have faces (all face vertices in the group)
    face_bone_groups = {}
    for poly in mesh_data.polygons:
        poly_verts = set(poly.vertices)
        # Check if ALL vertices of this face belong to the same single bone
        face_bones = set()
        for vi in poly_verts:
            b = vertex_bone.get(vi)
            if b is None:
                face_bones = None
                break
            face_bones.add(b)
        if face_bones and len(face_bones) == 1:
            bone = next(iter(face_bones))
            if bone not in face_bone_groups:
                face_bone_groups[bone] = 0
            face_bone_groups[bone] += 1

    if not face_bone_groups:
        return 0

    # Sort by face count descending — split largest groups first
    bones_to_split = sorted(face_bone_groups.keys(),
                            key=lambda b: -face_bone_groups[b])

    created = 0
    original_name = mesh_obj.name

    for bone_name in bones_to_split:
        # Re-get active mesh (may have changed after previous splits)
        mesh_obj = bpy.context.view_layer.objects.active
        if mesh_obj is None or mesh_obj.type != 'MESH':
            break

        # Select vertices for this bone group
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')

        vis = bone_vertices[bone_name]
        for v in mesh_obj.data.vertices:
            v.select = v.index in vis

        bpy.ops.object.mode_set(mode='EDIT')
        try:
            bpy.ops.mesh.separate(type='SELECTED')
        except RuntimeError:
            bpy.ops.object.mode_set(mode='OBJECT')
            continue
        bpy.ops.object.mode_set(mode='OBJECT')

        # Name the new mesh and ensure armature modifier
        for obj in bpy.context.selected_objects:
            if obj != mesh_obj and obj.type == 'MESH':
                obj.name = "%s_%s" % (original_name, bone_name)
                if not any(m.type == 'ARMATURE' for m in obj.modifiers):
                    mod = obj.modifiers.new('Armature', 'ARMATURE')
                    mod.object = armature

        created += 1

        # Rebuild vertex_bone mapping for the reduced mesh
        # (vertex indices are renumbered after separate)
        new_vertex_bone = {}
        for v in mesh_obj.data.vertices:
            bones = [(mesh_obj.vertex_groups[g.group].name, g.weight)
                     for g in v.groups
                     if g.group < len(mesh_obj.vertex_groups)
                     and mesh_obj.vertex_groups[g.group].name in bone_names
                     and g.weight > 0.0]
            if len(bones) == 1:
                new_vertex_bone[v.index] = bones[0][0]
            else:
                new_vertex_bone[v.index] = None
        vertex_bone = new_vertex_bone

        # Rebuild bone_vertices for remaining bones
        bone_vertices = {}
        for vi, bn in vertex_bone.items():
            if bn is not None:
                if bn not in bone_vertices:
                    bone_vertices[bn] = set()
                bone_vertices[bn].add(vi)

    return created


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
    "Physical D", "Special B", "Physical E", "Damage", "Damage B",
    "Faint", "Extra 1", "Special C", "Extra 2", "Extra 3", "Extra 4",
    "Take Flight",
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

    # 1. Bake loc/rot/scale on armatures + child meshes. Must run before
    #    anything else so subsequent prep + the exporter itself see clean
    #    identity matrix_world on every relevant object.
    baked = bake_transforms()
    if baked:
        print("  Baked transforms on %d object(s) [direct data mutation]" % baked)
        # Sanity-print a sample bone + vertex magnitude so the user can
        # eyeball whether bones and meshes ended up at the same scale.
        # If they're orders of magnitude apart, the loaded script version
        # is wrong (Text Editor caches the buffer; click Text > Reload).
        for arm in (o for o in bpy.data.objects if o.type == 'ARMATURE'):
            child = next((o for o in bpy.data.objects
                          if o.parent is arm and o.type == 'MESH' and o.data and o.data.vertices),
                         None)
            if child is None:
                continue
            longest = max((b.length for b in arm.data.bones), default=0.0)
            v = max((v.co.length for v in child.data.vertices), default=0.0)
            print("    %s: longest bone = %.3f, max mesh vertex = %.3f"
                  % (arm.name, longest, v))

    # 2. Camera — disabled: both XD and Colosseum disassemblies show no
    # consumer of the PKX camera. Keep prepare_camera() available until a
    # camera-less PKX export is confirmed in-game.
    # cam_created = prepare_camera()
    # if not cam_created:
    #     print("  Debug camera already exists")

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

        # Texture sizes (downscale >512 before format analysis)
        size_count = prepare_texture_sizes(arm)
        if size_count:
            print("  Downscaled %d texture(s) on '%s'" % (size_count, arm.name))

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
