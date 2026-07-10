"""Blender addon operators and registration for the DAT model importer/exporter."""
import os
import bpy
from bpy.props import (StringProperty, BoolProperty, FloatProperty, EnumProperty,
                       CollectionProperty, BoolVectorProperty, IntProperty)
from bpy_extras.io_utils import ImportHelper, ExportHelper

from .legacy import import_hsd as legacy_import_hsd
from .importer import Importer as IRImporter
from .importer.phases.extract.extract import extract_dat
from .importer.phases.route.route import route_sections
from .shared.helpers.logger import Logger, StubLogger

# Routing node types compatible with the legacy importer
_LEGACY_TYPE_MAP = {
    'SceneData': 'SCENE',
    'Joint': 'BONE',
}


class ImportHSD(bpy.types.Operator, ImportHelper):
    """Load a DAT model"""
    bl_idname = "import_model.dat"
    bl_label = "Import DAT"
    bl_options = {'UNDO'}

    files: CollectionProperty(name="File Path",
                          description="File path used for importing the HSD file",
                          type=bpy.types.OperatorFileListElement)
    directory: StringProperty(subtype="DIR_PATH")
    game: EnumProperty(
        name='Game of Origin',
        description='Which game the .dat file was extracted from. Selects the section-name → node-type routing rules.',
        items=[
            ('COLO_XD', 'Colosseum / XD', 'Pokémon Colosseum and Pokémon XD: Gale of Darkness'),
            ('KIRBY_AIR_RIDE', 'Kirby Air Ride', 'Kirby Air Ride'),
            ('SMASH_BROS', 'Super Smash Bros.', 'Super Smash Bros. Melee'),
            ('OTHER', 'Other', 'Unknown / unsupported game — falls back to Colosseum / XD routing rules'),
        ],
        default='COLO_XD',
    )
    colo_xd_kind: EnumProperty(
        name='Colo/XD Kind',
        description='What kind of Colosseum/XD container is being imported. PKX models carry a header that selects animation-slot labels; raw .dat models do not.',
        items=[
            ('PKX_POKEMON', 'PKX Pokémon', 'A PKX whose animation slots follow Pokémon battle-move conventions'),
            ('PKX_TRAINER', 'PKX Trainer', 'A PKX whose animation slots follow trainer-pose conventions'),
            ('DAT_MODEL', 'DAT Model', 'A raw .dat model with no PKX header — Pokémon/Trainer distinction does not apply'),
        ],
        default='PKX_POKEMON',
    )
    setup_workspace: BoolProperty(default=True, name='Setup Workspace',
                                 description='Split the viewport and open an Action Editor. Sets playback end frame to 60.')
    import_lights: BoolProperty(default=False, name='Import Lights',
                               description='Import light sets from the model file.')
    import_cameras: BoolProperty(default=False, name='Import Cameras',
                                description='Import cameras from the model file.')
    use_legacy: BoolProperty(default=False, name='Use Legacy Importer',
                            description='Use the old import pipeline instead of the new Intermediate Representation pipeline.')

    filename_ext = ".dat"
    filter_glob: StringProperty(default="*.fdat;*.dat;*.rdat;*.pkx;*.fsys;*.wzx;*.cam", options={'HIDDEN'})

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "game")
        if self.game == 'COLO_XD':
            layout.prop(self, "colo_xd_kind")
        layout.prop(self, "setup_workspace")
        layout.prop(self, "import_lights")
        layout.prop(self, "import_cameras")
        if self.game == 'COLO_XD':
            layout.prop(self, "use_legacy")

    def execute(self, context):
        if self.files and self.directory:
            paths = [os.path.join(self.directory, file.name) for file in self.files]
        else:
            paths = [self.filepath]

        any_succeeded = False
        for path in paths:
            try:
                if self.use_legacy:
                    self._import_legacy(context, path)
                else:
                    self._import_ir(context, path)
                any_succeeded = True
            except Exception as error:
                self.report({'ERROR'}, "Import failed for %s: %s" % (os.path.basename(path), error))

        if self.setup_workspace and any_succeeded:
            _setup_anim_workspace(context)

        return {'FINISHED'} if any_succeeded else {'CANCELLED'}

    def _import_ir(self, context, path):
        """Read file and run the IR import pipeline."""
        with open(path, 'rb') as f:
            raw_bytes = f.read()

        filename = os.path.basename(path)
        model_name = filename.split('.')[0] if filename else "unknown"

        logger = Logger(model_name=model_name)

        options = {
            "ik_hack": True,
            "max_frame": 10000,
            "filepath": path,
            "import_lights": self.import_lights,
            "import_cameras": self.import_cameras or filename.lower().endswith('.cam'),
            "include_shiny": True,
            "game": self.game,
            "colo_xd_kind": self.colo_xd_kind if self.game == 'COLO_XD' else None,
        }

        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action='DESELECT')

        IRImporter.run(context, raw_bytes, filename, options, logger=logger)

    def _import_legacy(self, context, path):
        """Run extract + route, legacy import, then post-process."""
        from .importer.phases.post_process.post_process import post_process

        with open(path, 'rb') as f:
            raw_bytes = f.read()

        filename = os.path.basename(path)
        entries = extract_dat(raw_bytes, filename)

        legacy_import_hsd.ikhack = True
        legacy_import_hsd.anim_max_frame = 10000
        legacy_import_hsd.write_logs = True
        legacy_import_hsd.import_lights = self.import_lights

        options = {"include_shiny": False}

        for dat_bytes, metadata in entries:
            section_map = route_sections(dat_bytes, game=self.game)

            # Record which armatures exist before the legacy import so we can
            # diff afterwards to find newly created ones for Phase 6
            existing = set(obj.name for obj in bpy.data.objects if obj.type == 'ARMATURE')

            for section_name, node_type in section_map.items():
                data_type = _LEGACY_TYPE_MAP.get(node_type)
                if data_type is None:
                    continue

                status = legacy_import_hsd.load_dat_bytes(
                    dat_bytes, metadata.filename, context,
                    scene_name=section_name,
                    data_type=data_type,
                )
                if status and 'FINISHED' not in status:
                    raise ValueError("Legacy import failed for %s section '%s'" % (
                        metadata.filename, section_name))

            # Diff armatures against the pre-import snapshot to find newly created ones
            new_armatures = set(obj.name for obj in bpy.data.objects
                                if obj.type == 'ARMATURE' and obj.name not in existing)

            post_process(new_armatures, metadata.shiny_params, options)


class ExportHSD(bpy.types.Operator, ExportHelper):
    """Export selected armature(s) as a DAT model"""
    bl_idname = "export_model.dat"
    bl_label = "Export DAT"

    filename_ext = ".dat"
    filter_glob: StringProperty(default="*.dat;*.pkx", options={'HIDDEN'})
    check_extension = False  # Allow .pkx files without forcing .dat extension

    write_logs: BoolProperty(default=True, name='Write Logs',
                            description='Write export logs to a temp file for debugging.')
    verbose: BoolProperty(default=False, name='Verbose',
                         description='Print INFO/DEBUG export progress to the Blender console, including the per-section DAT size breakdown.')
    strip_names: BoolProperty(default=False, name='Strip Node Names',
                             description='Remove bone/node names from the output. Enable for compatibility with models that have empty name fields.')
    sparsify_bezier: BoolProperty(default=True, name='Bezier Sparsification',
                                  description='Use bezier curves with slopes for animation export. Produces more accurate keyframes. Disable for simpler linear sparsification.')

    @classmethod
    def poll(cls, context):
        return any(obj.type == 'ARMATURE' for obj in context.scene.objects)

    def execute(self, context):
        from .exporter.exporter import Exporter

        model_name = os.path.splitext(os.path.basename(self.filepath))[0] or "export"

        if self.write_logs:
            logger = Logger(verbose=self.verbose, model_name=model_name)
        else:
            logger = StubLogger()

        options = {
            'strip_names': self.strip_names,
            'sparsify_bezier': self.sparsify_bezier,
        }

        try:
            Exporter.run(context, self.filepath, options, logger=logger)
        except Exception as error:
            self.report({'WARNING'}, "Export failed: %s" % error)
            logger.error("Export failed: %s", error)
            logger.close()
            return {'CANCELLED'}

        self.report({'INFO'}, "Exported to %s" % self.filepath)
        return {'FINISHED'}


def _setup_anim_workspace(context):
    """Split the 3D viewport and open an Action Editor.

    Skips setup if a Dope Sheet / Action Editor is already visible.
    """
    # Check if an Action Editor is already showing
    for area in context.screen.areas:
        if area.type == 'DOPESHEET_EDITOR':
            for space in area.spaces:
                if space.type == 'DOPESHEET_EDITOR' and space.mode == 'ACTION':
                    return  # Already set up

    screen = context.screen
    view3d_area = None
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            view3d_area = area
            break

    if not view3d_area:
        return

    with context.temp_override(area=view3d_area):
        bpy.ops.screen.area_split(direction='VERTICAL', factor=0.7)

    for area in screen.areas:
        if area.type == 'VIEW_3D' and area != view3d_area:
            area.type = 'DOPESHEET_EDITOR'
            for space in area.spaces:
                if space.type == 'DOPESHEET_EDITOR':
                    space.mode = 'ACTION'
            break


def menu_func_import(self, context):
    self.layout.operator(ImportHSD.bl_idname, text="Gamecube DAT Model (.dat)")


def menu_func_export(self, context):
    self.layout.operator(ExportHSD.bl_idname, text="Gamecube DAT Model (.dat)")


_SHINY_CHANNEL_ITEMS = [
    ('0', 'Red', 'Red channel (0)'),
    ('1', 'Green', 'Green channel (1)'),
    ('2', 'Blue', 'Blue channel (2)'),
    ('3', 'Alpha', 'Alpha channel (3)'),
]


def _on_shiny_toggle_update(obj, context):
    """Rebuild shiny node groups and refresh viewport when toggle changes."""
    if obj.dat_pkx_shiny:
        from .importer.phases.post_process.shiny_filter import rebuild_shiny_node_group
        rebuild_shiny_node_group(obj)
    _refresh_shiny_viewport(obj, context)


def _on_shiny_param_update(obj, context):
    """Rebuild shiny shader nodes and refresh viewport when a parameter changes."""
    if obj.dat_pkx_shiny:
        from .importer.phases.post_process.shiny_filter import rebuild_shiny_node_group
        rebuild_shiny_node_group(obj)
    _refresh_shiny_viewport(obj, context)


def _refresh_shiny_viewport(obj, context):
    """Tag objects and materials for viewport refresh."""
    obj.update_tag()
    for child in obj.children:
        if child.type == 'MESH' and child.active_material:
            child.active_material.node_tree.update_tag()
    if context and context.area:
        context.area.tag_redraw()


def _has_shiny_data(obj):
    """True if shiny params differ from identity/neutral (derived, no stored flag)."""
    try:
        identity = (int(obj.dat_pkx_shiny_route_r) == 0 and int(obj.dat_pkx_shiny_route_g) == 1
                    and int(obj.dat_pkx_shiny_route_b) == 2 and int(obj.dat_pkx_shiny_route_a) == 3)
        neutral = (abs(obj.dat_pkx_shiny_brightness_r) < 0.001
                   and abs(obj.dat_pkx_shiny_brightness_g) < 0.001
                   and abs(obj.dat_pkx_shiny_brightness_b) < 0.001)
        return not (identity and neutral)
    except AttributeError:
        return False


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


# The targeted-sub-anim bone list (PartAnimData.bone_config) is stored as one
# comma-joined string of bone *names* — Blender ID properties have no native
# string-array type, and the exporter resolves names → indices at write time so
# the list survives bone reordering. Up to 8 bones; the export caps and derives
# sub_param from the count.
_MAX_TARGET_BONES = 8


def _get_target_bones(obj, prefix):
    """Read the comma-joined target-bone name list into a Python list."""
    raw = obj.get(prefix + "_bones", "")
    if not isinstance(raw, str):
        return []
    return [n.strip() for n in raw.split(',') if n.strip()]


def _set_target_bones(obj, prefix, names):
    """Write a Python list back as the comma-joined name string (capped at 8)."""
    obj[prefix + "_bones"] = ', '.join(names[:_MAX_TARGET_BONES])


def _get_selectors(obj, prefix, n):
    """Read the parallel targeted-texture selector list, padded/truncated to n.

    Selectors are per-part texture parameters (bone_config bytes 8-15); a
    missing entry defaults to 0. Only meaningful for `targeted_texture`.
    """
    raw = obj.get(prefix + "_selectors", "")
    vals = []
    if isinstance(raw, str) and raw.strip():
        for tok in raw.split(','):
            tok = tok.strip()
            try:
                vals.append(int(tok))
            except ValueError:
                vals.append(0)
    return (vals + [0] * n)[:n]


def _set_selectors(obj, prefix, vals):
    """Write the selector list back as a comma-joined int string (capped at 8)."""
    obj[prefix + "_selectors"] = ', '.join(str(int(v)) for v in vals[:_MAX_TARGET_BONES])


class DAT_OT_SubAnimBoneAdd(bpy.types.Operator):
    """Add a target bone to this sub-animation."""
    bl_idname = "dat.sub_anim_bone_add"
    bl_label = "Add Target Bone"
    bl_options = {'UNDO', 'INTERNAL'}

    prefix: StringProperty()

    def execute(self, context):
        obj = context.active_object
        names = _get_target_bones(obj, self.prefix)
        if len(names) >= _MAX_TARGET_BONES:
            self.report({'WARNING'}, "A sub-animation targets at most %d bones" % _MAX_TARGET_BONES)
            return {'CANCELLED'}
        # Seed the new slot with the first bone not already targeted so the row
        # is immediately valid; the user retargets it via the picker if needed.
        bone_names = [b.name for b in obj.data.bones]
        default = next((b for b in bone_names if b not in names), bone_names[0] if bone_names else "")
        names.append(default)
        _set_target_bones(obj, self.prefix, names)
        return {'FINISHED'}


class DAT_OT_SubAnimBoneRemove(bpy.types.Operator):
    """Remove a target bone from this sub-animation."""
    bl_idname = "dat.sub_anim_bone_remove"
    bl_label = "Remove Target Bone"
    bl_options = {'UNDO', 'INTERNAL'}

    prefix: StringProperty()
    index: IntProperty()

    def execute(self, context):
        obj = context.active_object
        names = _get_target_bones(obj, self.prefix)
        if 0 <= self.index < len(names):
            sels = _get_selectors(obj, self.prefix, len(names))
            names.pop(self.index)
            sels.pop(self.index)
            _set_target_bones(obj, self.prefix, names)
            _set_selectors(obj, self.prefix, sels)
        return {'FINISHED'}


class DAT_OT_SubAnimBoneSet(bpy.types.Operator):
    """Pick the bone this target slot points at (searchable popup)."""
    bl_idname = "dat.sub_anim_bone_set"
    bl_label = "Set Target Bone"
    bl_options = {'UNDO', 'INTERNAL'}

    prefix: StringProperty()
    index: IntProperty()
    bone: StringProperty(name="Bone")

    def invoke(self, context, event):
        obj = context.active_object
        names = _get_target_bones(obj, self.prefix)
        if 0 <= self.index < len(names):
            self.bone = names[self.index]
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        obj = context.active_object
        self.layout.prop_search(self, "bone", obj.data, "bones", text="Bone")

    def execute(self, context):
        obj = context.active_object
        names = _get_target_bones(obj, self.prefix)
        if 0 <= self.index < len(names):
            names[self.index] = self.bone
            _set_target_bones(obj, self.prefix, names)
        return {'FINISHED'}


class DAT_OT_SubAnimSelectorSet(bpy.types.Operator):
    """Set the per-part texture selector for a targeted-texture entry."""
    bl_idname = "dat.sub_anim_selector_set"
    bl_label = "Set Texture Selector"
    bl_options = {'UNDO', 'INTERNAL'}

    prefix: StringProperty()
    index: IntProperty()
    # 0xFF is the joint sentinel, so a texture selector must stay in 0-254.
    selector: IntProperty(name="Selector", min=0, max=254)

    def invoke(self, context, event):
        obj = context.active_object
        n = len(_get_target_bones(obj, self.prefix))
        sels = _get_selectors(obj, self.prefix, n)
        if 0 <= self.index < len(sels):
            self.selector = sels[self.index]
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        self.layout.prop(self, "selector")

    def execute(self, context):
        obj = context.active_object
        n = len(_get_target_bones(obj, self.prefix))
        sels = _get_selectors(obj, self.prefix, n)
        if 0 <= self.index < len(sels):
            sels[self.index] = self.selector
            _set_selectors(obj, self.prefix, sels)
        return {'FINISHED'}


def _draw_enum_dropdown(layout, obj, prop_key, items, label="", as_int=False):
    """Draw a row of toggle buttons for a custom property enum.

    Args:
        layout: UILayout to draw into.
        obj: Object with the custom property.
        prop_key: Custom property key name.
        items: list of (value, display_label) tuples. Values are always strings.
        label: Row label (empty = no label).
        as_int: If True, store the value as int instead of string.
    """
    current = str(obj.get(prop_key, ""))

    row = layout.row(align=True)
    if label:
        row.label(text=label)
    sub = row.row(align=True)
    for val, lbl in items:
        op = sub.operator("dat.set_enum_prop", text=lbl,
                          depress=(val == current))
        op.prop_key = prop_key
        op.value = val
        op.as_int = as_int


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
    ("blink", "Blink"), ("talk", "Talk"),
]
# Sub-animation (PartAnimData) type. Values mirror _SUB_TYPE_MAP on the export
# side (exporter/phases/describe/helpers/scene.py). Labels reflect what the
# engine does with each (see file_formats.md § Sub-Animation System):
#   none              has_data==0 — block off
#   whole_texture     has_data==1 — whole-model texture/material animation
#   targeted_texture  has_data==2, selectors != 0xFF — per-part texture on listed bones
#   targeted_joint    has_data==2, selectors == 0xFF — joint animation on listed bones
# Both targeted kinds are XD-only (Colosseum has no per-part bone config).
_SUB_ANIM_TYPE_ITEMS = [
    ("none", "Off"),
    ("whole_texture", "Whole-Model Texture"),
    ("targeted_texture", "Targeted Texture"),
    ("targeted_joint", "Targeted Joints"),
]

# Property key suffixes for body map bones.
# Slots 0-7 are the well-known engine body parts (root, head tracking, etc.).
# Slots 8-15 are extended slots that carry particle-attachment bones on
# effect-themed Pokémon; `ModelSequence::GetPart(slot)` resolves any slot
# 0-15 into the current animation entry's bone index.
from .shared.helpers.pkx_header import BODY_MAP_KEYS as _BODY_MAP_KEYS


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
        return (obj is not None and obj.type == 'ARMATURE' and
                obj.get("dat_pkx_format") is not None)

    def draw(self, context):
        obj = context.active_object
        layout = self.layout

        from .shared.helpers.pkx_header import (
            XD_POKEMON_ANIM_NAMES, XD_TRAINER_ANIM_NAMES, BODY_MAP_NAMES,
        )

        # === General ===
        box = layout.box()
        box.label(text="General", icon='INFO')
        _draw_enum_dropdown(box, obj, "dat_pkx_format", _FORMAT_ITEMS, label="Format:")
        if "dat_pkx_species_id" in obj:
            box.prop(obj, '["dat_pkx_species_id"]', text="Species ID")
        if "dat_pkx_model_type" in obj:
            _draw_enum_dropdown(box, obj, "dat_pkx_model_type", _MODEL_TYPE_ITEMS, label="Model Type:")
        if "dat_pkx_head_bone" in obj:
            box.prop_search(obj, '["dat_pkx_head_bone"]', obj.data, "bones", text="Head Bone")
        if "dat_pkx_particle_orientation" in obj:
            _draw_enum_dropdown(box, obj, "dat_pkx_particle_orientation",
                                _PARTICLE_ORIENT_ITEMS, label="Particle Orientation:",
                                as_int=True)

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

        # === Particles (GPT1) ===
        # Particle visualization is disabled until we identify the
        # generator→bone binding mechanism — see
        # importer/phases/build_blender/helpers/particles.py for context.
        gen_count = obj.get("dat_particle_gen_count", 0)
        if gen_count:
            box = layout.box()
            box.label(text="Particles (GPT1)", icon='PARTICLES')
            col = box.column(align=True)
            col.scale_y = 0.8
            col.label(text=f"{gen_count} generators parsed; not visualised.", icon='INFO')
            col.label(text="Binding to bones isn't stored in the model.")

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

        # === Distortion ===
        dist_param = obj.get("dat_pkx_distortion_param", 0)
        dist_type = obj.get("dat_pkx_distortion_type", 0)
        if dist_param or dist_type:
            box = layout.box()
            box.label(text="Distortion", icon='MOD_WAVE')
            box.prop(obj, '["dat_pkx_distortion_type"]', text="Type")
            box.prop(obj, '["dat_pkx_distortion_param"]', text="Parameter")

        # === Particles ===
        ptl_count = obj.get("dat_particle_count", 0)
        if ptl_count:
            box = layout.box()
            box.label(text="Particles", icon='PARTICLES')
            _prop_row(box, "Generators", ptl_count)
            _prop_row(box, "Textures", obj.get("dat_particle_texture_count", 0))

        # === Body Map ===
        box = layout.box()
        box.label(text="Body Map", icon='BONE_DATA')
        col = box.column(align=True)
        for j, jk in enumerate(_BODY_MAP_KEYS):
            key = "dat_pkx_body_%s" % jk
            if key in obj:
                label = BODY_MAP_NAMES[j] if j < len(BODY_MAP_NAMES) else jk
                col.prop_search(obj, '["%s"]' % key, obj.data, "bones", text=label)

        # === Sub-Animations (Part Anim Data) ===
        if obj.get("dat_pkx_sub_anim_0_type") is not None:
            box = layout.box()
            header = box.row(align=True)
            icon = 'TRIA_DOWN' if obj.dat_pkx_sub_anim_expand else 'TRIA_RIGHT'
            header.prop(obj, "dat_pkx_sub_anim_expand", icon=icon,
                        text="Sub-Animations", emboss=False)
            if obj.dat_pkx_sub_anim_expand:
                for i in range(4):
                    prefix = "dat_pkx_sub_anim_%d" % i
                    sub_box = box.box()
                    # The trigger is fixed by the block's position (block 0 fires
                    # on sleep, 1 on wake, 2 on blink/idle, 3 on talk/speak).
                    # It is not stored or exported, so show it read-only.
                    trigger = obj.get(prefix + "_trigger", "unknown")
                    trigger_label = next(
                        (lbl for val, lbl in _SUB_ANIM_TRIGGER_ITEMS if val == trigger),
                        trigger.replace('_', ' ').title(),
                    )
                    sub_box.label(text="Trigger: %s" % trigger_label, icon='TIME')
                    # Both targeted kinds are XD-only; Colosseum has no per-part
                    # bone config, so only None / Whole-Model Texture apply.
                    if obj.get("dat_pkx_format") == "COLOSSEUM":
                        _type_items = [it for it in _SUB_ANIM_TYPE_ITEMS
                                       if it[0] in ("none", "whole_texture")]
                    else:
                        _type_items = _SUB_ANIM_TYPE_ITEMS
                    _draw_enum_dropdown(sub_box, obj, prefix + "_type",
                                        _type_items, label="Type:")
                    cur_type = obj.get(prefix + "_type")
                    is_targeted = cur_type in ("targeted_texture", "targeted_joint")
                    # The referenced clip is a texture animation for the texture
                    # types, or a joint animation for Targeted Joints.
                    ref_key = prefix + "_anim_ref"
                    if cur_type in ("whole_texture", "targeted_texture", "targeted_joint") \
                            and ref_key in obj:
                        sub_box.prop_search(obj, '["%s"]' % ref_key, bpy.data, "actions",
                                            text="Animation")
                    # Targeted types restrict the overlay to specific bones/parts
                    # (bone_config); the whole-model types don't use a part list.
                    # Targeted Texture additionally carries a per-part selector.
                    if is_targeted:
                        show_selector = (cur_type == "targeted_texture")
                        names = _get_target_bones(obj, prefix)
                        selectors = _get_selectors(obj, prefix, len(names))
                        col = sub_box.column(align=True)
                        noun = "Parts" if show_selector else "Bones"
                        col.label(text="Target %s (%d/%d):" % (noun, len(names), _MAX_TARGET_BONES))
                        for bi, bn in enumerate(names):
                            row = col.row(align=True)
                            op = row.operator("dat.sub_anim_bone_set",
                                              text=bn if bn else "(select bone)",
                                              icon='BONE_DATA')
                            op.prefix = prefix
                            op.index = bi
                            if show_selector:
                                sel = row.operator("dat.sub_anim_selector_set",
                                                   text="tex %d" % selectors[bi])
                                sel.prefix = prefix
                                sel.index = bi
                            rm = row.operator("dat.sub_anim_bone_remove", text="", icon='X')
                            rm.prefix = prefix
                            rm.index = bi
                        if len(names) < _MAX_TARGET_BONES:
                            add = col.operator("dat.sub_anim_bone_add",
                                               text="Add %s" % ("Part" if show_selector else "Bone"),
                                               icon='ADD')
                            add.prefix = prefix

        # === Animation Slots ===
        anim_count = obj.get("dat_pkx_anim_count", 0)
        if anim_count:
            box = layout.box()
            box.label(text="Animation Slots", icon='ACTION')

            model_type = obj.get("dat_pkx_model_type", "POKEMON")
            slot_names = XD_TRAINER_ANIM_NAMES if model_type == "TRAINER" else XD_POKEMON_ANIM_NAMES

            for i in range(anim_count):
                slot_label = slot_names[i] if i < len(slot_names) else "Slot %d" % i
                prefix = "dat_pkx_anim_%02d" % i

                # Expand/collapse header
                is_expanded = obj.dat_pkx_anim_expand[i] if i < 17 else False
                header = box.row(align=True)
                icon = 'TRIA_DOWN' if is_expanded else 'TRIA_RIGHT'
                header.prop(obj, "dat_pkx_anim_expand", index=i, icon=icon,
                            text=slot_label, emboss=False)

                # Show active action name in the header row
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

                # Expanded content
                sub_box = box.box()

                # Type
                _draw_enum_dropdown(sub_box, obj, prefix + "_type",
                                    _ANIM_TYPE_ITEMS, label="Type:")

                # Sub-animations. Compound slots are Damage B by
                # convention — slot 0 is the hit/damage clip, slot 1 is
                # the faint follow-through — so label them by their role
                # rather than as anonymous Action 1 / Action 2.
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

                # Timing — only show fields relevant to this animation type
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

                # Body map overrides
                has_overrides = False
                for j in range(16):
                    if obj.get(prefix + "_body_%s" % _BODY_MAP_KEYS[j]) is not None:
                        has_overrides = True
                        break
                if has_overrides:
                    col = sub_box.column(align=True)
                    col.label(text="Joint Overrides:")
                    for j in range(16):
                        jkey = prefix + "_body_%s" % _BODY_MAP_KEYS[j]
                        if jkey in obj:
                            label = BODY_MAP_NAMES[j] if j < len(BODY_MAP_NAMES) else _BODY_MAP_KEYS[j]
                            col.prop_search(obj, '["%s"]' % jkey, obj.data, "bones", text=label)


def _prop_row(layout, label, value):
    """Draw a label: value row in the panel."""
    row = layout.row()
    row.label(text="%s:" % label)
    row.label(text=str(value))


classes = (ImportHSD, ExportHSD, DAT_OT_SetEnumProp,
           DAT_OT_SubAnimBoneAdd, DAT_OT_SubAnimBoneRemove, DAT_OT_SubAnimBoneSet,
           DAT_OT_SubAnimSelectorSet,
           DAT_PT_PKXPanel)


_dat_props = [
    ('dat_pkx_shiny', BoolProperty(
        name="Shiny Preview",
        description="Toggle shiny color variant preview. When enabled, the shiny channel routing and brightness are applied to all materials",
        default=False, update=_on_shiny_toggle_update,
    )),
    # Defaults are identity (route 0/1/2/3) + neutral (0.0) so a model with no
    # real shiny round-trips as non-shiny. The non-identity "starting" preview
    # values are seeded by the apply-shiny / prep scripts when a user actually
    # adds a shiny variant to an arbitrary model.
    ('dat_pkx_shiny_route_r', EnumProperty(
        name="Route R", description="Which source color channel feeds the Red output",
        items=_SHINY_CHANNEL_ITEMS, default='0', update=_on_shiny_param_update,
    )),
    ('dat_pkx_shiny_route_g', EnumProperty(
        name="Route G", description="Which source color channel feeds the Green output",
        items=_SHINY_CHANNEL_ITEMS, default='1', update=_on_shiny_param_update,
    )),
    ('dat_pkx_shiny_route_b', EnumProperty(
        name="Route B", description="Which source color channel feeds the Blue output",
        items=_SHINY_CHANNEL_ITEMS, default='2', update=_on_shiny_param_update,
    )),
    ('dat_pkx_shiny_route_a', EnumProperty(
        name="Route A", description="Which source color channel feeds the Alpha output",
        items=_SHINY_CHANNEL_ITEMS, default='3', update=_on_shiny_param_update,
    )),
    ('dat_pkx_shiny_brightness_r', FloatProperty(
        name="Brightness R", description="Red brightness: -1 = black, 0 = unchanged, 1 = 2× bright",
        default=0.0, min=-1.0, max=1.0, step=1, precision=3, update=_on_shiny_param_update,
    )),
    ('dat_pkx_shiny_brightness_g', FloatProperty(
        name="Brightness G", description="Green brightness: -1 = black, 0 = unchanged, 1 = 2× bright",
        default=0.0, min=-1.0, max=1.0, step=1, precision=3, update=_on_shiny_param_update,
    )),
    ('dat_pkx_shiny_brightness_b', FloatProperty(
        name="Brightness B", description="Blue brightness: -1 = black, 0 = unchanged, 1 = 2× bright. Alpha brightness is forced to maximum by the game",
        default=0.0, min=-1.0, max=1.0, step=1, precision=3, update=_on_shiny_param_update,
    )),
    ('dat_pkx_anim_expand', BoolVectorProperty(
        name="Expand Animation Slots",
        description="Expand/collapse state for animation slot panels",
        size=17, default=[False] * 17,
    )),
    ('dat_pkx_sub_anim_expand', BoolProperty(
        name="Expand Sub-Animations",
        description="Expand/collapse the Sub-Animations panel",
        default=False,
    )),
]


_GX_FORMAT_ITEMS = [
    ('AUTO', 'Auto', 'Automatically select the best GX format based on pixel content'),
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


# Palette (TLUT) format for indexed textures (C4/C8/C14X2); ignored otherwise.
_PALETTE_FORMAT_ITEMS = [
    ('AUTO', 'Auto', 'Default palette format (RGB5A3) for indexed textures'),
    ('IA8', 'IA8 (Intensity+Alpha)', '8-bit intensity + 8-bit alpha, grayscale palette'),
    ('RGB565', 'RGB565 (No Alpha)', '16-bit RGB, no alpha'),
    ('RGB5A3', 'RGB5A3 (RGB+Alpha)', '16-bit with optional alpha'),
]


def register():
    for prop_name, prop in _dat_props:
        setattr(bpy.types.Object, prop_name, prop)
    bpy.types.Image.dat_gx_format = EnumProperty(
        name="GX Texture Format",
        description="GX texture format used when exporting this texture. Auto selects based on pixel content.",
        items=_GX_FORMAT_ITEMS,
        default='AUTO',
    )
    bpy.types.Image.dat_palette_format = EnumProperty(
        name="GX Palette Format",
        description="GX palette (TLUT) format used when exporting an indexed (C4/C8/C14X2) texture. Ignored for other formats.",
        items=_PALETTE_FORMAT_ITEMS,
        default='AUTO',
    )
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    for prop_name, _ in _dat_props:
        if hasattr(bpy.types.Object, prop_name):
            delattr(bpy.types.Object, prop_name)
    if hasattr(bpy.types.Image, 'dat_gx_format'):
        delattr(bpy.types.Image, 'dat_gx_format')
    if hasattr(bpy.types.Image, 'dat_palette_format'):
        delattr(bpy.types.Image, 'dat_palette_format')
