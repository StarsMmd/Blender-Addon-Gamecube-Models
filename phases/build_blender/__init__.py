"""Phase 5A: Build Blender scene objects from an Intermediate Representation scene."""
from .skeleton import build_skeleton
from .meshes import build_meshes


def build_blender_scene(ir_scene, context, options):
    """Consumes an IRScene and creates Blender objects via bpy API.

    Args:
        ir_scene: IRScene dataclass hierarchy
        context: Blender context
        options: dict of importer options
    """
    for ir_model in ir_scene.models:
        armature = build_skeleton(ir_model, context, options)
        build_meshes(ir_model, armature, context, options)

    # TODO: build lights, cameras, fogs
