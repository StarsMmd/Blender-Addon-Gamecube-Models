"""Blender addon operators and registration for the DAT model importer/exporter."""
import os
import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty, FloatProperty, EnumProperty, CollectionProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

from .legacy.importer import *
from .legacy.exporter import *
from .importer import Importer as IRImporter
from .shared.helpers.logger import Logger, StubLogger


class ImportHSD(bpy.types.Operator, ImportHelper):
    """Load a DAT model"""
    bl_idname = "import_model.dat"
    bl_label = "Import DAT"
    bl_options = {'UNDO'}

    files: CollectionProperty(name="File Path",
                          description="File path used for importing the HSD file",
                          type=bpy.types.OperatorFileListElement)
    directory: StringProperty(subtype="DIR_PATH")
    section: StringProperty(default='', name='Section Name',
                           description='Name of the section that should be imported. Leave blank to import all.')
    ik_hack: BoolProperty(default=True, name='IK Hack',
                         description='Shrinks Bones down to 1e-3 to make IK work properly.')
    max_frame: IntProperty(default=1000, name='Max Anim Frame',
                          description='Cutoff frame after which animations aren\'t sampled. Use 0 For no limit.')
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
                    status = Importer.parseDAT(context, path, self.section, self.ik_hack, self.max_frame, verbose=False)
                    if 'FINISHED' not in status:
                        return status
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
            "max_frame": self.max_frame if self.max_frame > 0 else 1000000000,
            "section_names": [self.section] if len(self.section) > 0 else [],
            "filepath": path,
            "import_lights": self.import_lights,
            "include_shiny": self.include_shiny,
        }

        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action='DESELECT')

        IRImporter.run(context, raw_bytes, filename, options, logger=logger)


class ExportHSD(bpy.types.Operator, ExportHelper):
    bl_idname = "export_model.dat"
    bl_label = "Export DAT"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        status = Exporter.writeDAT(context, self.filepath)
        if 'FINISHED' not in status:
            return status
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
        bpy.ops.screen.area_split(direction='VERTICAL', factor=0.6)

    for area in screen.areas:
        if area.type == 'VIEW_3D' and area != view3d_area:
            area.type = 'DOPESHEET_EDITOR'
            for space in area.spaces:
                if space.type == 'DOPESHEET_EDITOR':
                    space.mode = 'ACTION'
            break


def menu_func_import(self, context):
    self.layout.operator(ImportHSD.bl_idname, text="Gamecube DAT Model - Refactor (.dat)")


def menu_func_export(self, context):
    self.layout.operator(ExportHSD.bl_idname, text="Gamecube DAT Model - Refactor (.dat)")


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
    from .importer.phases.build_blender.helpers.shiny_filter import rebuild_shiny_node_group
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
