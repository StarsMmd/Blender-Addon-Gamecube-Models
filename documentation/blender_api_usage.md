# Blender API Usage Table

Every Blender Python API call used by this addon, with the Blender version range that supports it.

**Addon declared minimum:** `(4, 5, 0)` (in `bl_info`)
**Effective minimum (ignoring version guards):** 4.5.0

| Min | Max | API Call | File(s) | Notes |
|-----|-----|----------|---------|-------|
| | | **Registration & Addon Metadata** | | |
| 2.80 | current | `bpy.utils.register_class(cls)` | `__init__.py:162` | |
| 2.80 | current | `bpy.utils.unregister_class(cls)` | `__init__.py:170` | |
| 2.80 | current | `bpy.types.TOPBAR_MT_file_import.append()` | `__init__.py:164` | Was `INFO_MT_file_import` before 2.80 |
| 2.80 | current | `bpy.types.TOPBAR_MT_file_export.append()` | `__init__.py:165` | Was `INFO_MT_file_export` before 2.80 |
| 2.80 | current | `bpy.types.TOPBAR_MT_file_import.remove()` | `__init__.py:172` | |
| 2.80 | current | `bpy.types.TOPBAR_MT_file_export.remove()` | `__init__.py:173` | |
| 2.80 | current | `bpy.types.Operator` (subclass) | `__init__.py:45,86` | |
| 2.80 | current | `bpy.types.OperatorFileListElement` | `__init__.py:54` | |
| 2.80 | current | `bl_info` dict | `__init__.py:5` | |
| | | | | |
| | | **Properties (bpy.props)** | | |
| 2.80 | current | `bpy.props.CollectionProperty` | `__init__.py:51` | |
| 2.80 | current | `bpy.props.StringProperty` | `__init__.py:55,63` | |
| 2.80 | current | `bpy.props.BoolProperty` | `__init__.py:57,59,60` | |
| 2.80 | current | `bpy.props.IntProperty` | `__init__.py:58` | |
| 2.80 | current | `bpy.props.EnumProperty` | `__init__.py:22` | Imported but unused |
| 2.80 | current | `bpy.props.FloatProperty` | `__init__.py:22` | Imported but unused |
| | | | | |
| | | **IO Helpers (bpy_extras)** | | |
| 2.80 | current | `bpy_extras.io_utils.ImportHelper` | `__init__.py:30,45` | |
| 2.80 | current | `bpy_extras.io_utils.ExportHelper` | `__init__.py:30,86` | |
| 2.80 | current | `bpy_extras.io_utils.axis_conversion` | `__init__.py:30` | Imported but unused |
| | | | | |
| | | **App & Version** | | |
| 2.80 | current | `bpy.app.version` | Multiple | Returns `(major, minor, patch)` tuple |
| | | | | |
| | | **Context & Scene** | | |
| 2.80 | current | `bpy.context.scene.collection.objects.link(obj)` | `ModelSet.py:139`, `Mesh.py:64`, `PObject.py:193`, `Light.py:110,117`, `Spline.py:154` | Was `bpy.context.scene.objects.link()` before 2.80 |
| 2.80 | current | `bpy.context.view_layer.objects.active = obj` | `ModelSet.py:57,91,147,163,262,281`, `Mesh.py:64`, `Light.py` (via matrix) | Was `bpy.context.scene.objects.active` before 2.80 |
| 2.80 | current | `bpy.context.view_layer.update()` | `ModelSet.py:173` | |
| 2.80 | current | `bpy.context.scene.frame_set(n)` | `ModelSet.py:103` | |
| 2.80 | current | `bpy.context.scene.frame_end = n` | `__init__.py:104` | |
| 2.80 | current | `context.screen.areas` | `__init__.py:109` | |
| 3.2 | current | `context.temp_override(area=...)` | `__init__.py:118,137` | Introduced in 3.2; used for workspace setup |
| | | | | |
| | | **Operators (bpy.ops)** | | |
| 2.80 | current | `bpy.ops.object.mode_set(mode=...)` | `ModelSet.py:58,88,92,98,152,164,174,263,274,282,295`, `Joint.py:67`, `Mesh.py:70,96` | |
| 2.80 | current | `bpy.ops.object.select_all(action='DESELECT')` | `importer.py:47` | |
| 2.80 | current | `bpy.ops.object.select_all.poll()` | `importer.py:46` | |
| 2.80 | current | `bpy.ops.screen.area_split(direction, factor)` | `__init__.py:119,138` | |
| | | | | |
| | | **Object Data Creation** | | |
| 2.80 | current | `bpy.data.armatures.new(name)` | `ModelSet.py:129` | |
| 2.80 | current | `bpy.data.objects.new(name, object_data)` | `ModelSet.py:130`, `PObject.py:190`, `Light.py:100,107`, `Spline.py:153` | |
| 2.80 | current | `bpy.data.meshes.new(name)` | `PObject.py:189` | |
| 2.80 | current | `bpy.data.materials.new(name)` | `MaterialObject.py:29` | |
| 2.80 | current | `bpy.data.lights.new(name, type)` | `Light.py:86,88,90` | Was `bpy.data.lamps` before 2.80 |
| 2.80 | current | `bpy.data.curves.new(name, type='CURVE')` | `Spline.py:128` | |
| 2.80 | current | `bpy.data.images.new(name, w, h, alpha=True)` | `Image.py:132` | |
| 2.80 | current | `bpy.data.actions.new(name)` | `ModelSet.py:49`, `MaterialAnimation.py:98` | |
| 2.80 | current | `bpy.data.actions.remove(action)` | `MaterialAnimation.py:77` | |
| | | | | |
| | | **Object Properties** | | |
| 2.80 | current | `object.location = Vector(...)` | `PObject.py:191` | |
| 2.80 | current | `object.matrix_basis = Matrix(...)` | `ModelSet.py:135`, `Light.py:103,109,120` | |
| 2.80 | current | `object.matrix_basis @= Matrix(...)` | `ModelSet.py:180`, `Light.py:120` | In-place matrix multiply |
| 2.80 | current | `object.matrix_local = Matrix(...)` | `ModelSet.py:211`, `Mesh.py:143` | |
| 2.80 | current | `object.matrix_global = Matrix(...)` | `Mesh.py:131` | |
| 2.80 | current | `object.parent = obj` | `ModelSet.py:210`, `Mesh.py:44` | |
| 2.80 | current | `object.select_set(True)` | `ModelSet.py:141` | Was `object.select = True` before 2.80 |
| 2.80 | current | `object.hide_render = True` | `Mesh.py:41` | |
| 2.80 | current | `object.hide_set(True)` | `Mesh.py:42` | Was `object.hide = True` before 2.80 |
| 2.80 | current | `object.copy()` | `ModelSet.py:209` | Shallow copy of object |
| 2.80 | current | `object.empty_display_type = '...'` | `Light.py:108` | Was `empty_draw_type` before 2.80 |
| | | | | |
| | | **Armature & Bones** | | |
| 2.80 | current | `armature_data.edit_bones.new(name)` | `Joint.py:71` | Requires EDIT mode |
| 2.80 | current | `armature_data.edit_bones[name]` | `ModelSet.py:271,272,273,291,292,293` | |
| 2.82 | current | `bone.inherit_scale = 'ALIGNED'` | `Joint.py:97` | Was boolean `use_inherit_scale` before 2.82 |
| 2.80 | current | `bone.tail = Vector(...)` | `Joint.py:76,78` | |
| 2.80 | current | `bone.matrix = Matrix(...)` | `Joint.py:96` | Edit bone matrix |
| 2.80 | current | `bone.head = Vector(...)` | `ModelSet.py:272,292` | Edit bone head |
| 2.80 | current | `bone.parent = edit_bone` | `Joint.py:94` | |
| 2.80 | current | `armature_data.display_type = '...'` | `ModelSet.py:145` | Was `draw_type` before 2.80 |
| 2.80 | current | `armature_data.bones[name]` | `ModelSet.py:259,277` | |
| 2.80 | current | `bone.matrix_local` | `ModelSet.py:260,264,265,284,285` | Read-only in non-edit mode |
| 2.80 | current | `bone.use_local_location = True` | `ModelSet.py:62` | |
| | | | | |
| | | **Pose Bones** | | |
| 2.80 | current | `armature.pose.bones` | `ModelSet.py:59,93,165` | Requires POSE mode context |
| 2.80 | current | `pose_bone.rotation_mode = 'XYZ'` | `ModelSet.py:60` | |
| 2.80 | current | `pose_bone.location = (...)` | `ModelSet.py:94` | |
| 2.80 | current | `pose_bone.rotation_euler = (...)` | `ModelSet.py:95` | |
| 2.80 | current | `pose_bone.rotation_quaternion = (...)` | `ModelSet.py:96` | |
| 2.80 | current | `pose_bone.scale = (...)` | `ModelSet.py:97` | |
| | | | | |
| | | **Constraints** | | |
| 2.80 | current | `pose_bone.constraints.new(type='IK')` | `ModelSet.py:298` | |
| 2.80 | current | `pose_bone.constraints.new(type='COPY_LOCATION')` | `ModelSet.py:360` | |
| 2.80 | current | `pose_bone.constraints.new(type='TRACK_TO')` | `ModelSet.py:366`, `Light.py:112` | |
| 2.80 | current | `pose_bone.constraints.new(type='COPY_ROTATION')` | `ModelSet.py:373` | |
| 2.80 | current | `pose_bone.constraints.new(type='LIMIT_LOCATION')` | `ModelSet.py:387` | |
| 2.80 | current | `pose_bone.constraints.new(type='LIMIT_ROTATION')` | `ModelSet.py:387` | |
| 2.80 | current | `constraint.target = obj` | `ModelSet.py:301,363,368,374`, `Light.py:113` | |
| 2.80 | current | `constraint.subtarget = name` | `ModelSet.py:302,363,368,375` | |
| 2.80 | current | `constraint.chain_count = n` | `ModelSet.py:299` | IK constraint |
| 2.80 | current | `constraint.pole_target = obj` | `ModelSet.py:304` | IK constraint |
| 2.80 | current | `constraint.pole_subtarget = name` | `ModelSet.py:305` | IK constraint |
| 2.80 | current | `constraint.pole_angle = float` | `ModelSet.py:306` | IK constraint |
| 2.80 | current | `constraint.influence = float` | `ModelSet.py:361` | |
| 2.80 | current | `constraint.track_axis = '...'` | `ModelSet.py:369`, `Light.py:114` | |
| 2.80 | current | `constraint.up_axis = '...'` | `ModelSet.py:370`, `Light.py:115` | |
| 2.80 | current | `constraint.owner_space = '...'` | `ModelSet.py:377,388` | |
| 2.80 | current | `constraint.target_space = '...'` | `ModelSet.py:378` | |
| 2.80 | current | `constraint.use_min_x` / `min_x` / etc. | `ModelSet.py:393-402` | Limit constraint axes |
| | | | | |
| | | **Mesh Data** | | |
| 2.80 | current | `mesh.from_pydata(verts, edges, faces)` | `PObject.py:197` | |
| 2.80 | current | `mesh.update(calc_edges=True)` | `PObject.py:278` | |
| 2.65 | current | `mesh.validate(verbose, clean_customdata)` | `Mesh.py:55` | |
| 2.80 | current | `mesh.data.vertices[i].co = Vector(...)` | `Mesh.py:100` | |
| 2.80 | current | `mesh.data.polygons` | `PObject.py:481,513,531` | |
| 2.80 | current | `polygon.loop_indices` | `PObject.py:483,515,533` | |
| 2.80 | current | `mesh.data.loops` | `Mesh.py:117,137` | |
| 2.80 | current | `mesh.data.materials.append(mat)` | `Mesh.py:36` | |
| 2.74 | current | `mesh.data.normals_split_custom_set(normals)` | `Mesh.py:119,140,148` | Workflow changed in 4.1 |
| 2.80 | 4.0 | `mesh.use_auto_smooth = True` | `PObject.py:235` | Removed in 4.1; guarded by version check |
| 2.80 | current | `mesh.uv_layers.new()` | `PObject.py:528` | |
| 2.80 | current | `mesh.uv_layers[name]` | `PObject.py:530` | |
| 2.80 | current | `uv_layer.data[i].uv = [u, v]` | `PObject.py:539` | |
| 2.80 | current | `mesh.vertex_colors.new(name)` | `PObject.py:268,272,511,512` | Deprecated in 3.2 in favor of color attributes; still functional |
| 2.80 | current | `mesh.vertex_colors[name]` | `PObject.py:255,267,271` | |
| 2.80 | current | `vertex_color.data[i].color = [r,g,b,a]` | `PObject.py:269,270,273,524,525` | |
| | | | | |
| | | **Vertex Groups** | | |
| 2.80 | current | `object.vertex_groups.new(name)` | `Mesh.py:80,89,125,128,145` | |
| 2.80 | current | `vertex_group.add([indices], weight, 'REPLACE')` | `Mesh.py:102,133,134,146` | |
| | | | | |
| | | **Modifiers** | | |
| 2.80 | current | `object.modifiers.new(name, 'ARMATURE')` | `Mesh.py:151` | |
| 2.80 | current | `modifier.object = armature` | `Mesh.py:152` | |
| 2.80 | current | `modifier.use_bone_envelopes = False` | `Mesh.py:153` | |
| 2.80 | current | `modifier.use_vertex_groups = True` | `Mesh.py:154` | |
| | | | | |
| | | **Shape Keys** | | |
| 2.80 | current | `object.shape_key_add(from_mix=False)` | `PObject.py:471` | |
| 2.80 | current | `shapekey.data[i].co = value` | `PObject.py:476` | |
| | | | | |
| | | **Material & Shader Nodes** | | |
| 2.80 | current | `material.use_nodes = True` | `MaterialObject.py:30` | |
| 2.80 | current | `material.node_tree.nodes` | `MaterialObject.py:31` | |
| 2.80 | current | `material.node_tree.links` | `MaterialObject.py:32` | |
| 2.80 | current | `material.blend_method = '...'` | `MaterialObject.py:409,445,450,505,558,571` | Values: `'HASHED'`, `'BLEND'` |
| 2.80 | current | `nodes.new('ShaderNodeOutputMaterial')` | `MaterialObject.py:36` | |
| 2.79 | current | `nodes.new('ShaderNodeBsdfPrincipled')` | `MaterialObject.py:508` | Introduced in 2.79 |
| 2.80 | current | `nodes.new('ShaderNodeRGB')` | `MaterialObject.py:80,104,113,371,465,472,602-630` | |
| 2.80 | current | `nodes.new('ShaderNodeValue')` | `MaterialObject.py:91,128,137,410,488,638` | |
| 2.80 | current | `nodes.new('ShaderNodeMixRGB')` | `MaterialObject.py:116,140,253,269,294,319,381,420,432,671-768` | Deprecated in 3.4; replaced by `ShaderNodeMix`. Still functional in current versions |
| 2.80 | current | `nodes.new('ShaderNodeMath')` | `MaterialObject.py:140,451,703-800` | |
| 2.80 | current | `nodes.new('ShaderNodeAttribute')` | `MaterialObject.py:110,134,317,328` | |
| 2.80 | current | `nodes.new('ShaderNodeUVMap')` | `MaterialObject.py:163` | |
| 2.80 | current | `nodes.new('ShaderNodeTexCoord')` | `MaterialObject.py:169` | |
| 2.81 | current | `nodes.new('ShaderNodeMapping')` | `MaterialObject.py:177` | Input layout changed in 2.81 (Location/Rotation/Scale as sub-inputs) |
| 2.80 | current | `nodes.new('ShaderNodeTexImage')` | `MaterialObject.py:193` | |
| 2.80 | current | `nodes.new('ShaderNodeVectorMath')` | `MaterialObject.py:219` | |
| 2.80 | current | `nodes.new('ShaderNodeEmission')` | `MaterialObject.py:532,560` | |
| 2.80 | current | `nodes.new('ShaderNodeMixShader')` | `MaterialObject.py:537` | |
| 2.80 | current | `nodes.new('ShaderNodeBsdfTransparent')` | `MaterialObject.py:538,563,573` | |
| 2.80 | current | `nodes.new('ShaderNodeAddShader')` | `MaterialObject.py:544,564` | |
| 2.80 | current | `nodes.new('ShaderNodeBump')` | `MaterialObject.py:551` | |
| 2.80 | current | `nodes.new('ShaderNodeInvert')` | `MaterialObject.py:480` | |
| 2.81 | current | `nodes.new('ShaderNodeSeparateXYZ')` | `MaterialObject.py:815` | In `_make_per_axis_wrap` (currently unused) |
| 2.81 | current | `nodes.new('ShaderNodeCombineXYZ')` | `MaterialObject.py:838` | In `_make_per_axis_wrap` (currently unused) |
| 2.81 | current | `nodes.new('ShaderNodeClamp')` | `MaterialObject.py:823,831` | Introduced in 2.81; in `_make_per_axis_wrap` (currently unused) |
| 2.80 | current | `nodes.remove(node)` | `MaterialObject.py:35` | |
| 2.80 | current | `links.new(output, input)` | `MaterialObject.py` (50+ uses) | |
| 2.80 | current | `node.outputs[n].default_value` | `MaterialObject.py` (30+ uses) | |
| 2.80 | current | `node.inputs[n].default_value` | `MaterialObject.py` (30+ uses) | |
| 2.80 | current | `node.name = '...'` | `MaterialObject.py` (multiple) | |
| 2.80 | current | `mix_node.blend_type = '...'` | `MaterialObject.py` (multiple) | `'MIX'`, `'ADD'`, `'SUBTRACT'`, `'MULTIPLY'` |
| 2.80 | current | `mix_node.use_clamp = True` | `MaterialObject.py:454,685,695,715,722` | |
| 2.80 | current | `tex_node.image = image` | `MaterialObject.py:194` | |
| 2.80 | current | `tex_node.extension = '...'` | `MaterialObject.py:207,210` | `'REPEAT'`, `'EXTEND'` |
| 2.80 | current | `tex_node.interpolation = '...'` | `MaterialObject.py:213` | `'Closest'`, `'Linear'`, `'Cubic'` |
| 2.80 | current | `uv_node.uv_map = '...'` | `MaterialObject.py:164` | |
| 2.80 | current | `attribute_node.attribute_name = '...'` | `MaterialObject.py:111,135,318,329` | |
| 2.81 | current | `mapping_node.vector_type = '...'` | `MaterialObject.py:179` | |
| 2.81 | current | `mapping_node.inputs[1].default_value` (Location) | `MaterialObject.py:183,187` | Input indexing changed in 2.81 |
| 2.81 | current | `mapping_node.inputs[2].default_value` (Rotation) | `MaterialObject.py:180,191` | |
| 2.81 | current | `mapping_node.inputs[3].default_value` (Scale) | `MaterialObject.py:184` | |
| 4.0 | current | `shader.inputs["Specular IOR Level"]` | `MaterialObject.py:510,512` | Renamed from `"Specular"` in 4.0; guarded by version check |
| 2.79 | 3.6 | `shader.inputs["Specular"]` | `MaterialObject.py:510,514` | Old name; guarded by version check |
| 4.0 | current | `shader.inputs["Specular Tint"]` → RGBA tuple | `MaterialObject.py:517` | Changed from float to RGBA in 4.0; guarded |
| 2.79 | 3.6 | `shader.inputs["Specular Tint"]` → float | `MaterialObject.py:519` | Old type; guarded by version check |
| 2.80 | current | `shader.inputs['Roughness']` | `MaterialObject.py:521` | |
| 2.80 | current | `shader.inputs['Base Color']` | `MaterialObject.py:525` | |
| 2.80 | current | `shader.inputs['Alpha']` | `MaterialObject.py:528` | |
| 2.80 | current | `shader.inputs['Normal']` | `MaterialObject.py:554` | |
| 2.80 | current | `emission.inputs['Color']` | `MaterialObject.py:533` | |
| | | | | |
| | | **Animation Data** | | |
| 2.80 | current | `object.animation_data_create()` | `ModelSet.py:64`, `MaterialAnimation.py:95` | |
| 2.80 | current | `object.animation_data.action = action` | `ModelSet.py:65,102`, `MaterialAnimation.py:87,100` | |
| 4.4 | current | `animation_data.action_slot = slot` | `ModelSet.py:67`, `MaterialAnimation.py:106` | Guarded: `>= (4, 4, 0)` or `>= (4, 5, 0)` |
| 4.5 | current | `action.slots.new(type, name)` | `ModelSet.py:54`, `MaterialAnimation.py:104` | Guarded: `>= (4, 5, 0)` |
| 4.5 | current | `action.slots.active = slot` | `ModelSet.py:55`, `MaterialAnimation.py:105` | Guarded: `>= (4, 5, 0)` |
| 4.5 | current | `action.slots[0]` | `ModelSet.py:55,67`, `MaterialAnimation.py:105,106` | |
| 2.80 | current | `action.use_fake_user = True` | `ModelSet.py:50`, `MaterialAnimation.py:99` | |
| 2.80 | current | `action.name = '...'` | `ModelSet.py:84` | |
| | | | | |
| | | **F-Curves & Keyframes** | | |
| 2.80 | current | `action.fcurves.new(data_path, index=n)` | `AnimationJoint.py:98,122-148`, `MaterialAnimation.py:134,137,149`, `TextureAnimation.py:76` | |
| 2.80 | current | `action.fcurves.remove(curve)` | `AnimationJoint.py:116,212,273`, `MaterialAnimation.py:144` | |
| 2.80 | current | `action.fcurves` (iteration) | `ModelSet.py:73` | |
| 2.80 | current | `curve.keyframe_points.insert(frame, value)` | `AnimationJoint.py:124,129,134,199-207,266`, `MaterialAnimation.py:142` | Returns keyframe; `.interpolation` set inline |
| 2.80 | current | `keyframe.interpolation = '...'` | `AnimationJoint.py:199-207,266`, `MaterialAnimation.py:142` | `'BEZIER'`, `'LINEAR'` |
| 2.80 | current | `keyframe.co` | `ModelSet.py:76,78`, `TextureAnimation.py:83` | `[frame, value]` tuple |
| 2.80 | current | `curve.evaluate(frame)` | `AnimationJoint.py:151-153,161-169,246` | |
| 2.80 | current | `curve.modifiers.new('CYCLES')` | `AnimationJoint.py:104,270`, `MaterialAnimation.py:154`, `TextureAnimation.py:80` | |
| | | | | |
| | | **NLA** | | |
| 2.80 | current | `material.animation_data.nla_tracks.new()` | `MaterialAnimation.py:82` | |
| 2.80 | current | `track.name = '...'` | `MaterialAnimation.py:83` | |
| 2.80 | current | `track.mute = True` | `MaterialAnimation.py:84` | |
| 2.80 | current | `track.strips.new(name, start, action)` | `MaterialAnimation.py:85` | |
| 2.80 | current | `strip.extrapolation = 'HOLD'` | `MaterialAnimation.py:86` | |
| | | | | |
| | | **Light Data** | | |
| 2.80 | current | `light_data.color = [r, g, b]` | `Light.py:96-98` | |
| | | | | |
| | | **Image Data** | | |
| 2.80 | current | `image.pixels = [...]` | `Image.py:134` | Flat list of RGBA floats |
| 2.80 | current | `image.alpha_mode = 'CHANNEL_PACKED'` | `Image.py:135` | |
| 2.80 | current | `image.filepath_raw = path` | `Image.py:151` | |
| 2.80 | current | `image.file_format = 'PNG'` | `Image.py:152` | |
| 2.80 | current | `image.save()` | `Image.py:153` | |
| 2.80 | current | `image.pack()` | `Image.py:156` | |
| | | | | |
| | | **Curve / Spline Data** | | |
| 2.80 | current | `curve_data.dimensions = '3D'` | `Spline.py:129` | |
| 2.80 | current | `curve_data.splines.new('POLY')` | `Spline.py:133,148` | |
| 2.80 | current | `curve_data.splines.new('NURBS')` | `Spline.py:139` | |
| 2.80 | current | `spline.points.add(n)` | `Spline.py:134,140,149` | |
| 2.80 | current | `spline.points[i].co = Vector(...)` | `Spline.py:136,143,151` | 4D vector `(x, y, z, w)` |
| 2.80 | current | `spline.use_endpoint_u = True` | `Spline.py:144` | |
| 2.80 | current | `spline.order_u = n` | `Spline.py:145` | |
| | | | | |
| | | **mathutils** | | |
| 2.80 | current | `Vector((...))` | `Joint.py:76,78,126`, `ModelSet.py:191,260,264,265,272,278,284,285,290,292`, `AnimationJoint.py:191,261`, `PObject.py:191,489,497`, `Mesh.py:118`, `Light.py:103,109`, `Spline.py:136,143,151` | |
| 2.80 | current | `Matrix.Translation(vec)` | `Joint.py:126`, `ModelSet.py:135`, `AnimationJoint.py:261`, `Light.py:103,104,109` | |
| 2.80 | current | `Matrix.Rotation(angle, size, axis)` | `Joint.py:123-125`, `ModelSet.py:180`, `Light.py:104,120` | |
| 2.80 | current | `Matrix.Scale(factor, size, axis)` | `Joint.py:120-122` | |
| 2.80 | current | `Matrix(list)` | `Mesh.py:75,124,177,182` | Construct from nested list |
| 2.80 | current | `matrix.identity()` | `Mesh.py:183` | |
| 2.80 | current | `matrix.inverted()` | `Mesh.py:113,169,173`, `AnimationJoint.py:176,178,241` | |
| 2.80 | current | `matrix.inverted_safe()` | `AnimationJoint.py:181` | Returns identity if singular |
| 2.80 | current | `matrix.transpose()` | `Mesh.py:114` | |
| 2.80 | current | `matrix.to_3x3()` | `Mesh.py:112` | |
| 2.80 | current | `matrix.to_4x4()` | `Mesh.py:115` | |
| 2.80 | current | `matrix.to_scale()` | `ModelSet.py:267,287` | |
| 2.80 | current | `matrix.to_translation()` | `AnimationJoint.py:263`, `ModelSet.py:260` | |
| 2.80 | current | `matrix.decompose()` | `AnimationJoint.py:182` | Returns `(trans, rot, scale)` |
| 2.80 | current | `matrix.normalized()` | `Joint.py:103,106,109` | |
| 2.80 | current | `matrix.translation` | `ModelSet.py:260,278` | |
| 2.80 | current | `matrix.col[n]` | `ModelSet.py:265,285` | Column access |
| 2.80 | current | `vector.normalize()` | `PObject.py:491,497` | In-place |
| 2.80 | current | `vector.normalized()` | `Mesh.py:118`, `ModelSet.py:265,285` | Returns copy |
| 2.80 | current | `vector.length` | `PObject.py:490,496` | |
| 2.80 | current | `quaternion.to_euler()` | `AnimationJoint.py:183` | |
| 2.80 | current | `Euler(...)` | `Joint.py:3` | Imported but used indirectly |

## Version-Guarded Code Paths

The addon uses `BlenderVersion` checks to handle API differences across versions:

| Guard | Feature | File | Lines |
|-------|---------|------|-------|
| `>= (4, 5, 0)` | Action slots (`action.slots.new()`, `.active`, `.action_slot`) | `ModelSet.py:53-55`, `MaterialAnimation.py:103-106` | |
| `>= (4, 4, 0)` | `animation_data.action_slot` assignment | `ModelSet.py:66-67` | |
| `>= (4, 0, 0)` | Specular input renamed to `"Specular IOR Level"` | `MaterialObject.py:510` | |
| `>= (4, 0, 0)` | `"Specular Tint"` changed from float to RGBA | `MaterialObject.py:516-519` | |
| `< (4, 1, 0)` | `mesh.use_auto_smooth = True` (removed in 4.1) | `PObject.py:234-235` | |

## Deprecated APIs Still In Use

| API | Status | Replacement | Impact |
|-----|--------|-------------|--------|
| `ShaderNodeMixRGB` | Deprecated 3.4 | `ShaderNodeMix` | Still functional; used extensively for TEV and colormap blending |
| `mesh.vertex_colors` | Deprecated 3.2 | Color attributes API | Still functional; used for CLR0/CLR1 vertex colors and alpha |
| `mesh.normals_split_custom_set()` | Workflow changed 4.1 | Auto Smooth modifier / geometry nodes | Still callable; `use_auto_smooth` guard already in place |
