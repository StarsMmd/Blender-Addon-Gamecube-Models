# Blender API Usage Table

Every Blender Python API call used by this addon, with the Blender version range that supports it.

**Addon declared minimum:** `4.5.0` (in `blender_manifest.toml` and `bl_info`)
**Effective minimum (ignoring version guards):** 4.5.0

> **Note:** File references use refactored paths (`BlenderPlugin.py`, `importer/phases/build_blender/helpers/`, `importer/phases/post_process/`) and legacy paths (`legacy/` files like `ModelSet.py`, `MaterialObject.py`). Legacy files are only active when "Use Legacy Importer" is checked. Phase 5 (build_blender) and Phase 6 (post_process) only run when a Blender context is available (i.e., `context` is not `None`). The `shiny_filter.py` helper lives in `importer/phases/post_process/` (Phase 6), not in `build_blender/helpers/`.

| Min | Max | API Call | File(s) | Notes |
|-----|-----|----------|---------|-------|
| | | **Registration & Addon Metadata** | | |
| 2.80 | current | `bpy.utils.register_class(cls)` | `BlenderPlugin.py` | |
| 2.80 | current | `bpy.utils.unregister_class(cls)` | `BlenderPlugin.py` | |
| 2.80 | current | `bpy.types.TOPBAR_MT_file_import.append()` | `BlenderPlugin.py` | Was `INFO_MT_file_import` before 2.80 |
| 2.80 | current | `bpy.types.TOPBAR_MT_file_export.append()` | `BlenderPlugin.py` | |
| 2.80 | current | `bpy.types.TOPBAR_MT_file_import.remove()` | `BlenderPlugin.py` | |
| 2.80 | current | `bpy.types.TOPBAR_MT_file_export.remove()` | `BlenderPlugin.py` | |
| 2.80 | current | `bpy.types.Operator` (subclass) | `BlenderPlugin.py` | ImportHSD, ExportHSD |
| 2.80 | current | `bpy.types.Panel` (subclass) | `BlenderPlugin.py` | DAT_PT_ShinyPanel |
| 2.80 | current | `bpy.types.OperatorFileListElement` | `BlenderPlugin.py` | |
| | | | | |
| | | **Properties (bpy.props)** | | |
| 2.80 | current | `bpy.props.CollectionProperty` | `BlenderPlugin.py` | File list |
| 2.80 | current | `bpy.props.StringProperty` | `BlenderPlugin.py` | Section name, filter glob |
| 2.80 | current | `bpy.props.BoolProperty` | `BlenderPlugin.py` | Operator toggles + `dat_shiny` on Object |
| 2.80 | current | `bpy.props.IntProperty` | `BlenderPlugin.py` | Max frame |
| 2.80 | current | `bpy.props.FloatProperty` | `BlenderPlugin.py` | `dat_shiny_brightness_*` on Object |
| 2.80 | current | `bpy.props.EnumProperty` | `BlenderPlugin.py` | `dat_shiny_route_*` on Object |
| 2.80 | current | `setattr(bpy.types.Object, name, prop)` | `BlenderPlugin.py` | Register shiny properties on Object type |
| 2.80 | current | `delattr(bpy.types.Object, name)` | `BlenderPlugin.py` | Unregister shiny properties |
| 2.80 | current | Property `update` callback | `BlenderPlugin.py` | `_on_shiny_toggle_update`, `_on_shiny_param_update` |
| | | | | |
| | | **Custom Properties** | | |
| 2.80 | current | `object["key"] = value` | `shiny_filter.py` | `dat_has_shiny`, `dat_shiny_group` |
| 2.80 | current | `object.get("key", default)` | `shiny_filter.py`, `BlenderPlugin.py` | Panel poll, group name lookup |
| | | | | |
| | | **IO Helpers (bpy_extras)** | | |
| 2.80 | current | `bpy_extras.io_utils.ImportHelper` | `BlenderPlugin.py` | |
| 2.80 | current | `bpy_extras.io_utils.ExportHelper` | `BlenderPlugin.py` | |
| | | | | |
| | | **App & Version** | | |
| 2.80 | current | `bpy.app.version` | Multiple | Returns `(major, minor, patch)` tuple |
| | | | | |
| | | **Context & Scene** | | |
| 2.80 | current | `bpy.context.scene.collection.objects.link(obj)` | `meshes.py`, `skeleton.py`, `lights.py` | |
| 2.80 | current | `bpy.context.view_layer.objects.active = obj` | `skeleton.py` | |
| 2.80 | current | `bpy.context.scene.frame_end = n` | `BlenderPlugin.py` | Workspace setup |
| 2.80 | current | `context.screen.areas` | `BlenderPlugin.py` | Workspace setup |
| 3.2 | current | `context.temp_override(area=...)` | `BlenderPlugin.py` | Workspace split |
| | | | | |
| | | **Operators (bpy.ops)** | | |
| 2.80 | current | `bpy.ops.object.mode_set(mode=...)` | `skeleton.py` | EDIT/OBJECT mode switching |
| 2.80 | current | `bpy.ops.object.select_all(action='DESELECT')` | `BlenderPlugin.py` | |
| 2.80 | current | `bpy.ops.screen.area_split(direction, factor)` | `BlenderPlugin.py` | Workspace setup |
| | | | | |
| | | **Object Data Creation** | | |
| 2.80 | current | `bpy.data.armatures.new(name)` | `skeleton.py` | |
| 2.80 | current | `bpy.data.objects.new(name, object_data)` | `skeleton.py`, `meshes.py`, `lights.py` | |
| 2.80 | current | `bpy.data.meshes.new(name)` | `meshes.py` | |
| 2.80 | current | `bpy.data.materials.new(name)` | `materials.py`, `meshes.py` | |
| 2.80 | current | `bpy.data.lights.new(name, type)` | `lights.py` | |
| 2.80 | current | `bpy.data.images.new(name, w, h, alpha=True)` | `materials.py` | |
| 2.80 | current | `bpy.data.actions.new(name)` | `animations.py`, `material_animations.py` | |
| 2.80 | current | `bpy.data.node_groups.new(name, type)` | `shiny_filter.py` | ShinyFilter node group |
| 2.80 | current | `bpy.data.node_groups[name]` | `shiny_filter.py` | Lookup for rebuild |
| | | | | |
| | | **Object Properties** | | |
| 2.80 | current | `object.location = Vector(...)` | `meshes.py` | |
| 2.80 | current | `object.matrix_local = Matrix(...)` | `meshes.py` | |
| 2.80 | current | `object.parent = obj` | `meshes.py` | |
| 2.80 | current | `object.select_set(True)` | `skeleton.py` | |
| 2.80 | current | `object.hide_render = True` | `meshes.py` | |
| 2.80 | current | `object.hide_set(True)` | `meshes.py` | |
| 2.80 | current | `object.copy()` | `meshes.py` | Bone instances |
| 2.80 | current | `object.update_tag()` | `BlenderPlugin.py` | Shiny toggle viewport refresh |
| 2.80 | current | `object.children` | `BlenderPlugin.py` | Iterate child meshes for material tagging |
| | | | | |
| | | **Armature & Bones** | | |
| 2.80 | current | `armature_data.edit_bones.new(name)` | `skeleton.py` | Requires EDIT mode |
| 2.82 | current | `bone.inherit_scale = 'ALIGNED'` | `skeleton.py` | Was boolean before 2.82 |
| 2.80 | current | `bone.tail = Vector(...)` | `skeleton.py` | |
| 2.80 | current | `bone.matrix = Matrix(...)` | `skeleton.py` | Edit bone matrix |
| 2.80 | current | `bone.parent = edit_bone` | `skeleton.py` | |
| 2.80 | current | `armature_data.display_type = '...'` | `skeleton.py` | |
| | | | | |
| | | **Pose Bones** | | |
| 2.80 | current | `armature.pose.bones` | `skeleton.py`, `constraints.py` | |
| 2.80 | current | `pose_bone.rotation_mode = 'XYZ'` | `skeleton.py` | |
| | | | | |
| | | **Constraints** | | |
| 2.80 | current | `pose_bone.constraints.new(type=...)` | `constraints.py` | IK, COPY_LOCATION, TRACK_TO, COPY_ROTATION, LIMIT_* |
| 2.80 | current | `constraint.target = obj` | `constraints.py` | |
| 2.80 | current | `constraint.subtarget = name` | `constraints.py` | |
| 2.80 | current | `constraint.chain_count = n` | `constraints.py` | IK |
| 2.80 | current | `constraint.pole_target = obj` | `constraints.py` | IK |
| | | | | |
| | | **Mesh Data** | | |
| 2.80 | current | `mesh.from_pydata(verts, edges, faces)` | `meshes.py` | |
| 2.80 | current | `mesh.update(calc_edges=True)` | `meshes.py` | |
| 2.65 | current | `mesh.validate(verbose, clean_customdata)` | `meshes.py` | |
| 2.80 | current | `mesh.materials.append(mat)` | `meshes.py` | |
| 2.74 | current | `mesh.normals_split_custom_set(normals)` | `meshes.py` | |
| 2.80 | current | `mesh.uv_layers.new(name)` | `meshes.py` | |
| 3.2 | current | `mesh.color_attributes.new(name, type, domain)` | `meshes.py` | FLOAT_COLOR + CORNER; avoids sRGB auto-linearization |
| | | | | |
| | | **Vertex Groups** | | |
| 2.80 | current | `object.vertex_groups.new(name)` | `meshes.py` | |
| 2.80 | current | `vertex_group.add([indices], weight, 'REPLACE')` | `meshes.py` | |
| | | | | |
| | | **Modifiers** | | |
| 2.80 | current | `object.modifiers.new(name, 'ARMATURE')` | `meshes.py` | |
| | | | | |
| | | **Material & Shader Nodes** | | |
| 2.80 | current | `material.use_nodes = True` | `materials.py` | |
| 2.80 | current | `material.node_tree.nodes` / `.links` | `materials.py`, `shiny_filter.py` | |
| 2.80 | current | `material.node_tree.update_tag()` | `BlenderPlugin.py` | Force material refresh |
| 2.80 | current | `nodes.new('ShaderNodeOutputMaterial')` | `materials.py` | |
| 2.79 | current | `nodes.new('ShaderNodeBsdfPrincipled')` | `materials.py` | |
| 2.80 | current | `nodes.new('ShaderNodeRGB')` | `materials.py`, `shiny_filter.py` | |
| 2.80 | current | `nodes.new('ShaderNodeValue')` | `materials.py`, `shiny_filter.py` | |
| 2.80 | current | `nodes.new('ShaderNodeMixRGB')` | `materials.py`, `shiny_filter.py` | Deprecated 3.4; still functional |
| 2.80 | current | `nodes.new('ShaderNodeMath')` | `materials.py`, `shiny_filter.py` | MULTIPLY operation |
| 2.80 | current | `nodes.new('ShaderNodeAttribute')` | `materials.py` | Vertex colors |
| 2.80 | current | `nodes.new('ShaderNodeTexImage')` | `materials.py` | |
| 2.80 | current | `nodes.new('ShaderNodeEmission')` | `materials.py` | Unlit materials |
| 2.80 | current | `nodes.new('ShaderNodeMixShader')` | `materials.py` | |
| 2.80 | current | `nodes.new('ShaderNodeBsdfTransparent')` | `materials.py` | |
| 2.80 | current | `nodes.new('ShaderNodeAddShader')` | `materials.py` | |
| 2.80 | current | `nodes.new('ShaderNodeBump')` | `materials.py` | |
| 3.3 | current | `nodes.new('ShaderNodeSeparateColor')` | `shiny_filter.py` | Shiny channel routing |
| 3.3 | current | `nodes.new('ShaderNodeCombineColor')` | `shiny_filter.py` | Shiny channel recombination |
| 2.80 | current | `nodes.new('ShaderNodeGroup')` | `shiny_filter.py` | ShinyFilter group instance |
| 2.80 | current | `nodes.new('NodeGroupInput')` / `('NodeGroupOutput')` | `shiny_filter.py` | Inside node group |
| 2.80 | current | `nodes.remove(node)` | `materials.py` | |
| 2.80 | current | `nodes.clear()` | `shiny_filter.py` | Clear group for rebuild |
| 2.80 | current | `links.new(output, input)` | `materials.py`, `shiny_filter.py` | |
| 2.80 | current | `links.remove(link)` | `shiny_filter.py` | Interpose shiny filter |
| 2.80 | current | `mix_node.blend_type = '...'` | `materials.py`, `shiny_filter.py` | |
| 2.80 | current | `tex_node.extension = '...'` | `materials.py` | |
| 2.80 | current | `tex_node.interpolation = '...'` | `materials.py` | |
| 4.0 | current | `shader.inputs["Specular IOR Level"]` | `materials.py` | Guarded by version check |
| 4.0 | current | `shader.inputs["Specular Tint"]` → RGBA tuple | `materials.py` | Guarded by version check |
| | | | | |
| | | **Node Group Interface** | | |
| 4.0 | current | `group.interface.new_socket(name, in_out, socket_type)` | `shiny_filter.py` | Node group I/O sockets |
| 4.0 | current | `group.interface.items_tree` | `shiny_filter.py` | Check/remove Alpha socket |
| 4.0 | current | `group.interface.remove(item)` | `shiny_filter.py` | Remove Alpha socket on rebuild |
| | | | | |
| | | **Drivers** | | |
| 2.80 | current | `socket.driver_add("default_value")` | `shiny_filter.py` | Drive MixRGB factor from `dat_shiny` |
| 2.80 | current | `driver.type = 'AVERAGE'` | `shiny_filter.py` | |
| 2.80 | current | `driver.variables.new()` | `shiny_filter.py` | |
| 2.80 | current | `var.type = 'SINGLE_PROP'` | `shiny_filter.py` | |
| 2.80 | current | `target.id_type = 'OBJECT'` | `shiny_filter.py` | |
| 2.80 | current | `target.data_path = 'dat_shiny'` | `shiny_filter.py` | Registered property path |
| | | | | |
| | | **Animation Data** | | |
| 2.80 | current | `object.animation_data_create()` | `animations.py`, `material_animations.py` | |
| 2.80 | current | `object.animation_data.action = action` | `animations.py`, `material_animations.py` | |
| 4.5 | current | `action.slots.new(type, name)` | `animations.py`, `material_animations.py` | Guarded: `>= (4, 5, 0)` |
| 4.5 | current | `action.slots.active = slot` | `animations.py`, `material_animations.py` | Guarded: `>= (4, 5, 0)` |
| 4.4 | current | `animation_data.action_slot = slot` | `animations.py`, `material_animations.py` | Guarded: `>= (4, 4, 0)` |
| 2.80 | current | `action.use_fake_user = True` | `animations.py`, `material_animations.py` | |
| | | | | |
| | | **F-Curves & Keyframes** | | |
| 2.80 | current | `action.fcurves.new(data_path, index=n)` | `animations.py`, `material_animations.py` | |
| 2.80 | current | `curve.keyframe_points.insert(frame, value)` | `animations.py`, `material_animations.py` | |
| 2.80 | current | `keyframe.interpolation = '...'` | `animations.py` | BEZIER, LINEAR, CONSTANT |
| 2.80 | current | `keyframe.handle_left = (x, y)` | `animations.py` | Bezier handles |
| 2.80 | current | `keyframe.handle_right = (x, y)` | `animations.py` | |
| 2.80 | current | `curve.modifiers.new('CYCLES')` | `animations.py`, `material_animations.py` | Looping animations |
| | | | | |
| | | **NLA** | | |
| 2.80 | current | `material.animation_data.nla_tracks.new()` | `material_animations.py` | |
| 2.80 | current | `track.strips.new(name, start, action)` | `material_animations.py` | |
| | | | | |
| | | **Light Data** | | |
| 2.80 | current | `light_data.color = [r, g, b]` | `lights.py` | |
| | | | | |
| | | **Image Data** | | |
| 2.80 | current | `image.pixels = [...]` | `materials.py` | Flat RGBA float list |
| 2.80 | current | `image.alpha_mode = 'CHANNEL_PACKED'` | `materials.py` | |
| 2.80 | current | `image.pack()` | `materials.py` | |
| | | | | |
| | | **mathutils** | | |
| 2.80 | current | `Vector((...))` | `skeleton.py`, `meshes.py`, `lights.py`, `animations.py` | |
| 2.80 | current | `Matrix(list)` | `skeleton.py`, `meshes.py`, `constraints.py` | Construct from nested list |
| 2.80 | current | `Matrix.Translation(vec)` | `skeleton.py` | |
| 2.80 | current | `Matrix.Rotation(angle, size, axis)` | `skeleton.py` | |
| 2.80 | current | `matrix.inverted()` | `animations.py` | |
| 2.80 | current | `matrix.decompose()` | `animations.py` | Returns `(trans, rot, scale)` |
| | | | | |
| | | **Third-Party Libraries** | | |
| — | — | `numpy.frombuffer(bytes, dtype=np.uint8)` | `materials.py` | Image pixel conversion; bundled with Blender |
| — | — | `ndarray.astype(np.float32) / 255.0` | `materials.py` | u8 → float32 normalization |

## Version-Guarded Code Paths

The addon uses `BlenderVersion` checks to handle API differences across versions:

| Guard | Feature | File |
|-------|---------|------|
| `>= (4, 5, 0)` | Action slots (`action.slots.new()`, `.active`, `.action_slot`) | `animations.py`, `material_animations.py` |
| `>= (4, 4, 0)` | `animation_data.action_slot` assignment | `animations.py` |
| `>= (4, 0, 0)` | Specular input renamed to `"Specular IOR Level"` | `materials.py` |
| `>= (4, 0, 0)` | `"Specular Tint"` changed from float to RGBA | `materials.py` |

## Deprecated APIs Still In Use

| API | Status | Replacement | Impact |
|-----|--------|-------------|--------|
| `ShaderNodeMixRGB` | Deprecated 3.4 | `ShaderNodeMix` | Still functional; used for TEV blending and shiny filter mix |
| `mesh.vertex_colors` | Deprecated 3.2 | `mesh.color_attributes` (FLOAT_COLOR) | Migrated to FLOAT_COLOR to avoid sRGB auto-linearization |
| `mesh.normals_split_custom_set()` | Workflow changed 4.1 | Auto Smooth modifier | Still callable |
