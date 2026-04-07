"""Blender addon operators and registration for the DAT model importer/exporter."""
import os
import bpy
from bpy.props import StringProperty, BoolProperty, FloatProperty, EnumProperty, CollectionProperty
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
    ik_hack: BoolProperty(default=True, name='IK Hack',
                         description='Shrinks Bones down to 1e-3 to make IK work properly.')
    write_logs: BoolProperty(default=True, name='Write Logs',
                            description='Write import logs to a temp file for debugging.')
    setup_workspace: BoolProperty(default=True, name='Setup Workspace',
                                 description='Split the viewport and open an Action Editor. Sets playback end frame to 60.')
    import_lights: BoolProperty(default=True, name='Import Lights',
                               description='Import light sets from the model file.')
    include_shiny: BoolProperty(default=True, name='Include Shiny Variant',
                               description='Extract shiny color parameters from PKX files and add a toggleable shiny filter to materials.')
    use_legacy: BoolProperty(default=False, name='Use Legacy Importer',
                            description='Use the old import pipeline instead of the new Intermediate Representation pipeline.')

    filename_ext = ".dat"
    filter_glob: StringProperty(default="*.fdat;*.dat;*.rdat;*.pkx;*.fsys;*.wzx", options={'HIDDEN'})

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

        if self.write_logs:
            logger = Logger(model_name=model_name)
        else:
            logger = StubLogger()

        options = {
            "ik_hack": self.ik_hack,
            "max_frame": 10000,
            "filepath": path,
            "import_lights": self.import_lights,
            "include_shiny": self.include_shiny,
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

        legacy_import_hsd.ikhack = self.ik_hack
        legacy_import_hsd.anim_max_frame = 10000
        legacy_import_hsd.write_logs = self.write_logs
        legacy_import_hsd.import_lights = self.import_lights

        options = {"include_shiny": False}

        for dat_bytes, metadata in entries:
            section_map = route_sections(dat_bytes)

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
    strip_names: BoolProperty(default=False, name='Strip Node Names',
                             description='Remove bone/node names from the output. Enable for compatibility with models that have empty name fields.')

    @classmethod
    def poll(cls, context):
        return any(obj.type == 'ARMATURE' for obj in context.scene.objects)

    def execute(self, context):
        from .exporter.exporter import Exporter

        model_name = os.path.splitext(os.path.basename(self.filepath))[0] or "export"

        if self.write_logs:
            logger = Logger(model_name=model_name)
        else:
            logger = StubLogger()

        options = {
            'strip_names': self.strip_names,
        }

        try:
            Exporter.run(context, self.filepath, options, logger=logger)
        except Exception as error:
            self.report({'ERROR'}, "Export failed: %s" % error)
            logger.error("Export failed: %s", error)
            logger.close()
            return {'CANCELLED'}

        self.report({'INFO'}, "Exported to %s" % self.filepath)
        return {'FINISHED'}


def _setup_anim_workspace(context):
    """Split the 3D viewport and open an Action Editor. Set playback end to 60.

    Skips setup if a Dope Sheet / Action Editor is already visible.
    """
    # Check if an Action Editor is already showing
    for area in context.screen.areas:
        if area.type == 'DOPESHEET_EDITOR':
            for space in area.spaces:
                if space.type == 'DOPESHEET_EDITOR' and space.mode == 'ACTION':
                    return  # Already set up

    context.scene.frame_end = 60

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
        _sync_shiny_props_to_custom(obj)
        from .importer.phases.post_process.shiny_filter import rebuild_shiny_node_group
        rebuild_shiny_node_group(obj)
    _refresh_shiny_viewport(obj, context)


def _on_shiny_param_update(obj, context):
    """Write registered props back to PKX custom properties and rebuild if shiny is on."""
    _sync_shiny_props_to_custom(obj)
    if obj.dat_pkx_shiny:
        from .importer.phases.post_process.shiny_filter import rebuild_shiny_node_group
        rebuild_shiny_node_group(obj)
    _refresh_shiny_viewport(obj, context)


def _sync_shiny_props_to_custom(obj):
    """Write registered shiny properties back to dat_pkx_ custom properties."""
    obj["dat_pkx_shiny_route"] = [
        int(obj.dat_pkx_shiny_route_r),
        int(obj.dat_pkx_shiny_route_g),
        int(obj.dat_pkx_shiny_route_b),
        int(obj.dat_pkx_shiny_route_a),
    ]
    obj["dat_pkx_shiny_brightness"] = [
        obj.dat_pkx_shiny_brightness_r,
        obj.dat_pkx_shiny_brightness_g,
        obj.dat_pkx_shiny_brightness_b,
    ]


def _refresh_shiny_viewport(obj, context):
    """Tag objects and materials for viewport refresh."""
    obj.update_tag()
    for child in obj.children:
        if child.type == 'MESH' and child.active_material:
            child.active_material.node_tree.update_tag()
    if context and context.area:
        context.area.tag_redraw()


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

        # --- Shiny Variant ---
        box = layout.box()
        box.label(text="Shiny Variant", icon='COLOR')
        if obj.get("dat_pkx_has_shiny"):
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
        else:
            box.label(text="No shiny data for this model")

        # --- General ---
        box = layout.box()
        box.label(text="General", icon='INFO')
        _prop_row(box, "Format", obj.get("dat_pkx_format", "—"))
        _prop_row(box, "Species ID", obj.get("dat_pkx_species_id", "—"))
        _prop_row(box, "Model Type", obj.get("dat_pkx_model_type", "—"))
        head_bone = obj.get("dat_pkx_head_bone", "")
        _prop_row(box, "Head Bone", head_bone if head_bone else "(none)")
        _prop_row(box, "Particle Orientation", obj.get("dat_pkx_particle_orientation", 0))

        # --- Flags ---
        box = layout.box()
        box.label(text="Flags", icon='PREFERENCES')
        col = box.column(align=True)
        for flag_key, flag_label in [
            ("dat_pkx_flag_flying", "Flying Mode"),
            ("dat_pkx_flag_skip_frac_frames", "Skip Fractional Frames"),
            ("dat_pkx_flag_no_root_anim", "No Root Joint Animation"),
            ("dat_pkx_flag_bit7", "Unknown (bit 7)"),
        ]:
            val = obj.get(flag_key, False)
            icon = 'CHECKBOX_HLT' if val else 'CHECKBOX_DEHLT'
            col.label(text=flag_label, icon=icon)

        # --- Distortion ---
        dist_param = obj.get("dat_pkx_distortion_param", 0)
        dist_type = obj.get("dat_pkx_distortion_type", 0)
        if dist_param or dist_type:
            box = layout.box()
            box.label(text="Distortion", icon='MOD_WAVE')
            _prop_row(box, "Type", dist_type)
            _prop_row(box, "Parameter", dist_param)

        # --- Particles ---
        ptl_count = obj.get("dat_particle_count", 0)
        if ptl_count:
            box = layout.box()
            box.label(text="Particles", icon='PARTICLES')
            _prop_row(box, "Generators", ptl_count)
            _prop_row(box, "Textures", obj.get("dat_particle_texture_count", 0))

        # --- Animations ---
        anim_count = obj.get("dat_pkx_anim_count", 0)
        if anim_count:
            box = layout.box()
            box.label(text="Animations", icon='ACTION')
            _prop_row(box, "Slots", anim_count)


def _prop_row(layout, label, value):
    """Draw a label: value row in the panel."""
    row = layout.row()
    row.label(text="%s:" % label)
    row.label(text=str(value))


classes = (ImportHSD, ExportHSD, DAT_PT_PKXPanel)


_dat_props = [
    ('dat_pkx_shiny', BoolProperty(
        name="Shiny Preview",
        description="Toggle shiny color variant preview. When enabled, the shiny channel routing and brightness are applied to all materials",
        default=False, update=_on_shiny_toggle_update,
    )),
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


def register():
    for prop_name, prop in _dat_props:
        setattr(bpy.types.Object, prop_name, prop)
    bpy.types.Image.dat_gx_format = EnumProperty(
        name="GX Texture Format",
        description="GX texture format used when exporting this texture. Auto selects based on pixel content.",
        items=_GX_FORMAT_ITEMS,
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
