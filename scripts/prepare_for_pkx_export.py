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
  2. Stamps a default `dat_camera_aspect` on any scene camera missing one
     (camera creation lives in scripts/add_debug_camera.py)
  3. Limits vertex bone weights to 3 per vertex (GameCube constraint)
  4. Splits oversized meshes by body region if >25 estimated PObjects
  5. Applies default PKX metadata to all armatures that don't have it
  6. Auto-derives animation timing from action durations
  7. Downscales textures larger than 512×512 proportionally, then
     auto-selects GX texture formats for all armature textures
  8. Inserts shiny filter nodes into all materials (identity defaults, toggle off)
  9. Authors two helper actions per armature for in-game smoke testing:
       - `auto_animation_dummy` — two-frame identity pose (placeholder for
         empty slots; the game requires at least two keyframes per channel)
       - `auto_animation_spin` — 60-frame full revolution around the rig's
         vertical axis on the root bone, with frame 0 == frame 60 (mod 2π)
         so the loop closes cleanly
     These are not assigned to any PKX slot — pick them by hand in the PKX
     Metadata panel only when smoke-testing a model. They should be ignored
     for normal authoring.
 10. Creates standard battle lighting (1 ambient + 3 directional)

After running, the scene can be exported via File > Export > Gamecube model (.dat).

Requires the DAT plugin addon to be enabled (for registered shiny properties).

This script is fully standalone — no imports from the plugin codebase.
"""
import bpy
import math


# ---------------------------------------------------------------------------
# Optimisation knobs
# ---------------------------------------------------------------------------
#
# Trade visual fidelity for in-game performance. Lower values reduce
# PObject count, matrix-pool usage, and file size — critical for arbitrary
# (non-XD-native) model exports because the game's renderer chokes when
# these go past empirically observed caps. Game-native PKX bodies sit
# around 8–15 PObjects per material; if a prepped model's largest mesh
# lands well above that in the export log, tighten the knobs and re-prep.

# Hard cap on bone influences per vertex. GX hardware allows up to 4
# (PNMTXIDX selects from 4 blend weights). Game models commonly use 2 or
# 3 to keep envelope-combination explosion in check.
MAX_WEIGHTS_PER_VERTEX = 3

# Step size for weight quantisation, in absolute weight units (0..1).
# Larger steps collapse more near-identical envelopes into one, shrinking
# the unique-envelope count and the resulting PObject split. 0.1 matches
# the precision the game itself stores; 0.25 is much more aggressive and
# the right starting point for high-bone-count rips.
WEIGHT_QUANTISATION_STEP = 0.1

# Opt-in (HSDLib parity, `POBJ_Generator.ClampWeight`). When True, any
# vertex weight below WEIGHT_DROP_THRESHOLD is removed and its slack
# redistributed to the dominant bone before quantisation — prevents
# GLB-rip long-tail weight distributions from collapsing to sum<1.0
# after rounding. Leave False to preserve exact game-model round-trips;
# flip True for arbitrary rips that exhibit shrunken / floating vertices.
REDISTRIBUTE_SUB_THRESHOLD_WEIGHTS = False
WEIGHT_DROP_THRESHOLD = 0.1

# Maximum texture dimension on either axis; larger textures are
# downscaled proportionally. GX hardware cap is 1024×1024, but XD's
# texture-memory budget makes 512 the practical safe ceiling.
MAX_TEXTURE_DIM = 512


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
    scales bone lengths along with head positions; the alternative
    edit-mode `bone.matrix = world @ bone.matrix` approach leaves lengths
    unchanged, which on a small-scale rig collapses the whole skeleton
    into a tiny region.

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


def exit_armature_edit_modes():
    """Return every armature in the scene from Edit/Pose mode to Object mode.

    Must run before anything else. A from-scratch rig is frequently left
    mid-edit (placing bones) or in Pose mode, and the global mode is not
    Object mode in that state. Two things break otherwise:
      - The first operator in the prep flow, `bpy.ops.object.select_all`,
        fails its poll with "context is incorrect" (operator polls require
        Object mode).
      - `bake_transforms` mutates mesh/armature *data* directly; edits made
        while an object is in Edit mode are silently overwritten when the
        edit session is later flushed back, so the bake would be lost.

    `mode_set` acts on the active object, so each armature is made active via
    a context override before switching; leaving Object mode for the active
    object drops the whole scene to Object mode. Returns the count switched.
    """
    exited = 0
    for arm in [o for o in bpy.data.objects if o.type == 'ARMATURE']:
        if arm.mode == 'OBJECT':
            continue
        try:
            with bpy.context.temp_override(active_object=arm, object=arm):
                bpy.ops.object.mode_set(mode='OBJECT')
            exited += 1
        except RuntimeError:
            pass
    return exited


def bake_transforms():
    """Bake loc/rot/scale on every armature and its child meshes so each
    `matrix_world` is identity.

    The naive approach (apply world matrix to data, set matrix_basis to I)
    is *almost* right but breaks animations in two non-obvious ways:

      1. `Armature.transform()` while the action is evaluating leaves the
         pose-matrix cache stale — even after view_layer.update(), pose
         evaluation reads the old rest matrix and produces wildly wrong
         bone positions. Fix: mute the action and reset all pose-bone TRS
         to identity *before* baking, restore *after*.

      2. PoseBone.location values are in bone-local rest-frame coordinates.
         Pre-bake, the bone's rest frame is scaled by the armature's world
         scale; a pose-loc of 50 on a scale-0.01 rig means 0.5 m of world
         translation. Post-bake the rest frame has scale 1.0; the same 50
         now means 50 m. Fix: multiply every pose.bones[].location fcurve
         keyframe by the armature's pre-bake scale factor. Pose rotations
         and scales are dimensionless and need no adjustment.

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

    # Flush the depsgraph so matrix_world reflects any caller-set transform
    # (e.g. a freshly-assigned obj.scale). matrix_world is a cached property;
    # without this, the Step-0 snapshot below reads a stale identity scale and
    # the Step-3 translation-fcurve rescale is silently skipped — leaving
    # animated bone translations at their pre-scale magnitude.
    bpy.context.view_layer.update()

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
                # Bone-parented meshes (a holder-bone owner, see
                # reparent_meshes_to_holder_bones) are deliberately hung off a
                # bone rather than the armature object. The object-parent bake
                # below would force matrix_parent_inverse to identity and leave
                # matrix_world at the bone's tail transform — moving the mesh
                # and failing the identity verify. Their geometry was already
                # baked to world space on the first prep pass while they were
                # still object-parented, so skip them here.
                if obj.parent_type == 'BONE':
                    continue
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
    # head→tail length — on a rig with long root bones the display element
    # becomes visually dominant over the mesh itself. A custom_shape with
    # use_custom_shape_bone_size=False renders a fixed-size cube at each
    # joint regardless of bone length, giving a consistent marker display.
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
    # Step 3: scale every translation fcurve by the armature's pre-bake
    # world scale. Covers both pose-bone translations
    # (`pose.bones["…"].location`) and object-level translations
    # (`location`). Rotations and scales are dimensionless and need no
    # adjustment.
    #
    # Actions are scoped per armature: an action belongs to an armature
    # if any pose-bone fcurve names a bone on that armature, or if it's
    # referenced via animation_data on the armature itself or one of its
    # child meshes. A `seen` set prevents double-scaling when actions are
    # somehow shared across rigs.
    # ------------------------------------------------------------------
    pose_bone_path_re = re.compile(r'^pose\.bones\["([^"]+)"\]\.')
    loc_path_re = re.compile(r'^(pose\.bones\[".*"\]\.location|location)$')
    seen = set()
    for snap in saved_anim:
        s = snap['scale']
        if abs(s - 1.0) < 1e-6:
            continue
        arm = snap['arm']
        bone_names = {b.name for b in arm.data.bones}

        owned = set()
        for obj in (arm, *(o for o in bpy.data.objects if o.parent is arm)):
            ad = obj.animation_data
            if not ad:
                continue
            if ad.action:
                owned.add(ad.action)
            for tr in ad.nla_tracks:
                for st in tr.strips:
                    if st.action:
                        owned.add(st.action)
        for action in bpy.data.actions:
            if action in owned:
                continue
            for fc in action.fcurves:
                m = pose_bone_path_re.match(fc.data_path)
                if m and m.group(1) in bone_names:
                    owned.add(action)
                    break

        for action in owned:
            if action in seen:
                continue
            seen.add(action)
            for fc in action.fcurves:
                if not loc_path_re.match(fc.data_path):
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
# Mesh-owner / deformer separation (envelope invariant)
# ---------------------------------------------------------------------------
#
# Game-native models keep two joint roles strictly disjoint: a *mesh-owner*
# joint carries JOBJ_ENVELOPE_MODEL (a mesh hangs off it) and has no
# SKELETON flag / inverse-bind matrix, while a *deformer* joint carries
# JOBJ_SKELETON + an IBM (vertices are weighted to it) and owns no mesh.
# Across 76 surveyed game PKX files, zero envelope weights ever target a
# mesh-owner joint and no joint is ever both ENVELOPE_MODEL and SKELETON.
#
# Arbitrary rips violate this. A detached mesh weighted ~100% to one bone
# (eyes, hair strands) is also *attached* to that bone, so the exporter's
# refine_bone_flags strips SKELETON from it; the envelope coordinate-system
# math then can't resolve the bone as its own deformer, walks up to the
# nearest skeleton ancestor, and the mesh renders offset ("floating") in
# game while round-trips and Blender previews (which use the full skinning
# path for everyone) look fine.
#
# The fix mirrors the game structure: for every mesh whose export owner
# bone is also a deformer, insert a no-weight holder bone as a child of
# that deformer and bone-parent the mesh to the holder. Owner becomes the
# holder (ENV_MODEL, no weights → no SKELETON/IBM); the original bone stays
# a pure deformer. Done here in prep — not in the exporter IR — so the
# whole describe→plan→compose pipeline (and the PKX header's name→index
# body-map resolution) just sees the final armature with correct
# depth-first indices, no index remapping required.


def reparent_meshes_to_holder_bones(armature):
    """Enforce the mesh-owner/deformer disjoint invariant for `armature`.

    For each child mesh whose export owner bone (Blender bone-parent if
    set, else the nearest common ancestor of the bones it is weighted to)
    is itself an envelope weight target, create a coincident no-weight
    holder bone as a child of that deformer and bone-parent the mesh to
    it. Idempotent: on a second pass the meshes already own a (non-deformer)
    holder, so nothing matches.

    Returns the number of holder bones created.
    """
    import bpy

    arm_data = armature.data
    if not arm_data.bones:
        return 0
    bone_names = {b.name for b in arm_data.bones}
    root_name = arm_data.bones[0].name
    parent_of = {b.name: (b.parent.name if b.parent else None)
                 for b in arm_data.bones}

    def ancestors(name):
        chain = []
        while name is not None:
            chain.append(name)
            name = parent_of.get(name)
        return chain

    meshes = [o for o in bpy.data.objects
              if o.parent is armature and o.type == 'MESH']

    # Deformer set + per-mesh weighted bones (non-zero weights only).
    deformers = set()
    mesh_weighted = {}
    for m in meshes:
        idx_to_name = {vg.index: vg.name for vg in m.vertex_groups}
        weighted = set()
        for v in m.data.vertices:
            for g in v.groups:
                if g.weight > 0.0:
                    nm = idx_to_name.get(g.group)
                    if nm in bone_names:
                        weighted.add(nm)
        mesh_weighted[m] = weighted
        deformers |= weighted

    def owner_of(m):
        # Explicit Blender bone-parent wins — mirrors describe's
        # _determine_parent_bone_name.
        if m.parent_type == 'BONE' and m.parent_bone in bone_names:
            return m.parent_bone
        weighted = mesh_weighted.get(m, set())
        if not weighted:
            return root_name
        chains = [set(ancestors(n)) for n in weighted]
        common = set.intersection(*chains)
        if not common:
            return root_name
        # Nearest common ancestor = deepest = first match walking up from
        # any one weighted bone.
        for n in ancestors(next(iter(weighted))):
            if n in common:
                return n
        return root_name

    need = {}
    for m in meshes:
        owner = owner_of(m)
        if owner in deformers:
            need.setdefault(owner, []).append(m)

    if not need:
        return 0

    # Create holder bones (edit mode), coincident with their deformer so
    # the rest transform matches and the importer-validated coordinate path
    # applies. Parent to the root bone (not to the deformer) so the holder's
    # animated pose stays at rest in Blender's evaluator — otherwise the
    # mesh, bone-parented to the holder, would inherit the deformer's pose
    # at the object level *and* receive it again through the Armature
    # modifier's vertex weights, producing a double transform for any vert
    # weighted to that deformer. The in-game envelope math doesn't read the
    # owner's pose (it uses the nearest SKELETON ancestor of each weighted
    # bone), so the disjoint-owner invariant is preserved regardless of
    # where in the tree the holder sits.
    holder_for = {}
    prev_active = bpy.context.view_layer.objects.active
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm_data.edit_bones
    root_eb = eb[root_name]
    for owner in need:
        o = eb[owner]
        h = eb.new("%s_mesh" % owner)
        h.head = o.head.copy()
        h.tail = o.tail.copy()
        h.roll = o.roll
        h.parent = root_eb
        h.use_connect = False
        holder_for[owner] = h.name  # Blender may suffix on collision
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = prev_active
    bpy.context.view_layer.update()

    # Bone-parent each mesh to its holder while preserving world geometry.
    # Blender's high-level `m.matrix_world = world` setter for
    # bone-parented objects leaves a residual that exceeds the 1e-5
    # export validator tolerance on some rigs. The robust approach:
    #
    #   1. Apply the world transform to the mesh data while the mesh is
    #      object-parented (matrix_world is whatever it is — usually
    #      identity after the prior bake — and the data.transform() call
    #      bakes that into the vertices).
    #   2. Reset matrix_basis/matrix_parent_inverse so matrix_world is
    #      cleanly identity in object-parent space.
    #   3. Switch parent_type to 'BONE' and pin matrix_parent_inverse to
    #      the inverse of the bone's effective rest matrix (head matrix
    #      composed with the tail offset). That makes Blender's chain
    #      evaluation produce matrix_world = identity exactly — no
    #      iterative solve, no float-precision drift.
    #
    # This relies on PBR-imported meshes potentially sharing Mesh data
    # blocks (`skin_2800` + three duplicates pointing at one Mesh): copy
    # the data to single-user before transforming so the bake doesn't
    # leak into siblings.
    from mathutils import Matrix as _Matrix
    _identity = _Matrix.Identity(4)
    for owner, mlist in need.items():
        hname = holder_for[owner]
        bpy.context.view_layer.update()
        pose_bone = armature.pose.bones.get(hname)
        if pose_bone is None:
            continue
        tail_offset = _Matrix.Translation((0.0, pose_bone.bone.length, 0.0))
        bone_rest_inv = (armature.matrix_world
                         @ pose_bone.matrix
                         @ tail_offset).inverted()

        for m in mlist:
            # 1. Bake current world (typically identity) into the mesh data.
            world = m.matrix_world.copy()
            if not _is_identity_matrix(world):
                if m.data is not None:
                    if m.data.users > 1:
                        m.data = m.data.copy()
                    m.data.transform(world)
            # 2. Cleanly clear object-level transforms.
            m.matrix_basis = _identity
            if m.parent is not None:
                m.matrix_parent_inverse = _identity
            # 3. Switch to bone parenting and pin matrix_parent_inverse so
            #    the bone-tail offset cancels out, leaving matrix_world at
            #    identity without depending on Blender's matrix_world
            #    setter.
            m.parent = armature
            m.parent_type = 'BONE'
            m.parent_bone = hname
            m.matrix_parent_inverse = bone_rest_inv
            m.matrix_basis = _identity
    bpy.context.view_layer.update()

    return len(holder_for)


# ---------------------------------------------------------------------------
# Camera aspect
# ---------------------------------------------------------------------------
#
# This script does not create any camera. Use `scripts/add_debug_camera.py`
# if you want a viewport-friendly preview camera; the exporter writes
# whatever cameras are present in the scene with no special filtering.


def normalize_camera_aspect():
    """Stamp a default `dat_camera_aspect=1.18` on any scene camera that
    doesn't carry one already, so the exporter's CObj writes a sensible
    aspect for cameras authored without going through the importer.
    Returns the number of cameras touched.
    """
    touched = 0
    for obj in bpy.data.objects:
        if obj.type == 'CAMERA' and "dat_camera_aspect" not in obj:
            obj["dat_camera_aspect"] = 1.18
            print("  Camera '%s': set dat_camera_aspect = 1.18" % obj.name)
            touched += 1
    return touched


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


def _first_bone_action_name(armature):
    """Name of the first action whose fcurves drive this armature's pose bones,
    or `""` when the rig has no actions yet.

    Matches the exporter's own action-discovery logic in
    `describe_bone_animations` so the slot default lines up with what will
    actually get exported as DAT[0] under slot-ordered enumeration.
    """
    prefix = armature.name.split('_skeleton_')[0] if '_skeleton_' in armature.name else armature.name
    for action in bpy.data.actions:
        if action.name.startswith(prefix + '_'):
            return action.name
        if action.id_root == 'OBJECT':
            for fc in action.fcurves:
                if fc.data_path.startswith('pose.bones['):
                    return action.name
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

    # Head bone — preserve any value already set by the caller (e.g. a
    # deploy harness that picked the head bone via its own priority list).
    head_bone_name = armature.get("dat_pkx_head_bone") or _find_head_bone(armature)
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
    if model_type == 'POKEMON':
        sub_triggers = ["sleep_on", "sleep_off", "blink", "unused"]
    else:
        sub_triggers = ["sleep_on", "sleep_off", "extra", "unused"]
    for i in range(4):
        prefix = "dat_pkx_sub_anim_%d" % i
        armature[prefix + "_type"] = "none"
        armature[prefix + "_trigger"] = sub_triggers[i]
        armature[prefix + "_anim_ref"] = ""

    # --- Body map bones ---
    # The PKX header carries 16 slots per anim entry (body_map_bones[0..15]).
    # Disassembly + corpus survey confirms only `origin` (slot 0), `mouth`
    # (slot 1, head-attached Model entries) and `chest` (slot 2, LensFlare
    # anchor) are read by the waza-effect pipeline at any meaningful
    # frequency. The other slots are authored by hand and rarely consumed,
    # but we still expose all 16 so the user can hand-pick.
    #
    # Each slot is filled with a sensible default ONLY when the caller
    # hasn't already set it. This lets a deploy harness (or the user, by
    # hand) pick body-map bones via per-rig conventions and then re-run
    # prep to refresh timings without losing those choices.
    bones = list(armature.data.bones)
    root_name = bones[0].name if bones else ""
    _body_defaults = {key: "" for key in _BODY_MAP_KEYS}
    _body_defaults["origin"] = root_name
    _body_defaults["mouth"] = head_bone_name
    for key in _BODY_MAP_KEYS:
        prop_key = "dat_pkx_body_%s" % key
        # `not in armature` catches "never set"; `== ""` is a sentinel for
        # "explicitly cleared" — both should fall back to the default.
        existing = armature.get(prop_key)
        if existing:
            continue
        armature[prop_key] = _body_defaults[key]

    # --- Animation entries (17 slots) ---
    anim_count = 17
    armature["dat_pkx_anim_count"] = anim_count

    # Slot types: 0=idle(loop), 8=damage(hit), 9=damageB(compound), 10=faint(hit), rest=action
    _SLOT_TYPES = {0: "loop", 8: "hit_reaction", 9: "compound", 10: "hit_reaction"}

    # Leave every slot's action assignment empty by default. The author
    # picks the action per slot via the PKX Metadata panel; only then
    # does the next prep run derive timing. Auto-assigning a default
    # action here is a footgun: derive_timing would lock in timings
    # against the default's duration, and `set_if_zero` would then
    # protect those stale timings on every subsequent run.
    for i in range(anim_count):
        prefix = "dat_pkx_anim_%02d" % i
        anim_type = _SLOT_TYPES.get(i, "action")

        armature[prefix + "_type"] = anim_type
        armature[prefix + "_sub_0_anim"] = ""
        if anim_type == "compound":
            armature[prefix + "_sub_1_anim"] = ""
        armature[prefix + "_sub_count"] = 2 if anim_type == "compound" else 1
        armature[prefix + "_damage_flags"] = 0
        armature[prefix + "_terminator"] = 3 if is_xd else 1

        # Timings start at 0; derive_timing only runs once the panel has
        # existed for at least one prep run AND the author has picked an
        # action for the slot.
        armature[prefix + "_timing_1"] = 0.0
        armature[prefix + "_timing_2"] = 0.0
        armature[prefix + "_timing_3"] = 0.0
        armature[prefix + "_timing_4"] = 0.0

    print("  PKX metadata applied to '%s':" % armature.name)
    print("    Format: %s, Species: %d, Head bone: '%s'" % (format, species_id, head_bone_name))
    print("    17 animation slots (slot 0 = idle loop)")
    print("    Shiny params available in PKX Metadata panel (default: identity)")


def _get_action_duration(action_name):
    """Get an action's duration in seconds (frame span / 30 fps).

    HSD AOBJs advance at 30 animation-units/second on XD (verified by
    matching `AOBJ.end_frame / 30` against every game-native PKX header
    `timing_1` value).

    The exporter normalises every action to a zero-based frame range and
    bakes `max_frame - min_frame + 1` frames (see the exporter's
    `_bone_fcurves_frame_range`). The derived duration must span that same
    range, so we subtract the start frame. Using `max_frame + 1` alone
    assumes a frame-0 start and over-counts by the start frame — an action
    authored on Blender's default frame-1 start derives one frame too long,
    so the in-game timing outlasts the baked animation. For an importer
    round-trip the start frame is 0, so the result is unchanged.

    Only pose-bone fcurves define the animation length; object- and
    material-level fcurves can span a different range and are ignored,
    mirroring the exporter.
    """
    action = bpy.data.actions.get(action_name)
    if not action or not action.fcurves:
        return 0.0
    bone_frames = [kp.co[0] for fc in action.fcurves
                   if fc.data_path.startswith('pose.bones[')
                   for kp in fc.keyframe_points]
    frames = bone_frames or [kp.co[0] for fc in action.fcurves
                             for kp in fc.keyframe_points]
    if not frames:
        return 0.0
    return (max(frames) - min(frames) + 1) / 30.0


def derive_timing(armature):
    """Auto-derive animation timing fields from action durations.

    Timing semantics per anim_type:
      loop:         T1 = duration
      action:       T1 = wind-up (33%), T2 = hit (66%), T3 = duration
      hit_reaction: T1 = reaction start (50%), T2 = duration
      compound:     T1 = sub1 mid, T2 = sub1 end, T3 = sub2 mid, T4 = sub2 end

    Each timing field is only filled in when its current value is 0 — so
    re-running prep never clobbers a value the user (or an earlier prep
    pass) already set. To force a redrive on a specific slot, manually
    zero its timing fields in the PKX Metadata panel and re-run.

    Returns the number of timing fields updated.
    """
    anim_count = armature.get("dat_pkx_anim_count", 0)
    updated = 0

    def set_if_zero(key, value):
        nonlocal updated
        if armature.get(key, 0.0):
            return
        armature[key] = value
        updated += 1

    for i in range(anim_count):
        prefix = "dat_pkx_anim_%02d" % i
        anim_type = armature.get(prefix + "_type", "action")
        action_name = armature.get(prefix + "_sub_0_anim", "")
        dur = _get_action_duration(action_name) if action_name else 0.0

        if dur <= 0:
            continue

        if anim_type == "loop":
            set_if_zero(prefix + "_timing_1", dur)
        elif anim_type == "action":
            set_if_zero(prefix + "_timing_1", dur / 3.0)
            set_if_zero(prefix + "_timing_2", dur * 2.0 / 3.0)
            set_if_zero(prefix + "_timing_3", dur)
        elif anim_type == "hit_reaction":
            set_if_zero(prefix + "_timing_1", dur * 0.5)
            set_if_zero(prefix + "_timing_2", dur)
        elif anim_type == "compound":
            # Two sub-anims: get duration of second if available
            action2_name = armature.get(prefix + "_sub_1_anim", "")
            dur2 = _get_action_duration(action2_name) if action2_name else dur
            set_if_zero(prefix + "_timing_1", dur * 0.5)
            set_if_zero(prefix + "_timing_2", dur)
            set_if_zero(prefix + "_timing_3", dur2 * 0.5)
            set_if_zero(prefix + "_timing_4", dur2)

    return updated


# ---------------------------------------------------------------------------
# Test animations
# ---------------------------------------------------------------------------
#
# Two helper actions are authored per armature for in-game smoke-testing:
#
#   auto_animation_dummy — two-frame identity pose (placeholder for slots
#                          whose real action isn't ready yet).
#   auto_animation_spin  — 60-frame full revolution around the rig's
#                          vertical axis on the root bone, with the end
#                          keyframe at 2π so the loop closes cleanly back
#                          to 0° on frame 0.
#
# Neither action is assigned to a PKX slot — users hand-pick them in the
# PKX Metadata panel only when smoke-testing. They are created after
# apply_pkx_metadata() so the slot auto-fill never selects them.

_TEST_ANIM_DUMMY = "auto_animation_dummy"
_TEST_ANIM_SPIN = "auto_animation_spin"


def _new_action_with_object_slot(name):
    action = bpy.data.actions.new(name)
    action.use_fake_user = True
    slot = action.slots.new('OBJECT', 'Armature')
    action.slots.active = slot
    return action


def prepare_test_animations(armature):
    """Author two helper actions on `armature` for in-game smoke testing.

    Returns the number of actions that were newly created.
    """
    if not armature.data.bones:
        return 0
    root_name = armature.data.bones[0].name
    rot_path = 'pose.bones["%s"].rotation_euler' % root_name
    # Euler fcurves are only evaluated when the pose bone is in an Euler
    # rotation mode; the Blender default is QUATERNION, which silently
    # ignores rotation_euler keyframes during viewport playback.
    armature.pose.bones[root_name].rotation_mode = 'XYZ'
    created = 0

    if _TEST_ANIM_DUMMY not in bpy.data.actions:
        action = _new_action_with_object_slot(_TEST_ANIM_DUMMY)
        for axis in range(3):
            fc = action.fcurves.new(rot_path, index=axis)
            fc.keyframe_points.add(2)
            for i, frame in enumerate((0.0, 1.0)):
                kp = fc.keyframe_points[i]
                kp.co = (frame, 0.0)
                kp.interpolation = 'LINEAR'
        created += 1

    if _TEST_ANIM_SPIN not in bpy.data.actions:
        action = _new_action_with_object_slot(_TEST_ANIM_SPIN)
        # Sample 90° quarters so a renderer that interpolates raw fcurve
        # values (linearly, between euler endpoints) traces the full circle
        # rather than oscillating from 0 to 2π and back.
        steps = [(0.0, 0.0),
                 (15.0, math.pi * 0.5),
                 (30.0, math.pi),
                 (45.0, math.pi * 1.5),
                 (60.0, math.pi * 2.0)]
        for axis in range(3):
            fc = action.fcurves.new(rot_path, index=axis)
            fc.keyframe_points.add(len(steps))
            for i, (frame, angle) in enumerate(steps):
                kp = fc.keyframe_points[i]
                kp.co = (frame, angle if axis == 1 else 0.0)
                kp.interpolation = 'LINEAR'
        created += 1

    return created


# ---------------------------------------------------------------------------
# Texture sizing
# ---------------------------------------------------------------------------

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
                    if img.dat_gx_format != 'AUTO':
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
        # On GX the 4th source is alpha, but the shiny preview only carries
        # an RGB Color socket — alpha isn't available to route in. Fall back
        # to identity for that slot so "Alpha" reads as "leave this channel
        # alone" instead of silently zeroing it.
        source = srcs.get(routing[i], srcs[i])
        group.links.new(source, comb.inputs[i])
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


_SHINY_ALBEDO_KEYS = ('albedo', 'basecolor', 'diffuse', 'color')


def _shiny_albedo_rank(name):
    """Lower = more likely to be the albedo input. Names are normalised by
    stripping spaces/underscores so 'BaseColor', 'base color', and
    'base_color' all match. Unmatched names rank last.
    """
    lname = name.lower().replace('_', '').replace(' ', '')
    for i, key in enumerate(_SHINY_ALBEDO_KEYS):
        if key in lname:
            return i
    return len(_SHINY_ALBEDO_KEYS)


def _shiny_find_color_input_via_group(group_node):
    """Pick the outer input on `group_node` most likely to be the albedo
    feed: name matches albedo/basecolor/diffuse/color AND its material-
    level chain contains a texture.

    Topology-agnostic on purpose — shader packs like PokemonShaderbyChicoEevee
    route the Principled BSDF's Base Color through fresnel/rim-light mixes
    that never trace back to the actual albedo input, so a DFS from
    Principled.Base Color would miss it. The artist-facing input name is
    the only reliable signal for which outer socket is the albedo.
    """
    if group_node.node_tree is None:
        return None
    textured = [s for s in group_node.inputs
                if not _shiny_no_texture_in_color_chain(s)
                and _shiny_albedo_rank(s.name) < len(_SHINY_ALBEDO_KEYS)]
    if not textured:
        return None
    textured.sort(key=lambda s: _shiny_albedo_rank(s.name))
    return textured[0]


def _shiny_find_color_input(nodes):
    """Find the main color input on the output shader.

    Prefers a top-level Principled/Emission; otherwise recurses into
    ShaderNodeGroup instances so shader packs like PokemonShaderbyChicoEevee
    that wrap a Principled BSDF behind a custom group still get shiny
    nodes spliced onto whichever outer group input carries the albedo.
    """
    for node in nodes:
        if node.type == 'BSDF_PRINCIPLED':
            bc = node.inputs['Base Color']
            if bc.is_linked:
                return node, bc
    for node in nodes:
        if node.type == 'EMISSION':
            return node, node.inputs['Color']
    for node in nodes:
        if node.bl_idname == 'ShaderNodeGroup' and node.node_tree:
            outer = _shiny_find_color_input_via_group(node)
            if outer is not None:
                return node, outer
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
    mix = nodes.new('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'MIX'
    mix.clamp_factor = True
    mix.name = mix_name
    # ShaderNodeMix RGBA socket layout: Factor=0, A=6, B=7, Result=output 2.
    mix.inputs[0].default_value = 0.0
    links.new(source_out, mix.inputs[6])
    links.new(gn.outputs[0], mix.inputs[7])
    links.new(mix.outputs[2], target_input)
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

def prepare_mesh_weights(armature):
    """Optimize mesh weights for GameCube export.

    1. Limits all vertices to MAX_WEIGHTS_PER_VERTEX bone influences.
    2. Quantises weights to WEIGHT_QUANTISATION_STEP increments.
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

        # Step 2a: Drop sub-threshold weights and redistribute their slack
        # to the dominant bone of each vertex (opt-in, HSDLib ClampWeight
        # parity). Threshold and toggle live at the top of the file.
        if REDISTRIBUTE_SUB_THRESHOLD_WEIGHTS:
            redistributed = 0
            for v in mesh_obj.data.vertices:
                bone_groups = [g for g in v.groups
                               if g.group < len(mesh_obj.vertex_groups)
                               and mesh_obj.vertex_groups[g.group].name in bone_names
                               and g.weight > 0.0]
                small = [g for g in bone_groups
                         if g.weight < WEIGHT_DROP_THRESHOLD]
                if not small or len(small) == len(bone_groups):
                    continue
                slack = sum(g.weight for g in small)
                dominant = max(bone_groups, key=lambda g: g.weight)
                for g in small:
                    g.weight = 0.0
                dominant.weight = min(1.0, dominant.weight + slack)
                redistributed += 1
            if redistributed:
                print("    %s: redistributed sub-%.2f weights on %d vertices"
                      % (mesh_obj.name, WEIGHT_DROP_THRESHOLD, redistributed))

        # Step 2: Quantise weights to WEIGHT_QUANTISATION_STEP increments
        bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
        bpy.ops.object.vertex_group_normalize_all(lock_active=False)
        bpy.ops.object.mode_set(mode='OBJECT')

        step = WEIGHT_QUANTISATION_STEP
        mesh_data = mesh_obj.data
        quantized = 0
        for v in mesh_data.vertices:
            for g in v.groups:
                if g.group < len(mesh_obj.vertex_groups):
                    if mesh_obj.vertex_groups[g.group].name in bone_names:
                        q = round(g.weight / step) * step
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
                            g.weight = round(g.weight / step) * step
            print("    %s: quantised %d weight values to %.0f%% steps" %
                  (mesh_obj.name, quantized, step * 100))

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


def _cull_unused_material_slots(armature):
    """Remove material slots from each child mesh that no polygon references.

    Returns the total number of slots stripped across all child meshes.
    """
    removed = 0
    for child in armature.children:
        if child.type != 'MESH' or child.data is None:
            continue
        used = {p.material_index for p in child.data.polygons}
        for idx in reversed(range(len(child.material_slots))):
            if idx in used:
                continue
            bpy.ops.object.select_all(action='DESELECT')
            child.select_set(True)
            bpy.context.view_layer.objects.active = child
            child.active_material_index = idx
            bpy.ops.object.material_slot_remove()
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# Scene lights
# ---------------------------------------------------------------------------

# Namespaced prefix for every light this prep script creates. Keeps re-runs
# idempotent (lookup by exact name → skip if exists) and avoids collisions
# with user-authored or importer-built lights (which use shorter, generic
# names like "Light_0" / "Ambient_Light").
_PREP_LIGHT_PREFIX = "DATPlugin_Prep_"


def prepare_ambient_light():
    """Add an ambient light if none exists in the scene.

    Creates a no-op POINT light with energy=0 (invisible in Blender) and
    a dat_light_type="AMBIENT" custom property. The color controls
    scene-level fill lighting in-game — applied uniformly to all materials.

    Returns the number of ambient lights created (0 or 1).
    """
    # Skip if either an existing AMBIENT-flagged light is already present
    # OR our namespaced one was created on a previous run.
    name = _PREP_LIGHT_PREFIX + "Ambient"
    if bpy.data.objects.get(name) is not None:
        return 0
    for obj in bpy.data.objects:
        if obj.type == 'LIGHT' and obj.get('dat_light_type') == 'AMBIENT':
            return 0

    # Default: (76, 76, 76) / 255 ≈ 0.298 sRGB — a sensible neutral
    # fill brightness for in-engine preview.
    srgb_val = 76 / 255.0
    linear_val = _srgb_to_linear(srgb_val)

    light_data = bpy.data.lights.new(name=name, type='POINT')
    light_data.energy = 0
    light_data.color = (linear_val, linear_val, linear_val)

    lamp = bpy.data.objects.new(name=name, object_data=light_data)
    lamp["dat_light_type"] = "AMBIENT"
    bpy.context.scene.collection.objects.link(lamp)

    return 1


def prepare_lights():
    """Ensure the scene has a standard 4-light preview setup.

    Creates a 4-LightSet layout that matches the convention found in
    every tested Colo/XD model:
      [0] Ambient (76, 76, 76) — uniform fill, POINT with energy=0
      [1] Main directional (204, 204, 204) — brightest, SUN from above-front
      [2] Fill directional (102, 102, 102) — medium, SUN from the side
      [3] Back/rim directional (76, 76, 76) — darker, SUN from behind

    Names are namespaced under _PREP_LIGHT_PREFIX so re-runs don't
    duplicate them and they don't collide with imported / user lights.

    Returns the number of lights created.
    """
    created = 0

    # [0] Ambient — delegate to existing function
    created += prepare_ambient_light()

    # Standard directional lights — (suffix, color_u8, rotation_euler_radians)
    _DIRECTIONAL_LIGHTS = [
        ('Main', 204, (math.radians(-45), 0, math.radians(30))),
        ('Fill', 102, (math.radians(-30), 0, math.radians(-60))),
        ('Back',  76, (math.radians(-20), 0, math.radians(150))),
    ]

    for suffix, color_u8, rotation in _DIRECTIONAL_LIGHTS:
        name = _PREP_LIGHT_PREFIX + suffix
        # Idempotent: skip if a previous run already created this light.
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
    ("sleep_on", "Sleep"), ("sleep_off", "Wake Up"),
    ("blink", "Blink"), ("extra", "Extra"), ("unused", "Unused"),
]
# Standalone-script rule (per CLAUDE.md): no imports from the plugin
# package. Keep the body-map list inline and mirror its content with
# shared/helpers/pkx_header.py — both must stay in sync.
_BODY_MAP_KEYS = [
    "origin", "mouth", "chest", "tail",
    "eye_left", "eye_right", "hand_left", "hand_right",
    "additional_1", "additional_2", "additional_3", "additional_4",
    "foot_left", "foot_right", "center", "additional_5",
]
_BODY_MAP_NAMES = [
    "Origin", "Mouth", "Chest", "Tail",
    "Eye Left", "Eye Right", "Hand Left", "Hand Right",
    "Additional 1", "Additional 2", "Additional 3", "Additional 4",
    "Foot Left", "Foot Right", "Center", "Additional 5",
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


_GX_FORMAT_ITEMS = [
    ('AUTO', 'AUTO (Pick based on content)', 'Let the exporter choose a format'),
    ('CMPR', 'CMPR (Compressed)', 'S3TC/DXT1 compressed — best for most textures'),
    ('RGBA8', 'RGBA8 (Full Quality)', '32-bit full quality RGBA'),
    ('RGB565', 'RGB565 (No Alpha)', '16-bit RGB, no alpha'),
    ('RGB5A3', 'RGB5A3 (RGB+Alpha)', '16-bit with optional alpha'),
    ('I4', 'I4 (Grayscale 4-bit)', '4-bit grayscale'),
    ('I8', 'I8 (Grayscale 8-bit)', '8-bit grayscale (intensity = alpha)'),
    ('IA4', 'IA4 (Intensity+Alpha 4-bit)', '4-bit intensity + 4-bit alpha'),
    ('IA8', 'IA8 (Intensity+Alpha 8-bit)', '8-bit intensity + 8-bit alpha'),
    ('C4', 'C4 (4-bit Palette)', 'Palette indexed, up to 16 colors'),
    ('C8', 'C8 (8-bit Palette)', 'Palette indexed, up to 256 colors'),
]


def _register_image_props():
    """Register `dat_gx_format` on bpy.types.Image if not already registered.

    Mirrors the addon's definition in BlenderPlugin.py so the prep script
    works even when the addon is disabled or its register() hasn't run in
    the current session (e.g. after a botched script reload).
    """
    if hasattr(bpy.types.Image, 'dat_gx_format'):
        return
    from bpy.props import EnumProperty
    bpy.types.Image.dat_gx_format = EnumProperty(
        name="GX Texture Format",
        description="GX texture format used when exporting this texture. Auto selects based on pixel content.",
        items=_GX_FORMAT_ITEMS,
        default='AUTO',
    )


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
                    # Compound slots are Damage B by convention — slot 0
                    # is the hit/damage clip, slot 1 is the faint
                    # follow-through — so label them by role.
                    _slot_anim_type = obj.get(prefix + "_type", "action")
                    if _slot_anim_type == "compound" and sub_count > 1:
                        _sub_labels = ["Damage", "Fainting"]
                    else:
                        _sub_labels = None
                    for s in range(min(sub_count, 3)):
                        anim_key = prefix + "_sub_%d_anim" % s
                        row = sub_box.row(align=True)
                        if _sub_labels and s < len(_sub_labels):
                            row.label(text="%s:" % _sub_labels[s])
                        else:
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
                        _timing_labels = {1: "Damage Mid", 2: "Damage End",
                                          3: "Fainting Mid", 4: "Fainting End"}
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

    # Force every armature back to Object mode before anything else — a rig
    # left mid-edit makes the first operator below fail its poll, and would
    # make bake_transforms' direct-data edits get discarded.
    exited = exit_armature_edit_modes()
    if exited:
        print("  Returned %d armature(s) to Object mode" % exited)

    # 0. Register panel + properties if the addon isn't loaded
    _register_pkx_panel()
    _register_image_props()

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

    # 2. Camera aspect — stamp default dat_camera_aspect on any camera
    # missing it. Camera creation lives in scripts/add_debug_camera.py.
    normalize_camera_aspect()

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

        # Strip material slots that no polygon references — split-style ops
        # leave the full slot list copied onto each new mesh, and the unused
        # entries still pull their materials into the EEVEE compile graph.
        culled_slots = _cull_unused_material_slots(arm)
        if culled_slots:
            print("  Culled %d unused material slot(s) on '%s'" % (culled_slots, arm.name))

        # Separate mesh-owner joints from deformer joints (envelope
        # invariant) so detached single-bone meshes (eyes, hair) don't
        # float in-game. Runs after weight limiting/splitting so the final
        # mesh set + weights are known.
        holders = reparent_meshes_to_holder_bones(arm)
        if holders:
            print("  Inserted %d mesh-holder bone(s) on '%s'" % (holders, arm.name))

        # PKX metadata
        panel_existed_before = bool(arm.get("dat_pkx_format"))
        if panel_existed_before:
            print("  Armature '%s' already has PKX metadata (skipped)" % arm.name)
        else:
            apply_pkx_metadata(arm, format='XD', model_type='POKEMON', species_id=0)

        # Derive animation timing from action durations — only on runs
        # where the panel existed before this run. On the very first
        # prep run there are no author-picked slot actions yet, so
        # deriving would lock timings against the empty-string slot
        # (no-op) or — historically — against a default fill that no
        # longer happens. Leave timings at 0 until the author picks a
        # slot action and re-runs prep.
        if panel_existed_before:
            timing_count = derive_timing(arm)
            if timing_count:
                print("  Derived timing for %d animation slot(s) on '%s'"
                      % (timing_count, arm.name))

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

        # Test animations (auto_animation_dummy + auto_animation_spin) —
        # smoke-test placeholders, not auto-assigned to any PKX slot.
        test_anim_count = prepare_test_animations(arm)
        if test_anim_count:
            print("  Created %d test animation(s) for '%s'" % (test_anim_count, arm.name))

    # 6. Scene lights (ambient + 3 directional)
    light_count = prepare_lights()
    if light_count:
        print("  Added %d battle light(s)" % light_count)

    # 7. Leave the first armature selected + active so the PKX Metadata
    # panel is immediately visible in the Properties editor.
    _first_arm = next((o for o in bpy.data.objects if o.type == 'ARMATURE'), None)
    if _first_arm is not None:
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except RuntimeError:
            pass
        bpy.ops.object.select_all(action='DESELECT')
        _first_arm.select_set(True)
        bpy.context.view_layer.objects.active = _first_arm
        print("  Selected armature '%s'" % _first_arm.name)

    print("=== Done ===")
