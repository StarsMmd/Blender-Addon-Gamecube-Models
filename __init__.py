bl_info = {
    "name": "Gamecube Dat Model",
    "author": "Made",
    "blender": (2, 80, 0),
    "location": "File > Import-Export",
    "description": "Import-Export Gamecube .dat models",
    "warning": "",
    "category": "Import-Export"}


if "bpy" in locals():
    import importlib

import os
import bpy
from bpy.props import (
        CollectionProperty,
        StringProperty,
        BoolProperty,
        EnumProperty,
        FloatProperty,
        IntProperty,
)
from bpy_extras.io_utils import (
        ImportHelper,
        ExportHelper,
        axis_conversion,
)

from importer import importer
from exporter import exporter

class ImportHSD(bpy.types.Operator, ImportHelper):
    """Load a HSD scene"""
    bl_idname = "import_scene.hsd"
    bl_label = "Import HSD"
    bl_options = {'UNDO'}

    files = CollectionProperty(name="File Path",
                          description="File path used for importing "
                                      "the HSD file",
                          type=bpy.types.OperatorFileListElement)

    directory = StringProperty()
    section = StringProperty(default = 'scene_data', name = 'Section Name', description = 'Name of the section that should be imported as a scene')
    data_type = EnumProperty(
                items = (('SCENE', 'Scene', 'Import Scene'),
                         ('BONE', 'Bone', 'Import Armature')
                        ), name = 'Data Type', description = 'The type of data that is stored in the section')
    import_animation = BoolProperty(default = True, name = 'Import Animation', description = 'Whether to import animation. Off by default while it\'s still very buggy')
    ik_hack = BoolProperty(default = True, name = 'IK Hack', description = 'Shrinks Bones down to 1e-3 to make IK work properly')
    use_max_frame = BoolProperty(default = True, name = 'Use Max Anim Frame', description = 'Limits the sampled animation range to a maximum length')
    max_frame = IntProperty(default = 1000, name = 'Max Anim Frame', description = 'Cutoff frame after which animations aren\'t sampled')

    filename_ext = ".dat"
    filter_glob = StringProperty(default="*.fdat;*.dat;*.rdat;*.pkx", options={'HIDDEN'})

    def execute(self, context):
        paths = [os.path.join(self.directory, name.name)
                 for name in self.files]
        if not paths:
            paths.append(self.filepath)

        for path in paths:
            status = Importer.parseDAT(self, context, path, self.section, self.data_type, self.import_animation, self.ik_hack, self.max_frame, self.use_max_frame)
            if not 'FINISHED' in status:
                return status

        return {'FINISHED'}


class ExportHSD(bpy.types.Operator, ExportHelper):
    bl_idname = "export_scene.hsd"
    bl_label = "Export HSD"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        pass


def menu_func_import(self, context):
    self.layout.operator(ImportHSD.bl_idname, text="Gamecube Dat Model (.dat)")


def menu_func_export(self, context):
    self.layout.operator(ExportHSD.bl_idname, text="Gamecube Dat Model (.dat)")


classes = (
    ImportHSD,
    ExportHSD,
)

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


if __name__ == "__main__":
    register()
