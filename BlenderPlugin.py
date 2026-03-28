"""Blender addon operators and registration for the DAT model importer/exporter."""
import os
import bpy
from bpy.props import StringProperty, BoolProperty, IntProperty, CollectionProperty
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


classes = (ImportHSD, ExportHSD)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
