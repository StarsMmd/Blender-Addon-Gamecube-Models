"""Phase 6 (collision): BRCollisionScene → Blender objects.

Pure executor. Naming, colours, custom-property keys and face-attribute names
are all decided in plan_collision; this layer only calls bpy.
"""
import bpy
from mathutils import Matrix

from .helpers.linking import make_collection, link_into

try:
    from ....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def build_collision(br_collision, context, logger=StubLogger()):
    """Build the collision overlay for one .ccd.

    In: br_collision (BRCollisionScene); context (Blender context); logger.
    Out: the root Empty the overlay hangs from.
    """
    logger.info("=== Phase 6: Build Collision ===")

    materials = [_build_material(br_material)
                 for br_material in br_collision.materials]

    root_collection = make_collection(br_collision.collection_name)
    subcollections = {name: make_collection(name, root_collection)
                      for name in br_collision.subcollections}

    root = _build_empty(br_collision.root_name, br_collision.root_matrix, {},
                        root_collection)

    for marker in br_collision.markers:
        empty = _build_empty(marker.name, marker.matrix_basis,
                             marker.custom_props, root_collection)
        empty.parent = root

    for br_object in br_collision.objects:
        collection = subcollections.get(br_object.collection_name)
        if collection is None:
            raise ValueError(
                "Collision object '%s' wants collection '%s', which the plan "
                "did not declare — available: %s"
                % (br_object.name, br_object.collection_name,
                   ", ".join(subcollections) or "none")
            )
        obj = _build_object(br_object, materials, collection)
        obj.parent = root

    # Flush the parenting so world matrices read correctly straight away —
    # nothing else runs after the collision path to trigger an evaluation.
    if context is not None:
        context.view_layer.update()

    logger.info("  Built %d collision object(s) + %d entry marker(s) under '%s'",
                len(br_collision.objects), len(br_collision.markers), root.name)
    return root


def _build_object(br_object, materials, collection):
    """Create one collision mesh object with its attributes and properties."""
    mesh = bpy.data.meshes.new(br_object.name)
    mesh.from_pydata(br_object.vertices, [], br_object.faces)
    if mesh.validate():
        raise ValueError(
            "Blender rejected part of collision mesh '%s' (%d vertices, "
            "%d faces) — its per-face metadata can no longer be attached"
            % (br_object.name, len(br_object.vertices), len(br_object.faces))
        )
    mesh.update()

    for name, values in br_object.face_attributes.items():
        attribute = mesh.attributes.new(name=name, type='INT', domain='FACE')
        attribute.data.foreach_set('value', values)

    if br_object.material_index is not None:
        mesh.materials.append(materials[br_object.material_index])

    obj = bpy.data.objects.new(br_object.name, mesh)
    for key, value in br_object.custom_props.items():
        obj[key] = value
    if br_object.matrix_basis is not None:
        obj.matrix_basis = Matrix(br_object.matrix_basis)

    link_into(obj, collection)
    return obj


def _build_empty(name, matrix_basis, custom_props, collection):
    """Create a plain-axes Empty carrying the given properties."""
    empty = bpy.data.objects.new(name, None)
    empty.empty_display_type = 'PLAIN_AXES'
    for key, value in custom_props.items():
        empty[key] = value
    if matrix_basis is not None:
        empty.matrix_basis = Matrix(matrix_basis)
    link_into(empty, collection)
    return empty


def _build_material(br_material):
    """Create (or refresh) the shared translucent material for one subsystem."""
    material = bpy.data.materials.get(br_material.name)
    if material is None:
        material = bpy.data.materials.new(br_material.name)
    material.use_nodes = True

    principled = next((node for node in material.node_tree.nodes
                       if node.type == 'BSDF_PRINCIPLED'), None)
    if principled is None:
        raise ValueError(
            "Collision material '%s' has no Principled BSDF node — found: %s"
            % (br_material.name,
               ", ".join(node.type for node in material.node_tree.nodes) or "none")
        )

    red, green, blue, alpha = br_material.color
    principled.inputs['Base Color'].default_value = (red, green, blue, 1.0)
    principled.inputs['Alpha'].default_value = alpha
    material.blend_method = br_material.blend_method
    material.surface_render_method = br_material.surface_render_method
    material.diffuse_color = (red, green, blue, alpha)
    return material
