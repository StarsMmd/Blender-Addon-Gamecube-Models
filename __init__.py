bl_info = {
    "name": "Gamecube Dat Model",
    "author": "M",
    "blender": (3, 1, 0),
    "location": "File > Import-Export",
    "description": "Import-Export Gamecube .dat models",
    "warning": "",
    "category": "Import-Export"}


if "bpy" in locals():
    import importlib
    if "hsd" in locals():
        importlib.reload(hsd)
    if "import_hsd" in locals():
        importlib.reload(import_hsd)
    if "util" in locals():
        importlib.reload(util)


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
    section: bpy.props.StringProperty(default = 'scene_data', name = 'Section Name', description = 'Name of the section that should be imported as a scene')
    offset: bpy.props.IntProperty(default = 0, name = 'Offset', description = 'Offset of the Scene data in the file')
    data_type: bpy.props.EnumProperty(
                items = (('SCENE', 'Scene', 'Import Scene'),
                         ('BONE', 'Bone', 'Import Armature')
                        ), name = 'Data Type', description = 'The type of data that is stored in the section')
    import_animation: bpy.props.BoolProperty(default = True, name = 'Import Animation', description = 'Whether to import animation. Off by default while it\'s still very buggy')
    ik_hack: bpy.props.BoolProperty(default = True, name = 'IK Hack', description = 'Shrinks Bones down to 1e-3 to make IK work properly')
    use_max_frame: bpy.props.BoolProperty(default = True, name = 'Use Max Anim Frame', description = 'Limits the sampled animation range to a maximum length')
    max_frame: bpy.props.IntProperty(default = 1000, name = 'Max Anim Frame', description = 'Cutoff frame after which animations aren\'t sampled')

    filename_ext = ".dat"
    filter_glob = StringProperty(default="*.fdat;*.dat;*.rdat;*.pkx", options={'HIDDEN'})

    def execute(self, context):
        if self.files and self.directory:
            paths = [os.path.join(self.directory, file.name) for file in self.files]
        else:
            paths = [self.filepath]

        from . import import_hsd

        #import trace
        #tracer = trace.Trace(trace=1)

        for path in paths:
            status = import_hsd.load(self, context, path, self.offset, self.section, self.data_type, self.import_animation, self.ik_hack, self.max_frame, self.use_max_frame)
            #tracer.runctx('import_hsd.load(self, context, path, self.offset, self.section)', globals(), locals())
            #r = tracer.results()
            #r.write_results(show_missing=False, coverdir=".")
            if not 'FINISHED' in status:
                return status

        return {'FINISHED'}


class ExportHSD(bpy.types.Operator, ExportHelper):
    """Export a single object as a Stanford PLY with normals, """ \
    """colors and texture coordinates"""
    bl_idname = "export_scene.hsd"
    bl_label = "Export HSD"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        pass

    def draw(self, context):
        pass
    """
    bl_idname = "export_mesh.ply"
    bl_label = "Export PLY"

    filename_ext = ".ply"
    filter_glob = StringProperty(default="*.ply", options={'HIDDEN'})

    use_mesh_modifiers = BoolProperty(
            name="Apply Modifiers",
            description="Apply Modifiers to the exported mesh",
            default=True,
            )
    use_normals = BoolProperty(
            name="Normals",
            description="Export Normals for smooth and "
                        "hard shaded faces "
                        "(hard shaded faces will be exported "
                        "as individual faces)",
            default=True,
            )
    use_uv_coords = BoolProperty(
            name="UVs",
            description="Export the active UV layer",
            default=True,
            )
    use_colors = BoolProperty(
            name="Vertex Colors",
            description="Export the active vertex color layer",
            default=True,
            )

    global_scale = FloatProperty(
            name="Scale",
            min=0.01, max=1000.0,
            default=1.0,
            )

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        from . import export_ply

        from mathutils import Matrix

        keywords = self.as_keywords(ignore=("axis_forward",
                                            "axis_up",
                                            "global_scale",
                                            "check_existing",
                                            "filter_glob",
                                            ))
        global_matrix = axis_conversion(to_forward=self.axis_forward,
                                        to_up=self.axis_up,
                                        ).to_4x4() * Matrix.Scale(self.global_scale, 4)
        keywords["global_matrix"] = global_matrix

        filepath = self.filepath
        filepath = bpy.path.ensure_ext(filepath, self.filename_ext)

        return export_ply.save(self, context, **keywords)

    def draw(self, context):
        layout = self.layout

        row = layout.row()
        row.prop(self, "use_mesh_modifiers")
        row.prop(self, "use_normals")
        row = layout.row()
        row.prop(self, "use_uv_coords")
        row.prop(self, "use_colors")

        layout.prop(self, "axis_forward")
        layout.prop(self, "axis_up")
        layout.prop(self, "global_scale")
    """


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
