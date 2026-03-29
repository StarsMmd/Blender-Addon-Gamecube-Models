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
    import_lights: BoolProperty(default=False, name='Import Lights',
                               description='Import light sets from the model file.')
    include_shiny: BoolProperty(default=True, name='Include Shiny Variant',
                               description='Extract shiny color parameters from PKX files and add a toggleable shiny filter to materials.')
    use_legacy: BoolProperty(default=False, name='Use Legacy Importer',
                            description='Use the old import pipeline instead of the new Intermediate Representation pipeline.')

    filename_ext = ".dat"
    filter_glob: StringProperty(default="*.fdat;*.dat;*.rdat;*.pkx;*.fsys", options={'HIDDEN'})

    def execute(self, context):
        if self.files and self.directory:
            paths = [os.path.join(self.directory, file.name) for file in self.files]
        else:
            paths = [self.filepath]

        for path in paths:
            try:
                if self.use_legacy:
                    self._import_legacy(context, path)
                else:
                    self._import_ir(context, path)
            except Exception as error:
                self.report({'ERROR'}, "Import failed: %s" % error)
                return {'CANCELLED'}

        if self.setup_workspace:
            _setup_anim_workspace(context)

        return {'FINISHED'}

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
        """Run Phase 1 (extract) + Phase 2 (route), legacy import, then Phase 6 (post-process)."""
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
    bl_idname = "export_model.dat"
    bl_label = "Export DAT"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        self.report({'WARNING'}, "Export is not yet implemented.")
        return {'CANCELLED'}


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


class DAT_PT_ShinyPanel(bpy.types.Panel):
    """Panel for the shiny color variant parameters."""
    bl_label = "Shiny Variant"
    bl_idname = "OBJECT_PT_dat_shiny"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "object"

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == 'ARMATURE' and obj.get("dat_has_shiny", False)

    def draw(self, context):
        obj = context.active_object
        layout = self.layout

        layout.prop(obj, "dat_shiny", text="Enable")

        col = layout.column()
        col.active = obj.dat_shiny

        col.label(text="Channel Routing:")
        row = col.row(align=True)
        row.prop(obj, "dat_shiny_route_r", text="R")
        row.prop(obj, "dat_shiny_route_g", text="G")
        row = col.row(align=True)
        row.prop(obj, "dat_shiny_route_b", text="B")
        row.prop(obj, "dat_shiny_route_a", text="A")

        col.label(text="Brightness:")
        col.prop(obj, "dat_shiny_brightness_r", text="R")
        col.prop(obj, "dat_shiny_brightness_g", text="G")
        col.prop(obj, "dat_shiny_brightness_b", text="B")
        col.prop(obj, "dat_shiny_brightness_a", text="A")


classes = (ImportHSD, ExportHSD, DAT_PT_ShinyPanel)


_SHINY_CHANNEL_ITEMS = [
    ('RED', 'Red', 'Red channel'),
    ('GREEN', 'Green', 'Green channel'),
    ('BLUE', 'Blue', 'Blue channel'),
    ('ALPHA', 'Alpha', 'Alpha channel'),
]


def _on_shiny_toggle_update(obj, context):
    """Force viewport refresh when the Shiny toggle changes."""
    obj.update_tag()
    for child in obj.children:
        if child.type == 'MESH' and child.active_material:
            child.active_material.node_tree.update_tag()
    if context and context.area:
        context.area.tag_redraw()


def _on_shiny_param_update(obj, context):
    """Rebuild the shiny node group and refresh the viewport when a parameter changes."""
    from .importer.phases.post_process.shiny_filter import rebuild_shiny_node_group
    rebuild_shiny_node_group(obj)
    obj.update_tag()
    for child in obj.children:
        if child.type == 'MESH' and child.active_material:
            child.active_material.node_tree.update_tag()
    if context and context.area:
        context.area.tag_redraw()


_shiny_props = [
    ('dat_shiny', BoolProperty(
        name="Shiny", description="Toggle shiny color variant",
        default=False, update=_on_shiny_toggle_update,
    )),
    ('dat_shiny_route_r', EnumProperty(
        name="Route R", description="Source channel for red output",
        items=_SHINY_CHANNEL_ITEMS, default='RED', update=_on_shiny_param_update,
    )),
    ('dat_shiny_route_g', EnumProperty(
        name="Route G", description="Source channel for green output",
        items=_SHINY_CHANNEL_ITEMS, default='GREEN', update=_on_shiny_param_update,
    )),
    ('dat_shiny_route_b', EnumProperty(
        name="Route B", description="Source channel for blue output",
        items=_SHINY_CHANNEL_ITEMS, default='BLUE', update=_on_shiny_param_update,
    )),
    ('dat_shiny_route_a', EnumProperty(
        name="Route A", description="Source channel for alpha output",
        items=_SHINY_CHANNEL_ITEMS, default='ALPHA', update=_on_shiny_param_update,
    )),
    ('dat_shiny_brightness_r', FloatProperty(
        name="Brightness R", description="Red channel brightness (-1 = black, 0 = unchanged, 1 = 2x bright)",
        default=0.0, min=-1.0, max=1.0, step=1, precision=3, update=_on_shiny_param_update,
    )),
    ('dat_shiny_brightness_g', FloatProperty(
        name="Brightness G", description="Green channel brightness (-1 = black, 0 = unchanged, 1 = 2x bright)",
        default=0.0, min=-1.0, max=1.0, step=1, precision=3, update=_on_shiny_param_update,
    )),
    ('dat_shiny_brightness_b', FloatProperty(
        name="Brightness B", description="Blue channel brightness (-1 = black, 0 = unchanged, 1 = 2x bright)",
        default=0.0, min=-1.0, max=1.0, step=1, precision=3, update=_on_shiny_param_update,
    )),
    ('dat_shiny_brightness_a', FloatProperty(
        name="Brightness A", description="Alpha channel brightness (-1 = black, 0 = unchanged, 1 = 2x bright)",
        default=0.0, min=-1.0, max=1.0, step=1, precision=3, update=_on_shiny_param_update,
    )),
]


def register():
    for prop_name, prop in _shiny_props:
        setattr(bpy.types.Object, prop_name, prop)
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    for prop_name, _ in _shiny_props:
        if hasattr(bpy.types.Object, prop_name):
            delattr(bpy.types.Object, prop_name)
