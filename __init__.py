# Entry point to the script when loaded via Blender

# metadata about the addon which blender requires
# https://wiki.blender.org/wiki/Process/Addons/Guidelines/metainfo
bl_info = {
    "name": "Gamecube Dat Model (Refactor)",
    "author": "Made, StarsMmd, MikeyX",
    "blender": (4, 5, 0),
    "location": "File > Import-Export",
    "description": "Import-Export Gamecube .dat models",
    "warning": "",
    "category": "Import-Export"}


if "bpy" in locals():
    pass

import os

try:
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
    from .legacy.importer import *
    from .legacy.exporter import *
    _bpy_available = True
except (ImportError, SystemError):
    _bpy_available = False

if _bpy_available:
    # This class declares global properties which blender uses to add toggles and fields to the file open browser
    # allowing more options to be selected along with the filepath being opened.
    # When a file is selected the execute() function runs.
    class ImportHSD(bpy.types.Operator, ImportHelper):
        """Load a DAT model"""
        bl_idname = "import_model.dat"
        bl_label = "Import DAT"
        bl_options = {'UNDO'}

        files: bpy.props.CollectionProperty(name="File Path",
                              description="File path used for importing "
                                          "the HSD file",
                              type=bpy.types.OperatorFileListElement)
        directory: bpy.props.StringProperty(subtype="DIR_PATH")
        section: bpy.props.StringProperty(default = '', name = 'Section Name', description = 'Name of the section that should be imported. Leave blank to import all.')
        ik_hack: bpy.props.BoolProperty(default = True, name = 'IK Hack', description = 'Shrinks Bones down to 1e-3 to make IK work properly.')
        max_frame: bpy.props.IntProperty(default = 1000, name = 'Max Anim Frame', description = 'Cutoff frame after which animations aren\'t sampled. Use 0 For no limit.')
        verbose: bpy.props.BoolProperty(default = False, name = 'Verbose', description = 'Print detailed logging output to the console for debugging.')
        setup_workspace: bpy.props.BoolProperty(default = False, name = 'Setup Workspace', description = 'Split the viewport and open a Dope Sheet / Action Editor. Sets playback end frame to 60.')
        use_ir: bpy.props.BoolProperty(default = False, name = 'Use Intermediate Representation Pipeline', description = 'Use the new Intermediate Representation-based import pipeline (experimental).')

        filename_ext = ".dat"
        filter_glob: StringProperty(default="*.fdat;*.dat;*.rdat;*.pkx", options={'HIDDEN'})

        def execute(self, context):
            if self.files and self.directory:
                paths = [os.path.join(self.directory, file.name) for file in self.files]
            else:
                paths = [self.filepath]

            for path in paths:
                try:
                    if self.use_ir:
                        status = _import_ir(context, path, self.section, self.ik_hack, self.max_frame, self.verbose)
                    else:
                        status = Importer.parseDAT(context, path, self.section, self.ik_hack, self.max_frame, self.verbose)
                except Exception as error:
                    self.report({'ERROR'}, "Import failed: %s" % error)
                    return {'CANCELLED'}
                if not 'FINISHED' in status:
                    return status

            if self.setup_workspace:
                _setup_anim_workspace(context)

            return {'FINISHED'}


    class ExportHSD(bpy.types.Operator, ExportHelper):
        bl_idname = "export_model.dat"
        bl_label = "Export DAT"

        @classmethod
        def poll(cls, context):
            return context.active_object is not None

        def execute(self, context):
            status = Exporter.writeDAT(context, self.filepath)
            if not 'FINISHED' in status:
                return status

            return {'FINISHED'}


    def _setup_anim_workspace(context):
        """Split the 3D viewport and open an Action Editor and NLA Editor. Set playback end to 60."""
        context.scene.frame_end = 60

        # Find the 3D Viewport area to split
        screen = context.screen
        view3d_area = None
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                view3d_area = area
                break

        if not view3d_area:
            return

        # First split: 3D viewport | right panel (will become Action Editor)
        with context.temp_override(area=view3d_area):
            bpy.ops.screen.area_split(direction='VERTICAL', factor=0.6)

        # Find the new area and make it the Action Editor
        dopesheet_area = None
        for area in screen.areas:
            if area.type == 'VIEW_3D' and area != view3d_area:
                area.type = 'DOPESHEET_EDITOR'
                for space in area.spaces:
                    if space.type == 'DOPESHEET_EDITOR':
                        space.mode = 'ACTION'
                dopesheet_area = area
                break

        if not dopesheet_area:
            return

        # Second split: Action Editor on top | NLA Editor on bottom
        areas_before = set(screen.areas)
        with context.temp_override(area=dopesheet_area):
            bpy.ops.screen.area_split(direction='HORIZONTAL', factor=0.5)

        # The new area is the one not in our previous set
        for area in screen.areas:
            if area not in areas_before:
                area.type = 'NLA_EDITOR'
                break

    def _import_ir(context, filepath, section_name='', ik_hack=True, max_frame=1000, verbose=False):
        """New Intermediate Representation-based import pipeline."""
        from .shared.IO.DAT_io import DATParser
        from .shared.IO.Logger import Logger
        from .phases.describe import describe_scene
        from .phases.build_blender import build_blender_scene

        model_name = os.path.basename(filepath).split('.')[0] if filepath else "unknown"
        logger = Logger(verbose=verbose, model_name=model_name)

        importer_options = {
            "ik_hack": ik_hack,
            "verbose": verbose,
            "max_frame": max_frame if max_frame > 0 else 1000000000,
            "section_names": [section_name] if len(section_name) > 0 else [],
            "filepath": filepath,
        }

        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action='DESELECT')

        parser = DATParser(filepath, importer_options, logger=logger)
        parser.parseSections()
        parser.close()

        if context is not None and len(parser.sections) > 0:
            ir_scene, raw_animations = describe_scene(parser.sections, importer_options, logger=logger)
            build_blender_scene(ir_scene, context, importer_options, logger=logger, raw_animations=raw_animations)

        logger.info("Log file: %s", logger.log_path)
        logger.close()
        return {'FINISHED'}

    def menu_func_import(self, context):
        self.layout.operator(ImportHSD.bl_idname, text="Gamecube DAT Model - Refactor (.dat)")


    def menu_func_export(self, context):
        self.layout.operator(ExportHSD.bl_idname, text="Gamecube DAT Model - Refactor (.dat)")


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
