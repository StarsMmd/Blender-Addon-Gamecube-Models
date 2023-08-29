# Entry point to the script when loaded via Blender

# metadata about the addon which blender requires
# https://wiki.blender.org/wiki/Process/Addons/Guidelines/metainfo
bl_info = {
    "name": "Gamecube Dat Model",
    "author": "Made, StarsMmd, MikeyX",
    "blender": (3, 1, 0),
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

# This class declares global properties which blender uses to add toggles and fields to the file open browser
# allowing more options to be selected along with the filepath being opened.
# When a file is selected the execute() function runs.
class ImportHSD(bpy.types.Operator, ImportHelper):
    """Load a HSD scene"""
    bl_idname = "import_scene.hsd"
    bl_label = "Import HSD"
    bl_options = {'UNDO'}

    files: bpy.props.CollectionProperty(name="File Path",
                          description="File path used for importing "
                                      "the HSD file",
                          type=bpy.types.OperatorFileListElement)
    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    section: bpy.props.StringProperty(default = '', name = 'Section Name', description = 'Name of the section that should be imported. Leave blank to import all.')
    ik_hack: bpy.props.BoolProperty(default = True, name = 'IK Hack', description = 'Shrinks Bones down to 1e-3 to make IK work properly.')
    max_frame: bpy.props.IntProperty(default = 1000, name = 'Max Anim Frame', description = 'Cutoff frame after which animations aren\'t sampled. Use 0 For no limit.')

    filename_ext = ".dat"
    filter_glob = StringProperty(default="*.fdat;*.dat;*.rdat;*.pkx", options={'HIDDEN'})

    def execute(self, context):
        if self.files and self.directory:
            paths = [os.path.join(self.directory, file.name) for file in self.files]
        else:
            paths = [self.filepath]

        for path in paths:
            status = Importer.parseDAT(context, path, self.section, self.ik_hack, self.max_frame, False)
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
        status = Exporter.writeDAT(context, path)
        if not 'FINISHED' in status:
            return status

        return {'FINISHED'}


def menu_func_import(self, context):
    self.layout.operator(ImportHSD.bl_idname, text="Gamecube Dat Model (.dat)")


def menu_func_export(self, context):
    self.layout.operator(ExportHSD.bl_idname, text="Gamecube Dat Model (.dat)")


classes = (
    ImportHSD,
    ExportHSD,
)

# This function is called when the addon is installed by the user. The classes are registered and added to the blender menus.
def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)

# This function is called when the addon is uninstalled by the user. The classes are unregistered and removed from the blender menus.
def unregister():
    for cls in classes:
        bpy.utils.unregister_class(cls)

    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)

# This function is called when the addon is run as a script from within blender's scripting window
if __name__ == "__main__":
    register()
