"""Blender Representation (BR) — target-specialised dataclasses.

The BR is the Plan phase's output: a Blender-specific build plan derived from
the platform-agnostic IR. Each BR dataclass maps to a concrete Blender
concept (armature, bone, action, material node graph, etc.) with already-
decided per-target settings (inherit_scale mode, rotation_mode, edit-bone
matrices, etc.) so the build_blender phase can act as a thin bpy executor.
"""
