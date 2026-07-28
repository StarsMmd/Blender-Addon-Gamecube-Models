"""Execute a BR particle system as Blender objects. Pure bpy walker.

One Empty per system (parented to the armature) holding one single-vertex
mesh per emitter. The Empty is what keeps emitters out of the model: the
export describe phase collects geometry by ``obj.parent is armature``, so
hanging emitters off an intermediate parent leaves that sweep untouched.
Each emitter mesh carries a Geometry Nodes modifier whose
group exposes the emitter's parameters as interface inputs and its over-life
gradients as a ColorRamp / Float Curve — real, editable nodes that the
export leg reads back. Geometry passes straight through the group; the
preview simulation that will consume these inputs is not built yet.

Which emitter fires from which bone is animation data, not a property of
these objects: it lives on the pose bones' ``particle_emit`` fcurves, whose
values index ``dat_particle_emitter_index``.
"""
import bpy

from .linking import link_beside
from .materials import build_material, resolve_image

try:
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


# Plan names the Set Material node this; build hands it the emitter's material,
# which BR cannot carry as a node input (it is an ID pointer, not data).
_MATERIAL_NODE = 'ParticleMaterial'


def build_particles(br_particles, armature, context, logger=StubLogger()):
    """Create the emitter hierarchy for one model.

    In: br_particles (BRParticleSystem|None); armature (bpy.types.Object,
        parent of the system root); context (Blender context, unused —
        objects link into the scene collection); logger (Logger).
    Out: None. No-op when br_particles is None.
    """
    if br_particles is None:
        return

    image_cache = {}
    for br_image in br_particles.images:
        resolve_image(br_image, image_cache)

    root = _build_root(br_particles.root_name, armature)
    # Attach points first — every emitter's modifier references one by name.
    for br_attach in br_particles.attaches:
        _build_attach(br_attach, armature)
    for br_emitter in br_particles.emitters:
        _build_emitter(br_emitter, root, image_cache, armature)

    logger.info("  Built %d particle emitter(s), %d texture(s), %d attach point(s)",
                len(br_particles.emitters), len(br_particles.images),
                len(br_particles.attaches))


def _build_attach(br_attach, armature):
    """Create the bone-parented Empty an emitter spawns at.

    Blender anchors a bone-parented child at the bone's tail, so the Empty is
    pushed back along the bone to sit on its head — where the joint the game
    attaches to actually is.

    In: br_attach (BRParticleAttach); armature (bpy.types.Object).
    Out: bpy.types.Object.
    """
    bone = armature.data.bones.get(br_attach.bone_name)
    if bone is None:
        raise ValueError(
            "particle attach references missing bone %r (have: %s)"
            % (br_attach.bone_name, [b.name for b in armature.data.bones]))

    attach = bpy.data.objects.new(br_attach.name, None)
    attach.empty_display_type = 'SPHERE'
    attach.empty_display_size = 0.05
    link_beside(attach, armature)
    attach.parent = armature
    attach.parent_type = 'BONE'
    attach.parent_bone = br_attach.bone_name
    attach.location = (0.0, -bone.length, 0.0)
    return attach


def _build_root(name, armature):
    """Create the Empty every emitter parents to.

    In: name (str); armature (bpy.types.Object).
    Out: bpy.types.Object — an Empty at the armature origin, parented to it.
    """
    root = bpy.data.objects.new(name, None)
    root.empty_display_type = 'PLAIN_AXES'
    root.empty_display_size = 0.25
    link_beside(root, armature)
    root.parent = armature
    return root


def _build_emitter(br_emitter, root, image_cache, armature):
    """Create one emitter object: mesh + material + geometry-node modifier.

    In: br_emitter (BRParticleEmitter); root (bpy.types.Object, parent Empty);
        image_cache (dict, keyed by BRImage.cache_key); armature
        (bpy.types.Object, drives the emit gate).
    Out: bpy.types.Object.
    """
    mesh = bpy.data.meshes.new(br_emitter.name)
    mesh.from_pydata([(0.0, 0.0, 0.0)], [], [])
    mesh.update()

    emitter = bpy.data.objects.new(br_emitter.name, mesh)
    link_beside(emitter, root)
    emitter.parent = root

    material = None
    if br_emitter.material is not None:
        material = build_material(br_emitter.material, image_cache)
        mesh.materials.append(material)

    if br_emitter.node_group is not None:
        node_group = _build_node_group(br_emitter.node_group, material)
        modifier = emitter.modifiers.new(name="Particles", type='NODES')
        modifier.node_group = node_group
        _apply_modifier_inputs(modifier, node_group, br_emitter.node_group.inputs)
        if br_emitter.emit_driver is not None:
            _build_emit_driver(modifier, node_group, br_emitter.emit_driver, armature)

    for key, value in br_emitter.custom_props.items():
        emitter[key] = list(value) if isinstance(value, (list, tuple)) else value

    return emitter


# ---------------------------------------------------------------------------
# Node group
# ---------------------------------------------------------------------------


def _build_node_group(spec, material=None):
    """Create the emitter's GeometryNodeTree from its BR spec.

    In: spec (BRParticleNodeGroup); material (bpy.types.Material|None, shaded
        onto the instanced quads).
    Out: bpy.types.GeometryNodeTree.
    """
    tree = bpy.data.node_groups.new(spec.name, 'GeometryNodeTree')

    for socket in spec.inputs:
        _build_interface_socket(tree, socket, 'INPUT')
    for socket in spec.outputs:
        _build_interface_socket(tree, socket, 'OUTPUT')

    nodes = {}
    for br_node in spec.nodes:
        node = tree.nodes.new(type=br_node.node_type)
        node.name = br_node.name
        if br_node.location is not None:
            node.location = br_node.location
        # Properties precede defaults: several of these nodes switch their
        # socket types with a data_type property.
        for prop, value in br_node.properties.items():
            setattr(node, prop, value)
        for socket_key, value in br_node.input_defaults.items():
            _set_input_default(node, socket_key, value)
        nodes[br_node.name] = node

    # Zone sockets only exist once the pair is joined, so this precedes links.
    for input_name, output_name in spec.simulation_zones:
        _node(nodes, input_name).pair_with_output(_node(nodes, output_name))

    for node_name, ramp in spec.color_ramps.items():
        _apply_color_ramp(_node(nodes, node_name), ramp)
    for node_name, curve in spec.float_curves.items():
        _apply_float_curve(_node(nodes, node_name), curve)

    if material is not None and _MATERIAL_NODE in nodes:
        _socket(nodes[_MATERIAL_NODE].inputs, 'Material').default_value = material

    for link in spec.links:
        tree.links.new(
            _socket(_node(nodes, link.from_node).outputs, link.from_output),
            _socket(_node(nodes, link.to_node).inputs, link.to_input),
        )

    return tree


def _input_identifiers(tree):
    """Interface input sockets by name → Blender's assigned identifier.

    In: tree (bpy.types.GeometryNodeTree).
    Out: dict[str, str].
    """
    return {item.name: item.identifier for item in tree.interface.items_tree
            if item.item_type == 'SOCKET' and item.in_out == 'INPUT'}


def _set_input_default(node, socket_key, value):
    """Set one input socket's ``default_value``, addressed by identifier or name.

    In: node (bpy node); socket_key (str); value (object).
    Out: None.
    """
    socket = _socket(node.inputs, socket_key)
    if isinstance(value, (list, tuple)):
        socket.default_value[:] = list(value)
    else:
        socket.default_value = value


def _build_interface_socket(tree, spec, in_out):
    """Add one interface socket, then its limits and default.

    Limits are applied before the default because Blender clamps the default
    into the socket's range at assignment time.

    In: tree (bpy.types.GeometryNodeTree); spec (BRInterfaceSocket);
        in_out (str, 'INPUT' or 'OUTPUT').
    Out: the created interface socket.
    """
    socket = tree.interface.new_socket(
        name=spec.name, in_out=in_out, socket_type=spec.socket_type)

    if spec.description:
        socket.description = spec.description
    if spec.subtype is not None and hasattr(socket, 'subtype'):
        socket.subtype = spec.subtype
    if spec.min_value is not None and hasattr(socket, 'min_value'):
        socket.min_value = spec.min_value
    if spec.max_value is not None and hasattr(socket, 'max_value'):
        socket.max_value = spec.max_value
    if spec.value is not None and hasattr(socket, 'default_value'):
        socket.default_value = _bpy_value(spec.value, spec.socket_type)
    return socket


def _apply_modifier_inputs(modifier, tree, specs):
    """Write each emitter parameter onto the modifier.

    Modifier inputs are addressed by the interface socket's Blender-assigned
    identifier, so the group has to exist before this runs. The geometry
    socket is the modifier's input link, not a value — it is skipped.

    In: modifier (bpy.types.NodesModifier); tree (bpy.types.GeometryNodeTree);
        specs (list[BRInterfaceSocket]).
    Out: None.
    """
    identifiers = _input_identifiers(tree)

    for spec in specs:
        if spec.socket_type == 'NodeSocketGeometry' or spec.value is None:
            continue
        identifier = identifiers.get(spec.name)
        if identifier is None:
            raise ValueError(
                "no interface input %r on %s (have: %s)"
                % (spec.name, tree.name, sorted(identifiers)))
        modifier[identifier] = _bpy_value(spec.value, spec.socket_type)


def _build_emit_driver(modifier, tree, spec, armature):
    """Drive the group's Emit input from the firing bone's spawn keys.

    The emitter runs while any of that bone's ``particle_emit`` lanes holds
    its index. Those keys hold their value between spawns (they are events,
    not a sampled signal), so the emitter stays alive from the frame it fires
    until the bone fires something else — close to the game, where the
    generator instance outlives the event that created it.

    In: modifier (bpy.types.NodesModifier); tree (bpy.types.GeometryNodeTree);
        spec (BRParticleEmitDriver); armature (bpy.types.Object).
    Out: None.
    """
    identifier = _input_identifiers(tree).get('Emit')
    if identifier is None:
        raise ValueError("no Emit input on %s" % tree.name)

    fcurve = modifier.driver_add('["%s"]' % identifier)
    driver = fcurve.driver
    driver.type = 'SCRIPTED'
    for lane in range(spec.lane_count):
        variable = driver.variables.new()
        variable.name = 'lane%d' % lane
        variable.type = 'SINGLE_PROP'
        variable.targets[0].id = armature
        variable.targets[0].data_path = (
            'pose.bones["%s"]["particle_emit"][%d]' % (spec.bone_name, lane))
    driver.expression = '1.0 if (%s) else 0.0' % ' or '.join(
        'lane%d == %d' % (lane, spec.emitter_index)
        for lane in range(spec.lane_count))


def _apply_color_ramp(node, ramp):
    """Replace a ColorRamp node's elements with the planned stops.

    Elements are rebuilt from a single survivor rather than edited in place:
    the collection re-sorts on every position write, and the planned stops
    are already strictly increasing, so appending them in order is the one
    sequence that can't shuffle underneath us.

    In: node (bpy.types.ShaderNodeValToRGB); ramp (BRColorRamp, at least one
        stop).
    Out: None.
    """
    node.color_ramp.interpolation = ramp.interpolation
    node.color_ramp.color_mode = ramp.color_mode

    elements = node.color_ramp.elements
    while len(elements) > 1:
        elements.remove(elements[-1])

    elements[0].position = ramp.stops[0].position
    elements[0].color = ramp.stops[0].color
    for stop in ramp.stops[1:]:
        elements.new(stop.position).color = stop.color


def _apply_float_curve(node, curve):
    """Replace a Float Curve node's points with the planned ones.

    In: node (bpy.types.ShaderNodeFloatCurve); curve (BRFloatCurve, at least
        two points).
    Out: None.
    """
    mapping = node.mapping
    mapping.use_clip = curve.use_clip
    mapping.clip_min_y = curve.clip_min_y
    mapping.clip_max_y = curve.clip_max_y

    points = mapping.curves[0].points
    while len(points) > 2:
        points.remove(points[-1])

    for point, planned in zip(points, curve.points[:2]):
        point.location = (planned.x, planned.y)
    for planned in curve.points[2:]:
        points.new(planned.x, planned.y)

    mapping.update()


def _node(nodes, name):
    """Look up a node created for this group, loudly.

    In: nodes (dict[str, bpy node]); name (str).
    Out: bpy node. Raises ValueError when the name is unknown.
    """
    if name not in nodes:
        raise ValueError("no particle node %r (have: %s)" % (name, sorted(nodes)))
    return nodes[name]


def _socket(collection, key):
    """Resolve a socket by identifier, then by name.

    Group input/output sockets get their identifiers from Blender when the
    interface is created, so the plan addresses those by name; every other
    socket is addressed by identifier as elsewhere in BR.

    In: collection (bpy_prop_collection — node.inputs or node.outputs);
        key (str).
    Out: bpy socket. Raises ValueError when nothing matches.
    """
    for socket in collection:
        if socket.identifier == key:
            return socket
    for socket in collection:
        if socket.name == key:
            return socket
    raise ValueError(
        "no socket %r (have: %s)" % (key, [s.identifier for s in collection]))


def _bpy_value(value, socket_type=''):
    """Convert a BR socket value into what bpy expects.

    Object sockets hold an ID pointer, so BR carries the object's *name*
    (BR holds no bpy objects) and it resolves here. Sequences become lists;
    everything else passes through.

    In: value (object); socket_type (str, socket bl_idname).
    Out: object. Raises ValueError when a named object is missing.
    """
    if socket_type == 'NodeSocketObject':
        obj = bpy.data.objects.get(value)
        if obj is None:
            raise ValueError("particle attach object %r was not built" % (value,))
        return obj
    return list(value) if isinstance(value, (list, tuple)) else value
