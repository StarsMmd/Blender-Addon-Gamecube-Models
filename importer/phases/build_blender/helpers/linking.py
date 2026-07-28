"""Where newly built objects get linked.

An import files its objects into its own collection so the whole thing can be
hidden, soloed or deleted as a unit — object parenting carries the transform,
but only collections hide their contents. Anything parented to an armature
follows that armature's collection rather than threading the target through
every builder.
"""
import bpy


def make_collection(name, parent=None):
    """Create a collection and nest it under parent, or under the scene root.

    In: name (str); parent (bpy.types.Collection|None).
    Out: bpy.types.Collection.
    """
    collection = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(collection)
    return collection


def link_into(obj, collection):
    """Link an object into a collection, or the scene root when there is none.

    In: obj (bpy.types.Object, not yet linked); collection
        (bpy.types.Collection|None).
    Out: None.
    """
    (collection or bpy.context.scene.collection).objects.link(obj)


def link_beside(obj, sibling):
    """Link an object into the collection its sibling already lives in.

    Used for everything that hangs off an armature (meshes, spline paths,
    particle emitters) so it lands wherever that armature was filed.

    In: obj (bpy.types.Object, not yet linked); sibling (bpy.types.Object).
    Out: None. Falls back to the scene root when the sibling is itself unlinked.
    """
    collections = getattr(sibling, 'users_collection', None) if sibling else None
    link_into(obj, collections[0] if collections else None)
