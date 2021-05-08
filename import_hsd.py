import os
import math
import struct

if "bpy" in locals():
    import importlib
    if "hsd" in locals():
        importlib.reload(hsd)
    if "gx" in locals():
        importlib.reload(gx)
    if "img" in locals():
        importlib.reload(img)

from . import hsd, gx, img

import time

import bpy
from mathutils import Matrix, Euler, Vector
"""

import hsd
import gx

"""

#TODO list
#features:
#implement comp tev
#implement texture animations
#animations of other properties
#culling?
#figure out how the skyboxes are rendered shadeless (just no lights assigned?)
#needed optimizations (bottlenecks):
#image conversion
#bugs:
#fix custom normals #done?
#fix texture transforms
#why are the shadows in pyrite white?
#misc:
#deprecate blender internal material

ikhack = True
bone_count = 0
armature_count = 0
light_count = 0
image_count = 0
anim_max_frame = 1000

def error_output(string):
    print('Error: ' + string)
    return {'CANCELLED'}

def notice_output(string):
    print(string)

def load_hsd(filepath, context = None, offset = 0, scene_name = 'scene_data', data_type = 'SCENE', import_animation = True):
    data = None
    try:
        file = open( filepath, 'rb')
        data = bytearray(os.path.getsize( filepath))
        file.readinto(data)
        data = memoryview(data)
        file.close()
    except:
        error_output("Couldn't read file")
        return

    print ("Read File " +  filepath)
    hsd.HSD_reset_created_structs()
    if len(data) - offset < hsd.HSD_get_struct_size('HSD_ArchiveHeader'):
        error_output("Invalid data: Smaller than Header size")
        return

    if filepath[-4:] == '.pkx':
        # check for byte pattern unique to XD pkx models
        isXDModel = struct.unpack('>I', data[32:32+4])[0] == 0xFFFFFFFF

        pkx_header_size = 0xE60 if isXDModel else 0x40
        gpt1SizeOffset = 8 if isXDModel else 4
        gpt1Size = struct.unpack('>I', data[gpt1SizeOffset:gpt1SizeOffset+4])[0]

        if (gpt1Size > 0) and isXDModel:
            pkx_header_size += gpt1Size + ((0x20 - (gpt1Size % 0x20)) % 0x20)
        data = data[pkx_header_size:]

    #this is where our header should be
    header_data = data[offset:]

    hsd.HSD_reset_created_structs()

    header, _ = hsd.HSD_read_struct('HSD_ArchiveHeader', header_data, -1)
    reloc_size = header.nb_reloc * hsd.HSD_get_struct_size('HSD_ArchiveRelocationInfo')
    public_size = header.nb_public * hsd.HSD_get_struct_size('HSD_ArchivePublicInfo')
    extern_size = header.nb_extern * hsd.HSD_get_struct_size('HSD_ArchiveExternInfo')
    header_size = 32
    data_size = header.data_size + header_size + reloc_size + public_size + extern_size
    print(header.file_size)
    print(data_size)
    if not (header.file_size <= len(header_data) and  data_size <= header.file_size):
        return error_output("Invalid data: file_size greater than read data")

    #location of the info array
    info = data[offset + header_size + header.data_size:]

    scene_info = hsd.HSD_get_archive_section(info[reloc_size:], header, scene_name)
    if not scene_info:
        return error_output("Couldn't find Scene")

    #pointer offsets are relative to the end of the header, since we already have the header object
    #and the info arrays we'll adjust our memoryview to only cover the main data
    data = data[offset + header_size:offset + header_size + header.data_size]

    #make sure the current selection doesn't mess with anything
    if bpy.ops.object.select_all.poll():
        bpy.ops.object.select_all(action='DESELECT')

    if data_type == 'BONE':
        load_bone(data, scene_info, info[0:], filepath)
    else:
        load_scene(data, scene_info, info[0:], filepath, import_animation)

    return {'FINISHED'}

def load_bone(data, info, rel, filepath):
    root_joint, valid = hsd.HSD_init_Joint(data, info.entry)
    mesh_dict, material_dict = init_geometry()
    if valid:
        armature = load_model(root_joint, mesh_dict, material_dict)
    else:
        error_output("Invalid Armature")

def load_scene(data, scene_info, rel, filepath, import_animation = True):
    scene = hsd.HSD_initialize_scene(data, scene_info, rel)
    if not scene:
        return error_output("Invalid Scene")

    scenedescs = hsd.HSD_get_struct_dict('HSD_SceneDesc')
    scene = list(scenedescs.values())[0]

    #do geometry here because the way it's currently implemented it initializes geometry from all models
    mesh_dict, material_dict = init_geometry()

    for k, modelset in enumerate(scene.modelsets):
        root_joint = modelset.joint
        if not root_joint:
            notice_output("Empty Model")
            continue

        armature = load_model(root_joint, mesh_dict, material_dict)

        if import_animation:
            n_a = len(modelset.animjoints) if modelset.animjoints else 0
            n_m = len(modelset.matanimjoints) if modelset.matanimjoints else 0
            n_s = len(modelset.shapeanimjoints) if modelset.shapeanimjoints else 0

            print('ANIMS: %d %d %d' % (n_a, n_m, n_s))

            anim_count = max(n_a, n_m, n_s)





            for i in range(anim_count):



                if modelset.animjoints:

                    global cur_anim
                    cur_anim = i
                    animjoint = modelset.animjoints[i]
                    if animjoint.aobjdesc or animjoint.child or animjoint.next:
                        action = bpy.data.actions.new(os.path.basename(filepath) + '_Anim' + '' + ' ' + str(k) + ' ' + str(i))
                        action.use_fake_user = True
                        bpy.types.PoseBone.custom_40 = bpy.props.FloatProperty(name="40")
                        add_bone_animation_total(armature, root_joint, modelset.animjoints[i], action)
                #TODO: figure out how to pack this into a single track with the above or something
                #if modelset.matanimjoints:
                #    add_material_animation(material_dict, modelset.matanimjoints[i], action)
                #if modelset.shapeanimjoints:
                #    add_shape_animation(mesh_dict, modelset.shapeanimjoints[i], action)




    for lightset in scene.lightsets:
        light = lightset.lightdesc
        if not light:
            notice_output("Empty Light")
            continue

        light = load_light(light)

cur_anim = 0


#####################################




def add_bone_animation_total(armature, root_joint, animation, action):
    for bone in armature.pose.bones:
        bone.rotation_mode = 'XYZ'
    for bone in armature.data.bones:
        bone.use_local_location = True
    armature.animation_data_create()
    armature.animation_data.action = action
    trav_animjoints_total(root_joint, animation, action, armature.pose)

def trav_animjoints_total(joint, animjoint, action, pose):

    if joint.robj:
        robj = joint.robj
        if robj:
            print(joint.temp_name + ':')
            if joint.flags & hsd.JOBJ_TYPE_MASK == hsd.JOBJ_JOINT1:
                print('JOBJ_JOINT1')
            if joint.flags & hsd.JOBJ_TYPE_MASK == hsd.JOBJ_JOINT2:
                print('JOBJ_JOINT2')
            if joint.flags & hsd.JOBJ_TYPE_MASK == hsd.JOBJ_EFFECTOR:
                print('JOBJ_EFFECTOR')
        while robj:
            print('ROBJ: %.8X TYPE: %.8X SUBTYPE: %.8X' % (robj.id, robj.flags & 0x70000000, robj.flags & 0x0FFFFFFF))
            if (robj.flags & 0x70000000 == 0x10000000):
                print(' JointRef: ' + robj.u.temp_name)
            elif (robj.flags & 0x70000000 == 0x40000000):
                print(' VAL0: %f VAL1: %f' % (robj.val0, robj.val1))
            robj = robj.next
        if animjoint.robjanim:
            print('ROBJANIM')

    if animjoint.aobjdesc:
        add_jointanim_to_armature_total(joint, animjoint.aobjdesc, action, pose)
    if animjoint.child:
        trav_animjoints_total(joint.child, animjoint.child, action, pose)
    if animjoint.next:
        trav_animjoints_total(joint.next, animjoint.next, action, pose)


TRANSFORMCOUNT = (hsd.HSD_A_J_SCAZ - hsd.HSD_A_J_ROTX) + 1

t_jointanim_type_dict = {
    hsd.HSD_A_J_ROTX: ('r', 0),
    hsd.HSD_A_J_ROTY: ('r', 1),
    hsd.HSD_A_J_ROTZ: ('r', 2),
    #hsd.HSD_A_J_PATH: '',
    hsd.HSD_A_J_TRAX: ('l', 0),
    hsd.HSD_A_J_TRAY: ('l', 1),
    hsd.HSD_A_J_TRAZ: ('l', 2),
    hsd.HSD_A_J_SCAX: ('s', 0),
    hsd.HSD_A_J_SCAY: ('s', 1),
    hsd.HSD_A_J_SCAZ: ('s', 2),
}

def add_jointanim_to_armature_total(joint, aobjdesc, action, pose):
    t0 = time.perf_counter()

    #trans, rot, scale = joint.temp_matrix_local.decompose()
    trans, rot, scale = joint.position, joint.rotation, joint.scale
    #rot = rot.to_euler('XYZ')
    if aobjdesc.flags & hsd.AOBJ_NO_ANIM:
        return
    fobj = aobjdesc.fobjdesc
    invmtx = joint.temp_matrix_local.inverted()
    #invmtx = invmtx * Matrix.Translation(Vector((0.0,1.0,0.0)))
    transform_list = [0] * (TRANSFORMCOUNT)
    while fobj:
        #print(hsd_a_j_dict[fobj.type])
        if fobj.type == hsd.HSD_A_J_PATH:
            pass #TODO: implement paths
            print('HSD_A_J_PATH')
        elif fobj.type >= hsd.HSD_A_J_ROTX and fobj.type <= hsd.HSD_A_J_SCAZ:
            data_type, component = t_jointanim_type_dict[fobj.type]
            data_path = 'pose.bones["' + joint.temp_name + '"]' + '.' + data_type
            curve = action.fcurves.new(data_path, index=component)
            transform_list[fobj.type - hsd.HSD_A_J_ROTX] = curve

            #total values for testing
            curve_bias = 0
            curve_scale = 1
            read_fobjdesc(fobj, curve, curve_bias, curve_scale, False)

            if aobjdesc.flags & hsd.AOBJ_ANIM_LOOP:
                curve.modifiers.new('CYCLES')
        else:
            print('Unknown A Type: %.2X JOINT: %s' % (fobj.type, joint.temp_name))

        fobj = fobj.next

    for i in range(3):
        if not transform_list[i]:
            curve = action.fcurves.new('pose.bones["' + joint.temp_name + '"].r', index=i)
            curve.keyframe_points.insert(0, joint.rotation[i])
            transform_list[i] = curve
        if not transform_list[i+4]:
            curve = action.fcurves.new('pose.bones["' + joint.temp_name + '"].l', index=i)
            curve.keyframe_points.insert(0, joint.position[i])
            transform_list[i+4] = curve
        if not transform_list[i+7]:
            curve = action.fcurves.new('pose.bones["' + joint.temp_name + '"].s', index=i)
            curve.keyframe_points.insert(0, joint.scale[i])
            transform_list[i+7] = curve

    new_transform_list = [0] * 10

    for i in range(3):
        curve = action.fcurves.new('pose.bones["' + joint.temp_name + '"].rotation_euler', index=i)
        new_transform_list[i] = curve
        curve = action.fcurves.new('pose.bones["' + joint.temp_name + '"].location', index=i)
        new_transform_list[i+4] = curve
        curve = action.fcurves.new('pose.bones["' + joint.temp_name + '"].scale', index=i)
        new_transform_list[i+7] = curve

    global anim_max_frame
    for frame in range(min(int(aobjdesc.endframe), anim_max_frame)):
        scale_x = Matrix.Scale(transform_list[7].evaluate(frame), 4, [1.0,0.0,0.0])
        scale_y = Matrix.Scale(transform_list[8].evaluate(frame), 4, [0.0,1.0,0.0])
        scale_z = Matrix.Scale(transform_list[9].evaluate(frame), 4, [0.0,0.0,1.0])
        rotation_x = Matrix.Rotation(transform_list[0].evaluate(frame), 4, 'X')
        rotation_y = Matrix.Rotation(transform_list[1].evaluate(frame), 4, 'Y')
        rotation_z = Matrix.Rotation(transform_list[2].evaluate(frame), 4, 'Z')
        translation = Matrix.Translation(Vector((transform_list[4].evaluate(frame), transform_list[5].evaluate(frame), transform_list[6].evaluate(frame))))
        # T * R * S
        rotation = rotation_z @ rotation_y @ rotation_x
        scale = scale_z @ scale_y @ scale_x
        mtx = translation @ rotation @ scale
        Bmtx = invmtx @ mtx
        trans, rot, scale = Bmtx.decompose()
        rot = rot.to_euler()
        new_transform_list[0].keyframe_points.insert(frame, rot[0]).interpolation = 'BEZIER'
        new_transform_list[1].keyframe_points.insert(frame, rot[1]).interpolation = 'BEZIER'
        new_transform_list[2].keyframe_points.insert(frame, rot[2]).interpolation = 'BEZIER'
        new_transform_list[4].keyframe_points.insert(frame, trans[0]).interpolation = 'BEZIER'
        new_transform_list[5].keyframe_points.insert(frame, trans[1]).interpolation = 'BEZIER'
        new_transform_list[6].keyframe_points.insert(frame, trans[2]).interpolation = 'BEZIER'
        new_transform_list[7].keyframe_points.insert(frame, scale[0]).interpolation = 'BEZIER'
        new_transform_list[8].keyframe_points.insert(frame, scale[1]).interpolation = 'BEZIER'
        new_transform_list[9].keyframe_points.insert(frame, scale[2]).interpolation = 'BEZIER'

    for c in transform_list:
        if c:
            action.fcurves.remove(c)

    """transform *= Matrix.Translation(Vector(position))
    posebone = pose.bones[joint.temp_name]
    by.ops.screen.frame_set(frame)
    posebone.matrix_local = transform
    posebone.keyframe_insert(data_path = 'location')
    posebone.keyframe_insert(data_path = 'rotation')
    posebone.keyframe_insert(data_path = 'scale')
    """

    t1 = time.perf_counter()

    #print (('anim %s: ' % joint.temp_name) + str(t1 - t0))



####################################


def add_bone_animation(armature, root_joint, animation, action):
    for bone in armature.pose.bones:
        bone.rotation_mode = 'XYZ'
    for bone in armature.data.bones:
        bone.use_local_location = False
        #bone.use_inherit_rotation = False
    armature.animation_data_create()
    armature.animation_data.action = action
    trav_animjoints(root_joint, animation, action)

def trav_animjoints(joint, animjoint, action):
    if animjoint.flags:
        print('Joint: %s\t AnimJointFlags: %.8X' % (joint.temp_name, animjoint.flags))
    if animjoint.aobjdesc:
        add_jointanim_to_armature(joint, animjoint.aobjdesc, action)
    if animjoint.child:
        trav_animjoints(joint.child, animjoint.child, action)
    if animjoint.next:
        trav_animjoints(joint.next, animjoint.next, action)

def add_jointanim_to_armature(joint, aobjdesc, action):
    trans, rot, scale = joint.position, joint.rotation, joint.scale
    #if aobjdesc.flags & hsd.AOBJ_NO_ANIM:
    #    return
    printd = (joint.temp_name == 'Bone57')
    if printd:
        print(action.name)
        print('AOBJ FLAGS: %.8X' % aobjdesc.flags)
    fobj = aobjdesc.fobjdesc
    transform_list = [0] * 10
    while fobj:
        #print(hsd_a_j_dict[fobj.type])
        if fobj.type == hsd.HSD_A_J_PATH:
            #TODO: implement paths
            print('HSD_A_J_PATH')
        elif (fobj.type >= hsd.HSD_A_J_ROTX and fobj.type <= hsd.HSD_A_J_SCAZ):
            data_type, component = jointanim_type_dict[fobj.type]
            data_path = 'pose.bones["' + joint.temp_name + '"]' + '.' + data_type
            curve = action.fcurves.new(data_path, index=component)
            transform_list[fobj.type - hsd.HSD_A_J_ROTX] = curve

            #HSD curves give absolute transform values while the Pose's are relative to the EditBones'
            #This means we'll have to adjust all the values accordingly
            curve_bias = 0
            curve_scale = 1
            if fobj.type == hsd.HSD_A_J_ROTX:
                curve_bias = -rot[0]
            elif fobj.type == hsd.HSD_A_J_ROTY:
                curve_bias = -rot[1]
            elif fobj.type == hsd.HSD_A_J_ROTZ:
                curve_bias = -rot[2]
            elif fobj.type == hsd.HSD_A_J_TRAX:
                curve_bias = -trans[0]
            elif fobj.type == hsd.HSD_A_J_TRAY:
                curve_bias = -trans[1]
            elif fobj.type == hsd.HSD_A_J_TRAZ:
                curve_bias = -trans[2]
            elif fobj.type == hsd.HSD_A_J_SCAX:
                curve_scale = 1 / scale[0]
            elif fobj.type == hsd.HSD_A_J_SCAY:
                curve_scale = 1 / scale[1]
            elif fobj.type == hsd.HSD_A_J_SCAZ:
                curve_scale = 1 / scale[2]

            if printd:
                print(hsd_a_j_dict[fobj.type])
            read_fobjdesc(fobj, curve, curve_bias, curve_scale, printd)
            #read_fobjdesc(fobj, curve, 0, 1, printd)

            if aobjdesc.flags & hsd.AOBJ_ANIM_LOOP:
                curve.modifiers.new('CYCLES')
        else:
            print('Unknown A Type: %.2X' % fobj.type)
            if fobj.type in hsd_a_j_dict:
                data_type = hsd_a_j_dict[fobj.type]
            else:
                data_type = 'custom_%d' % fobj.type
            data_path = 'pose.bones["' + joint.temp_name + '"]' + '.' + data_type
            curve = action.fcurves.new(data_path, index=0)
            read_fobjdesc(fobj, curve, 0, 1, printd)

        fobj = fobj.next

    for i in range(3):
        if not transform_list[i]:
            curve = action.fcurves.new('pose.bones["' + joint.temp_name + '"].rotation_euler', index=i)
            transform_list[i] = curve
            curve.keyframe_points.insert(0, 0)
        if not transform_list[i+4]:
            curve = action.fcurves.new('pose.bones["' + joint.temp_name + '"].location', index=i)
            transform_list[i+4] = curve
            curve.keyframe_points.insert(0, 0)
        if not transform_list[i+7]:
            curve = action.fcurves.new('pose.bones["' + joint.temp_name + '"].scale', index=i)
            transform_list[i+7] = curve
            curve.keyframe_points.insert(0, 1)

    bonemtxinv = joint.temp_matrix_local.inverted()
    for frame in range(int(aobjdesc.endframe)):
        scale = list(tuple(joint.scale))
        rotation = list(tuple(joint.rotation))
        position = list(tuple(joint.position))
        for i in range(3):
            rotation[i] += transform_list[i].evaluate(frame)
            position[i] += transform_list[i+4].evaluate(frame)
            scale[i] *= transform_list[i+7].evaluate(frame)
        posetargetmtx = compileSRTmtx(scale, rotation, position)
        posemtx = bonemtxinv @ posetargetmtx
        trans, rot, scale = posemtx.decompose()
        for i in range(3):
            transform_list[i].keyframe_points.insert(frame, rot[i])
            transform_list[i+4].keyframe_points.insert(frame, trans[i])
            transform_list[i+7].keyframe_points.insert(frame, scale[i])

hsd_a_j_dict = {
    hsd.HSD_A_J_ROTX: 'HSD_A_J_ROTX',
    hsd.HSD_A_J_ROTY: 'HSD_A_J_ROTY',
    hsd.HSD_A_J_ROTZ: 'HSD_A_J_ROTZ',
    hsd.HSD_A_J_PATH: 'HSD_A_J_PATH',
    hsd.HSD_A_J_TRAX: 'HSD_A_J_TRAX',
    hsd.HSD_A_J_TRAY: 'HSD_A_J_TRAY',
    hsd.HSD_A_J_TRAZ: 'HSD_A_J_TRAZ',
    hsd.HSD_A_J_SCAX: 'HSD_A_J_SCAX',
    hsd.HSD_A_J_SCAY: 'HSD_A_J_SCAY',
    hsd.HSD_A_J_SCAZ: 'HSD_A_J_SCAZ',
    hsd.HSD_A_J_NODE: 'HSD_A_J_NODE',
    hsd.HSD_A_J_BRANCH: 'HSD_A_J_BRANCH',
    hsd.HSD_A_J_SETBYTE0: 'HSD_A_J_SETBYTE0',
    hsd.HSD_A_J_SETBYTE1: 'HSD_A_J_SETBYTE1',
    hsd.HSD_A_J_SETBYTE2: 'HSD_A_J_SETBYTE2',
    hsd.HSD_A_J_SETBYTE3: 'HSD_A_J_SETBYTE3',
    hsd.HSD_A_J_SETBYTE4: 'HSD_A_J_SETBYTE4',
    hsd.HSD_A_J_SETBYTE5: 'HSD_A_J_SETBYTE5',
    hsd.HSD_A_J_SETBYTE6: 'HSD_A_J_SETBYTE6',
    hsd.HSD_A_J_SETBYTE7: 'HSD_A_J_SETBYTE7',
    hsd.HSD_A_J_SETBYTE8: 'HSD_A_J_SETBYTE8',
    hsd.HSD_A_J_SETBYTE9: 'HSD_A_J_SETBYTE9',
    hsd.HSD_A_J_SETFLOAT0: 'HSD_A_J_SETFLOAT0',
    hsd.HSD_A_J_SETFLOAT1: 'HSD_A_J_SETFLOAT1',
    hsd.HSD_A_J_SETFLOAT2: 'HSD_A_J_SETFLOAT2',
    hsd.HSD_A_J_SETFLOAT3: 'HSD_A_J_SETFLOAT3',
    hsd.HSD_A_J_SETFLOAT4: 'HSD_A_J_SETFLOAT4',
    hsd.HSD_A_J_SETFLOAT5: 'HSD_A_J_SETFLOAT5',
    hsd.HSD_A_J_SETFLOAT6: 'HSD_A_J_SETFLOAT6',
    hsd.HSD_A_J_SETFLOAT7: 'HSD_A_J_SETFLOAT7',
    hsd.HSD_A_J_SETFLOAT8: 'HSD_A_J_SETFLOAT8',
    hsd.HSD_A_J_SETFLOAT9: 'HSD_A_J_SETFLOAT9',
}

def read_fobjdesc(fobjdesc, curve, bias, scale, printd):
    printa = printd
    printd = 0
    current_frame = 0 - fobjdesc.startframe // 1
    cur_pos = 0
    ad = fobjdesc.ad
    if printd:
        print('DATA: %s' % ''.join(['%.2X' % b for b in ad[:fobjdesc.length]]))

    value_type = (fobjdesc.frac_value & hsd.HSD_A_FRAC_TYPE_MASK)
    frac_value = (fobjdesc.frac_value & hsd.HSD_A_FRAC_MASK)
    slope_type = (fobjdesc.frac_slope & hsd.HSD_A_FRAC_TYPE_MASK)
    frac_slope = (fobjdesc.frac_slope & hsd.HSD_A_FRAC_MASK)
    if printa:
        print('Value: %s %d' % (frac_type_dict[value_type], frac_value))
        print('Slope: %s %d' % (frac_type_dict[slope_type], frac_slope))

    keyframes = []
    slopes = []

    cur_slope = 0
    if printd:
        print('LENGTH %d' % fobjdesc.length)
    while cur_pos < fobjdesc.length:
        if printd:
            print('CURPOS %d' % cur_pos)
        opcode = ad[cur_pos] & hsd.HSD_A_OP_MASK
        node_count = (ad[cur_pos] & hsd.HSD_A_PACK0_MASK) >> hsd.HSD_A_PACK0_SHIFT
        shift = 0
        while ad[cur_pos] & hsd.HSD_A_PACK_EXT:
            cur_pos += 1
            node_count += (ad[cur_pos] & hsd.HSD_A_PACK1_MASK) << (hsd.HSD_A_PACK1_BIT * shift + 3)
            shift += 1
        cur_pos += 1
        #there's always at least one node
        node_count += 1

        if opcode == hsd.HSD_A_OP_SLP:
            for i in range(node_count):
                _, cur_slope, cur_pos = read_node_values(opcode, value_type, frac_value, slope_type, frac_slope, ad, cur_pos)
        else:
            for i in range(node_count):
                val, slope, cur_pos = read_node_values(opcode, value_type, frac_value, slope_type, frac_slope, ad, cur_pos)
                if printd:
                    print(val)
                slopes.append((cur_slope, slope))
                cur_slope = slope

                keyframe = curve.keyframe_points.insert(current_frame, (val + bias) * scale)
                if printd:
                    print(opcode)
                keyframe.interpolation = interpolation_dict[opcode]
                keyframes.append(keyframe)

                if not opcode == hsd.HSD_A_OP_NONE:
                    shift = 0
                    wait = 0
                    while True:
                        wait += (ad[cur_pos] & hsd.HSD_A_WAIT_MASK) << (hsd.HSD_A_WAIT_BIT * shift)
                        if printd:
                            print('WaitByte %.2X' % ad[cur_pos])
                        shift += 1
                        if not ad[cur_pos] & hsd.HSD_A_WAIT_EXT:
                            break
                        cur_pos += 1
                    if printd:
                        print('WAIT %d' % wait)
                    cur_pos += 1
                    #TODO: Is there always at least one wait frame ?
                    current_frame += wait

    for i in range(len(keyframes)):
        #TODO: I don't know whether this is the correct conversion
        #try either normalized tangent vectors or x = 1

        #assuming x = 1
        if i > 0:
            l_delta = keyframe.co[0] - keyframes[i - 1].co[0]
            keyframe.handle_left[:] = (keyframe.co[0] - l_delta / 3, keyframe.co[1] - slopes[i][0] * l_delta / 3)
        if i < len(keyframes) - 1:
            r_delta = keyframes[i + 1].co[0] - keyframe.co[0]
            keyframe.handle_right[:] = (keyframe.co[0] + r_delta / 3, keyframe.co[1] + slopes[i][1] * r_delta / 3)

frac_type_dict = {
    hsd.HSD_A_FRAC_FLOAT: 'HSD_A_FRAC_FLOAT',
    hsd.HSD_A_FRAC_S16: 'HSD_A_FRAC_S16',
    hsd.HSD_A_FRAC_U16: 'HSD_A_FRAC_U16',
    hsd.HSD_A_FRAC_S8: 'HSD_A_FRAC_S8',
    hsd.HSD_A_FRAC_U8: 'HSD_A_FRAC_U8',
}

opcode_dict = {
    hsd.HSD_A_OP_NONE: 'HSD_A_OP_NONE',
    hsd.HSD_A_OP_CON: 'HSD_A_OP_CON',
    hsd.HSD_A_OP_LIN: 'HSD_A_OP_LIN',
    hsd.HSD_A_OP_SPL0: 'HSD_A_OP_SPL0',
    hsd.HSD_A_OP_SPL: 'HSD_A_OP_SPL',
    hsd.HSD_A_OP_SLP: 'HSD_A_OP_SLP',
    hsd.HSD_A_OP_KEY: 'HSD_A_OP_KEY',
}

def read_node_values(opcode, value_type, frac_value, slope_type, frac_slope, ad, cur_pos):
    slope = 0
    val = 0

    #frac_value += 1
    if opcode == hsd.HSD_A_OP_NONE:
        return 0, 0, cur_pos

    if not opcode == hsd.HSD_A_OP_SLP:
        if value_type == hsd.HSD_A_FRAC_FLOAT:
            val = struct.unpack('f', ad[cur_pos:cur_pos + 4])[0]
            cur_pos += 4
        elif value_type == hsd.HSD_A_FRAC_S16:
            val = struct.unpack('h', ad[cur_pos:cur_pos + 2])[0] / (1 << frac_value)
            cur_pos += 2
        elif value_type == hsd.HSD_A_FRAC_U16:
            val = struct.unpack('H', ad[cur_pos:cur_pos + 2])[0] / (1 << frac_value)
            cur_pos += 2
        elif value_type == hsd.HSD_A_FRAC_S8:
            val = struct.unpack('b', ad[cur_pos:cur_pos + 1])[0] / (1 << frac_value)
            cur_pos += 1
        elif value_type == hsd.HSD_A_FRAC_U8:
            val = struct.unpack('B', ad[cur_pos:cur_pos + 1])[0] / (1 << frac_value)
            cur_pos += 1

    if (opcode == hsd.HSD_A_OP_SPL or
        opcode == hsd.HSD_A_OP_SLP):
        if slope_type == hsd.HSD_A_FRAC_FLOAT:
            slope = struct.unpack('f', ad[cur_pos:cur_pos + 4])[0]
            cur_pos += 4
        elif slope_type == hsd.HSD_A_FRAC_S16:
            slope = struct.unpack('h', ad[cur_pos:cur_pos + 2])[0] / (1 << frac_slope)
            cur_pos += 2
        elif slope_type == hsd.HSD_A_FRAC_U16:
            slope = struct.unpack('H', ad[cur_pos:cur_pos + 2])[0] / (1 << frac_slope)
            cur_pos += 2
        elif slope_type == hsd.HSD_A_FRAC_S8:
            slope = struct.unpack('b', ad[cur_pos:cur_pos + 1])[0] / (1 << frac_slope)
            cur_pos += 1
        elif slope_type == hsd.HSD_A_FRAC_U8:
            slope = struct.unpack('B', ad[cur_pos:cur_pos + 1])[0] / (1 << frac_slope)
            cur_pos += 1

    return val, slope, cur_pos

interpolation_dict = {
    hsd.HSD_A_OP_NONE: 'CONSTANT',
    hsd.HSD_A_OP_CON: 'CONSTANT',
    hsd.HSD_A_OP_LIN: 'LINEAR',
    hsd.HSD_A_OP_SPL0: 'BEZIER',
    hsd.HSD_A_OP_SPL: 'BEZIER',
    #hsd.HSD_A_OP_SLP: '',
    hsd.HSD_A_OP_KEY: 'LINEAR', #?
}


jointanim_type_dict = {
    hsd.HSD_A_J_ROTX: ('rotation_euler', 0),
    hsd.HSD_A_J_ROTY: ('rotation_euler', 1),
    hsd.HSD_A_J_ROTZ: ('rotation_euler', 2),
    #hsd.HSD_A_J_PATH: '',
    hsd.HSD_A_J_TRAX: ('location', 0),
    hsd.HSD_A_J_TRAY: ('location', 1),
    hsd.HSD_A_J_TRAZ: ('location', 2),
    hsd.HSD_A_J_SCAX: ('scale', 0),
    hsd.HSD_A_J_SCAY: ('scale', 1),
    hsd.HSD_A_J_SCAZ: ('scale', 2),
}


def add_material_animation(material_dict, animations, action):
    pass

def add_shape_animation(mesh_dict, animations, action):
    pass

def init_geometry():
    hsd_textures = hsd.HSD_get_struct_dict('HSD_TObjDesc')
    texture_dict = {}
    image_dict = make_textures(hsd_textures.values(), texture_dict)

    hsd_materials = hsd.HSD_get_struct_dict('HSD_MObjDesc')
    material_dict = {}
    for hsd_material in hsd_materials.values():
        material_dict[hsd_material.id] = make_approx_cycles_material(hsd_material, image_dict)

    hsd_meshes = hsd.HSD_get_struct_dict('HSD_DObjDesc')
    mesh_dict = {}
    for hsd_mesh in hsd_meshes.values():
        pobj = hsd_mesh.pobj
        while pobj:
            ob = make_mesh(pobj, mesh_dict)
            #add material
            #mat = make_material(hsd_mesh.mobj, texture_dict)
            mat = material_dict[hsd_mesh.mobj.id]
            ob.data.materials.append(mat)
            pobj = pobj.next
    return mesh_dict, material_dict

#normalize u8 to float
#only used for color so we can do srgb conversion here
def normcolor(x):
    if len(x) > 2:
        color = [c / 255 for c in x]
        return tolin(color)
    else:
        type = x[1]
        val = x[0] / 255
        if type == 'R' or type == 'G' or type == 'B':
            return tolin([val])[0]
        elif type == 'A':
            return val


def norm8bit(x):
    if hasattr(x, '__iter__'):
        return [c / 255 for c in x]
    else:
        return x / 255

def make_approx_cycles_material(mobj, image_dict):
    material = mobj.mat
    mat = bpy.data.materials.new('')
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    #diff = nodes['Diffuse BSDF']
    #output = nodes['Material Output']
    for node in nodes:
        nodes.remove(node)
    output = nodes.new('ShaderNodeOutputMaterial')
    #nodes.remove(diff)

    mat_diffuse_color = normcolor(material.diffuse)

    #XXX: Print material flags etc
    print(mat.name)
    notice_output('MOBJ FLAGS:\nrendermode: %.8X' % mobj.rendermode)
    if mobj.pedesc:
        pedesc = mobj.pedesc
        notice_output('PEDESC FLAGS:\nflags: %.2X\nref0: %.2X\nref1: %.2X\ndst_alpha: %.2X\ntype: %.2X\nsrc_factor: %.2X\ndst_factor: %.2X\nlogic_op: %.2X\nz_comp: %.2X\nalpha_comp0: %.2X\nalpha_op: %.2X\nalpha_comp1: %.2X' % \
                       (pedesc.flags, pedesc.ref0, pedesc.ref1, pedesc.dst_alpha, pedesc.type, pedesc.src_factor, pedesc.dst_factor, pedesc.logic_op, pedesc.z_comp, pedesc.alpha_comp0, pedesc.alpha_op, pedesc.alpha_comp1))


    textures = []
    toon = None
    tex_num = 0
    texdesc = mobj.texdesc
    while texdesc:
        #if texdesc.flag & hsd.TEX_COORD_TOON:
        #    toon = texdesc

        #XXX:
        notice_output('TOBJ FLAGS:\nid: %.8X\nsrc: %.8X\nflag: %.8X' % (texdesc.texid, texdesc.src, texdesc.flag))
        if texdesc.tev:
            tev = texdesc.tev
            notice_output('TEV FLAGS:\ncolor_op: %.2X\nalpha_op: %.2X\ncolor_bias: %.2X\nalpha_bias: %.2X\n\
color_scale: %.2X\nalpha_scale: %.2X\ncolor_clamp: %.2X\nalpha_clamp: %.2X\n\
color_a: %.2X color_b: %.2X color_c: %.2X color_d: %.2X\n\
alpha_a: %.2X alpha_b: %.2X alpha_c: %.2X alpha_d: %.2X\n\
konst: %.2X%.2X%.2X%.2X tev0: %.2X%.2X%.2X%.2X tev1: %.2X%.2X%.2X%.2X\n\
active: %.8X' % ((tev.color_op, tev.alpha_op, tev.color_bias, tev.alpha_bias,\
                                            tev.color_scale, tev.alpha_scale, tev.color_clamp, tev.alpha_clamp, \
                                            tev.color_a, tev.color_b, tev.color_c, tev.color_d, \
                                            tev.alpha_a, tev.alpha_b, tev.alpha_c, tev.alpha_d) + \
                                            tuple(tev.konst) + tuple(tev.tev0) + tuple(tev.tev1) + \
                                            (tev.active,)))

        print('%.8X' % texdesc.flag)
        #if texdesc.flag & (hsd.TEX_LIGHTMAP_DIFFUSE | hsd.TEX_LIGHTMAP_AMBIENT):
        if mobj.rendermode & (1 << (tex_num + 4)): #is this texture enabled in the material?
            textures.append(texdesc)
        texdesc = texdesc.next
        tex_num += 1
        if tex_num > 7:
            break

    print('textures: %d' % len(textures))

    if mobj.rendermode & hsd.RENDER_DIFFUSE:
        color = nodes.new('ShaderNodeRGB')
        if (mobj.rendermode & hsd.RENDER_DIFFUSE_BITS) == hsd.RENDER_DIFFUSE_VTX:
            color.outputs[0].default_value[:] = [1,1,1,1]
        else:
            color.outputs[0].default_value[:] = mat_diffuse_color

        alpha = nodes.new('ShaderNodeValue')
        if (mobj.rendermode & hsd.RENDER_ALPHA_BITS) == hsd.RENDER_ALPHA_VTX:
            alpha.outputs[0].default_value = 1
        else:
            alpha.outputs[0].default_value = material.alpha
    else:
        if (mobj.rendermode & hsd.CHANNEL_FIELD) == hsd.RENDER_DIFFUSE_MAT:
            color = nodes.new('ShaderNodeRGB')
            color.outputs[0].default_value[:] = mat_diffuse_color
        else:
            #Toon not supported
            #if toon:
            #    color = nodes.new('ShaderNodeTexImage')
            #    color.image = image_dict[toon.id]
            #    #TODO: add the proper texture mapping
            #else:
            color = nodes.new('ShaderNodeAttribute')
            color.attribute_name = 'color_0'

            if not ((mobj.rendermode & hsd.RENDER_DIFFUSE_BITS) == hsd.RENDER_DIFFUSE_VTX):
                diff = nodes.new('ShaderNodeRGB')
                diff.outputs[0].default_value[:] = mat_diffuse_color
                mix = nodes.new('ShaderNodeMixRGB')
                mix.blend_type = 'ADD'
                mix.inputs[0].default_value = 1
                links.new(color.outputs[0], mix.inputs[1])
                links.new(diff.outputs[0], mix.inputs[2])
                color = mix

        if (mobj.rendermode & hsd.RENDER_ALPHA_BITS) == hsd.RENDER_ALPHA_MAT:
            alpha = nodes.new('ShaderNodeValue')
            alpha.outputs[0].default_value = material.alpha
        else:
            alpha = nodes.new('ShaderNodeAttribute')
            alpha.attribute_name = 'alpha_0'

            if not (mobj.rendermode & hsd.RENDER_ALPHA_BITS) == hsd.RENDER_ALPHA_VTX:
                mat_alpha = nodes.new('ShaderNodeValue')
                mat_alpha.outputs[0].default_value = material.alpha
                mix = nodes.new('ShaderNodeMath')
                mix.operation = 'MULTIPLY'
                links.new(alpha.outputs[0], mix.inputs[0])
                links.new(mat_alpha.outputs[0], mix.inputs[1])
                alpha = mix


    last_color = color.outputs[0]
    last_alpha = alpha.outputs[0]
    last_bump  = None

    for texdesc in textures:
        if (texdesc.flag & hsd.TEX_COORD_MASK) == hsd.TEX_COORD_UV:
            uv = nodes.new('ShaderNodeUVMap')
            uv.uv_map = 'uvtex_' + str(texdesc.src - 4)
            uv_output = uv.outputs[0]
        elif (texdesc.flag & hsd.TEX_COORD_MASK) == hsd.TEX_COORD_REFLECTION:
            uv = nodes.new('ShaderNodeTexCoord')
            uv_output = uv.outputs[6]
        else:
            print('UV Type not supported: %X' % (texdesc.flag & hsd.TEX_COORD_MASK))
            uv_output = None

        mapping = nodes.new('ShaderNodeMapping')
        mapping.vector_type = 'TEXTURE'
        mapping.inputs[1].default_value = texdesc.translate #mapping.translation[:]
        mapping.inputs[2].default_value = texdesc.rotate #mapping.rotate[:]
        mapping.inputs[3].default_value = texdesc.scale #mapping.scale[:]

        #blender UV coordinates are relative to the bottom left so we need to account for that
        mapping.inputs[1].default_value[1] = 1 - (texdesc.scale[1] * (texdesc.translate[1] + 1))

        #TODO: Is this correct?
        if (texdesc.flag & hsd.TEX_COORD_MASK) == hsd.TEX_COORD_REFLECTION:
            mapping.inputs[2].default_value[0] -= math.pi/2

        texture = nodes.new('ShaderNodeTexImage')
        texture.image = image_dict[texdesc.id]
        texture.name = ("0x%X" % texdesc.id)
        texture.name += ' flag: %X' % texdesc.flag
        texture.name += (' image: 0x%X ' % (texdesc.imagedesc.image_ptr_id if texdesc.imagedesc else -1))
        texture.name += (' tlut: 0x%X' % (texdesc.tlutdesc.id if texdesc.tlutdesc else -1))

        texture.extension = 'EXTEND'
        if texdesc.wrap_t == gx.GX_REPEAT:
            texture.extension = 'REPEAT'

        interp_dict = {
            gx.GX_NEAR: 'Closest',
            gx.GX_LINEAR: 'Linear',
            gx.GX_NEAR_MIP_NEAR: 'Closest',
            gx.GX_LIN_MIP_NEAR: 'Linear',
            gx.GX_NEAR_MIP_LIN: 'Closest',
            gx.GX_LIN_MIP_LIN: 'Cubic' #XXX use CUBIC?
        }

        if texdesc.lod:
            texture.interpolation = interp_dict[texdesc.lod.minFilt]

        if uv_output:
            links.new(uv_output, mapping.inputs[0])
        links.new(mapping.outputs[0], texture.inputs[0])

        cur_color = texture.outputs[0]
        cur_alpha = texture.outputs[1]
        #do tev
        if texdesc.tev:
            tev = texdesc.tev
            if tev.active & hsd.TOBJ_TEVREG_ACTIVE_COLOR_TEV:
                inputs = [make_tev_input(nodes, texture, tev, i, True) for i in range(4)]
                cur_color = make_tev_op(nodes, links, inputs, tev, True)

            if tev.active & hsd.TOBJ_TEVREG_ACTIVE_ALPHA_TEV:
                inputs = [make_tev_input(nodes, texture, tev, i, False) for i in range(4)]
                cur_alpha = make_tev_op(nodes, links, inputs, tev, False)

            texture.name += ' tev'
        if texdesc.flag & hsd.TEX_BUMP:
            #bumpmap
            if last_bump:
                #idk, just do blending for now to keep the nodes around
                mix = nodes.new('ShaderNodeMixRGB')
                mix.blend_type = 'MIX'
                mix.inputs[0].default_value = texdesc.blending
                links.new(last_bump, mix.inputs[1])
                links.new(cur_color, mix.inputs[2])
                last_bump = mix.outputs[0]
            else:
                last_bump = cur_color
        else:
            #do color
            if (texdesc.flag & hsd.TEX_LIGHTMAP_MASK) & (hsd.TEX_LIGHTMAP_DIFFUSE | hsd.TEX_LIGHTMAP_EXT):
                colormap = texdesc.flag & hsd.TEX_COLORMAP_MASK
                if not (colormap == hsd.TEX_COLORMAP_NONE or
                        colormap == hsd.TEX_COLORMAP_PASS):
                    mix = nodes.new('ShaderNodeMixRGB')
                    mix.blend_type = map_col_op_dict[colormap]
                    mix.inputs[0].default_value = 1
                    ###
                    colormap_name_dict = {
                    hsd.TEX_COLORMAP_NONE: 'TEX_COLORMAP_NONE',
                    hsd.TEX_COLORMAP_PASS: 'TEX_COLORMAP_PASS',
                    hsd.TEX_COLORMAP_REPLACE: 'TEX_COLORMAP_REPLACE',
                    hsd.TEX_COLORMAP_ALPHA_MASK: 'TEX_COLORMAP_ALPHA_MASK',
                    hsd.TEX_COLORMAP_RGB_MASK: 'TEX_COLORMAP_RGB_MASK',
                    hsd.TEX_COLORMAP_BLEND: 'TEX_COLORMAP_BLEND',
                    hsd.TEX_COLORMAP_ADD: 'TEX_COLORMAP_ADD',
                    hsd.TEX_COLORMAP_SUB: 'TEX_COLORMAP_SUB',
                    hsd.TEX_COLORMAP_MODULATE: 'TEX_COLORMAP_MODULATE'
                    }
                    mix.name = colormap_name_dict[colormap] + ' ' + str(texdesc.blending)
                    ###
                    if not colormap == hsd.TEX_COLORMAP_REPLACE:
                        links.new(last_color, mix.inputs[1])
                        links.new(cur_color, mix.inputs[2])
                    if colormap == hsd.TEX_COLORMAP_ALPHA_MASK:
                        links.new(cur_alpha, mix.inputs[0])
                    elif colormap == hsd.TEX_COLORMAP_RGB_MASK:
                        links.new(cur_color, mix.inputs[0])
                    elif colormap == hsd.TEX_COLORMAP_BLEND:
                        mix.inputs[0].default_value = texdesc.blending
                    elif colormap == hsd.TEX_COLORMAP_REPLACE:
                        links.new(cur_color, mix.inputs[1])
                        mix.inputs[0].default_value = 0.0

                    last_color = mix.outputs[0]
            #do alpha
            alphamap = texdesc.flag & hsd.TEX_ALPHAMAP_MASK
            if not (alphamap == hsd.TEX_ALPHAMAP_NONE or
                    alphamap == hsd.TEX_ALPHAMAP_PASS):
                mix = nodes.new('ShaderNodeMixRGB')
                mix.blend_type = map_alpha_op_dict[alphamap]
                mix.inputs[0].default_value = 1
                ###
                alphamap_name_dict = {
                hsd.TEX_ALPHAMAP_NONE: 'TEX_ALPHAMAP_NONE',
                hsd.TEX_ALPHAMAP_PASS: 'TEX_ALPHAMAP_PASS',
                hsd.TEX_ALPHAMAP_REPLACE: 'TEX_ALPHAMAP_REPLACE',
                hsd.TEX_ALPHAMAP_ALPHA_MASK: 'TEX_ALPHAMAP_ALPHA_MASK',
                hsd.TEX_ALPHAMAP_BLEND: 'TEX_ALPHAMAP_BLEND',
                hsd.TEX_ALPHAMAP_ADD: 'TEX_ALPHAMAP_ADD',
                hsd.TEX_ALPHAMAP_SUB: 'TEX_ALPHAMAP_SUB',
                hsd.TEX_ALPHAMAP_MODULATE: 'TEX_ALPHAMAP_MODULATE'
                }
                mix.name = alphamap_name_dict[alphamap]
                ###
                if not alphamap == hsd.TEX_ALPHAMAP_REPLACE:
                    links.new(last_alpha, mix.inputs[1])
                    links.new(cur_alpha, mix.inputs[2])
                if alphamap == hsd.TEX_ALPHAMAP_ALPHA_MASK:
                    links.new(cur_alpha, mix.inputs[0])
                elif alphamap == hsd.TEX_ALPHAMAP_BLEND:
                    mix.inputs[0].default_value = texdesc.blending
                elif alphamap == hsd.TEX_ALPHAMAP_REPLACE:
                    links.new(cur_alpha, mix.inputs[1])

                last_alpha = mix.outputs[0]

    #final render settings, on the GameCube these would control how the rendered data is written to the EFB (Embedded Frame Buffer)

    alt_blend_mode = 'NOTHING'

    transparent_shader = False
    if mobj.pedesc:
        pedesc = mobj.pedesc
        #PE (Pixel Engine) parameters can be given manually in this struct
        #TODO: implement other custom PE stuff
        #blend mode
        #HSD_StateSetBlendMode    ((GXBlendMode) pe->type,
		#	      (GXBlendFactor) pe->src_factor,
		#	      (GXBlendFactor) pe->dst_factor,
		#	      (GXLogicOp) pe->logic_op);
        if pedesc.type == gx.GX_BM_NONE:
            pass #source data just overwrites EFB data (Opaque)
        elif pedesc.type == gx.GX_BM_BLEND:
            #dst_pix_clr = src_pix_clr * src_factor + dst_pix_clr * dst_factor
            if pedesc.dst_factor == gx.GX_BL_ZERO:
                #destination is completely overwritten
                if pedesc.src_factor == gx.GX_BL_ONE:
                    pass #same as GX_BM_NONE
                elif pedesc.src_factor == gx.GX_BL_ZERO:
                    #destination is set to 0
                    black = nodes.new('ShaderNodeRGB')
                    black.outputs[0].default_value[:] = [0,0,0,1]
                    last_color = black.outputs[0]
                elif pedesc.src_factor == gx.GX_BL_DSTCLR:
                    #multiply src and dst
                    #mat.blend_method = 'MULTIPLY'
                    alt_blend_mode = 'MULTIPLY'
                elif pedesc.src_factor == gx.GX_BL_SRCALPHA:
                    #blend with black by alpha
                    blend = nodes.new('ShaderNodeMixRGB')
                    links.new(last_alpha, blend.inputs[0])
                    blend.inputs[1].default_value = [0,0,0,0xFF]
                    links.new(last_color, blend.inputs[2])
                    last_color = blend.outputs[0]
                elif pedesc.src_factor == gx.INVSRCALPHA:
                    #same as above with inverted alpha
                    blend = nodes.new('ShaderNodeMixRGB')
                    links.new(last_alpha, blend.inputs[0])
                    blend.inputs[2].default_value = [0,0,0,0xFF]
                    links.new(last_color, blend.inputs[1])
                    last_color = blend.outputs[0]
                else:
                    #can't be properly approximated with Eevee or Cycles
                    pass
            elif pedesc.dst_factor == gx.GX_BL_ONE:
                if pedesc.src_factor == gx.GX_BL_ONE:
                    #Add src and dst
                    #mat.blend_method = 'ADD'
                    alt_blend_mode = 'ADD'
                elif pedesc.src_factor == gx.GX_BL_ZERO:
                    #Material is invisible
                    transparent_shader = True
                    mat.blend_method = 'HASHED'
                    invisible = nodes.new('ShaderNodeValue')
                    invisible.outputs[0].default_value = 0
                    last_alpha = invisible.outputs[0]
                elif pedesc.src_factor == gx.GX_BL_SRCALPHA:
                    #add alpha blended color
                    transparent_shader = True
                    #mat.blend_method = 'ADD'
                    alt_blend_mode = 'ADD'
                    #manually blend color
                    blend = nodes.new('ShaderNodeMixRGB')
                    links.new(last_alpha, blend.inputs[0])
                    blend.inputs[1].default_value = [0,0,0,0xFF]
                    links.new(last_color, blend.inputs[2])
                    last_color = blend.outputs[0]
                elif pedesc.src_factor == gx.GX_BL_INVSRCALPHA:
                    #add inverse alpha blended color
                    transparent_shader = True
                    #mat.blend_method = 'ADD'
                    alt_blend_mode = 'ADD'
                    #manually blend color
                    blend = nodes.new('ShaderNodeMixRGB')
                    links.new(last_alpha, blend.inputs[0])
                    blend.inputs[2].default_value = [0,0,0,0xFF]
                    links.new(last_color, blend.inputs[1])
                    last_color = blend.outputs[0]
                else:
                    #can't be properly approximated with Eevee or Cycles
                    pass
            elif (pedesc.dst_factor == gx.GX_BL_INVSRCALPHA and pedesc.src_factor == gx.GX_BL_SRCALPHA):
                #Alpha Blend
                transparent_shader = True
                mat.blend_method = 'HASHED'
            elif (pedesc.dst_factor == gx.GX_BL_SRCALPHA and pedesc.src_factor == gx.GX_BL_INVSRCALPHA):
                #Inverse Alpha Blend
                transparent_shader = True
                mat.blend_method = 'HASHED'
                factor = nodes.new('ShaderNodeMath')
                factor.operation = 'SUBTRACT'
                factor.inputs[0].default_value = 1
                factor.use_clamp = True
                links.new(last_alpha, factor.inputs[1])
                last_alpha = factor.outputs[0]
            else:
                #can't be properly approximated with Eevee or Cycles
                pass
        elif pedesc.type == gx.GX_BM_LOGIC:
            if pedesc.op == gx.GX_LO_CLEAR:
                #destination is set to 0
                black = nodes.new('ShaderNodeRGB')
                black.outputs[0].default_value[:] = [0,0,0,1]
                last_color = black.outputs[0]
            elif pedesc.op == gx.GX_LO_SET:
                #destination is set to 1
                white = nodes.new('ShaderNodeRGB')
                white.outputs[0].default_value[:] = [1,1,1,1]
                last_color = white.outputs[0]
            elif pedesc.op == gx.GX_LO_COPY:
                pass #same as GX_BM_NONE ?
            elif pedesc.op == gx.GX_LO_INVCOPY:
                #invert color ?
                invert = nodes.new('ShaderNodeInvert')
                links.new(last_color, invert.inputs[1])
                last_color = invert.outputs[0]
            elif pedesc.op == gx.GX_LO_NOOP:
                #Material is invisible
                transparent_shader = True
                mat.blend_method = 'HASHED'
                invisible = nodes.new('ShaderNodeValue')
                invisible.outputs[0].default_value = 0
                last_alpha = invisible.outputs[0]
            else:
                #can't be properly approximated with Eevee or Cycles
                pass
        elif pedesc.type == gx.GX_BM_SUBTRACT:
            pass #not doable right now
        else:
            error_log('Unknown Blend Mode: %X' % pedesc.type)
    else:
        #TODO:
        #use the presets from the rendermode flags
        if mobj.rendermode & hsd.RENDER_XLU:
            transparent_shader = True
            mat.blend_method = 'HASHED'

    #output shader
    shader = nodes.new('ShaderNodeBsdfPrincipled')
    #specular
    if mobj.rendermode & hsd.RENDER_SPECULAR:
        shader.inputs[5].default_value = mobj.mat.shininess / 50
    else:
        shader.inputs[5].default_value = 0
    #specular tint
    shader.inputs[6].default_value = .5
    #roughness
    shader.inputs[7].default_value = .5

    #diffuse color
    links.new(last_color, shader.inputs[0])

    #alpha
    if transparent_shader:
        #
        #alpha_factor = nodes.new('ShaderNodeMath')
        #alpha_factor.operation = 'POWER'
        #alpha_factor.inputs[1].default_value = 3
        #links.new(last_alpha, alpha_factor.inputs[0])
        #last_alpha = alpha_factor.outputs[0]
        #
        links.new(last_alpha, shader.inputs[18])

    #normal
    if last_bump:
        bump = nodes.new('ShaderNodeBump')
        bump.inputs[1].default_value = 1
        links.new(last_bump, bump.inputs[2])
        links.new(bump.outputs[0], shader.inputs[19])

    #Add Additive or multiplicative alpha blending, since these don't have explicit options in 2.81 anymore
    if (alt_blend_mode == 'ADD'):
        mat.blend_method = 'BLEND'
        #using emissive shader, unfortunately this will obviously override all the principled settings
        e = nodes.new('ShaderNodeEmission')
        #is this really right ? comes from blender release notes
        e.inputs[1].default_value = 1.9
        t = nodes.new('ShaderNodeBsdfTransparent')
        add = nodes.new('ShaderNodeAddShader')
        links.new(last_color, e.inputs[0])
        links.new(e.outputs[0], add.inputs[0])
        links.new(t.outputs[0], add.inputs[1])
        shader = add
    elif (alt_blend_mode == 'MULTIPLY'):
        mat.blend_method = 'BLEND'
        #using transparent shader, unfortunately this will obviously override all the principled settings
        t = nodes.new('ShaderNodeBsdfTransparent')
        links.new(last_color, t.inputs[0])
        shader = t

    #output to Material
    links.new(shader.outputs[0], output.inputs[0])

    output.name = 'Rendermode : 0x%X' % mobj.rendermode
    output.name += ' Transparent: ' + ('True' if transparent_shader else 'False')
    output.name += ' Pedesc: ' + (pedesc_type_dict[mobj.pedesc.type] if mobj.pedesc else 'False')
    if mobj.pedesc and mobj.pedesc.type == gx.GX_BM_BLEND:
        output.name += ' ' + pedesc_src_factor_dict[mobj.pedesc.src_factor] + ' ' + pedesc_dst_factor_dict[mobj.pedesc.dst_factor]

    return mat

def make_tev_input(nodes, texture, tev, input, iscolor):
    if iscolor:
        flag = (tev.color_a, tev.color_b, tev.color_c, tev.color_d)[input]
        if not (flag == gx.GX_CC_TEXC or flag == gx.GX_CC_TEXA):
            color = nodes.new('ShaderNodeRGB')
        if flag == gx.GX_CC_ZERO:
            color.outputs[0].default_value = [0.0, 0.0, 0.0, 1]
        elif flag == gx.GX_CC_ONE:
            color.outputs[0].default_value = [1.0, 1.0, 1.0, 1]
        elif flag == gx.GX_CC_HALF:
            color.outputs[0].default_value = [0.5, 0.5, 0.5, 1]
        elif flag == gx.GX_CC_TEXC:
            return texture.outputs[0]
        elif flag == gx.GX_CC_TEXA:
            return texture.outputs[1]
        elif flag == hsd.TOBJ_TEV_CC_KONST_RGB:
            color.outputs[0].default_value = normcolor([tev.konst[0], tev.konst[1], tev.konst[2], 0xFF])
        elif flag == hsd.TOBJ_TEV_CC_KONST_RRR:
            color.outputs[0].default_value = normcolor([tev.konst[0], tev.konst[0], tev.konst[0], 0xFF])
        elif flag == hsd.TOBJ_TEV_CC_KONST_GGG:
            color.outputs[0].default_value = normcolor([tev.konst[1], tev.konst[1], tev.konst[1], 0xFF])
        elif flag == hsd.TOBJ_TEV_CC_KONST_BBB:
            color.outputs[0].default_value = normcolor([tev.konst[2], tev.konst[2], tev.konst[2], 0xFF])
        elif flag == hsd.TOBJ_TEV_CC_KONST_AAA:
            color.outputs[0].default_value = normcolor([tev.konst[3], tev.konst[3], tev.konst[3], 0xFF])
        elif flag == hsd.TOBJ_TEV_CC_TEX0_RGB:
            color.outputs[0].default_value = normcolor([tev.tev0[0], tev.tev0[1], tev.tev0[2], 0xFF])
        elif flag == hsd.TOBJ_TEV_CC_TEX0_AAA:
            color.outputs[0].default_value = normcolor([tev.tev0[3], tev.tev0[3], tev.tev0[3], 0xFF])
        elif flag == hsd.TOBJ_TEV_CC_TEX1_RGB:
            color.outputs[0].default_value = normcolor([tev.tev1[0], tev.tev1[1], tev.tev1[2], 0xFF])
        elif flag == hsd.TOBJ_TEV_CC_TEX1_AAA:
            color.outputs[0].default_value = normcolor([tev.tev1[3], tev.tev1[3], tev.tev1[3], 0xFF])
        else:
            error_output("unknown tev color input: 0x%X" % flag)
            return texture.outputs[0]
        return color.outputs[0]
    else:
        flag = (tev.alpha_a, tev.alpha_b, tev.alpha_c, tev.alpha_d)[input]
        if not (flag == gx.GX_CA_TEXA):
            alpha = nodes.new('ShaderNodeValue')
        if flag == gx.GX_CA_ZERO:
            alpha.outputs[0].default_value = 0.0
        elif flag == gx.GX_CA_TEXA:
            return texture.outputs[1]
        elif flag == hsd.TOBJ_TEV_CA_KONST_R:
            alpha.outputs[0].default_value = normcolor((tev.konst[0], 'R'))
        elif flag == hsd.TOBJ_TEV_CA_KONST_G:
            alpha.outputs[0].default_value = normcolor((tev.konst[1], 'G'))
        elif flag == hsd.TOBJ_TEV_CA_KONST_B:
            alpha.outputs[0].default_value = normcolor((tev.konst[2], 'B'))
        elif flag == hsd.TOBJ_TEV_CA_KONST_A:
            alpha.outputs[0].default_value = normcolor((tev.konst[3], 'A'))
        elif flag == hsd.TOBJ_TEV_CA_TEX0_A:
            alpha.outputs[0].default_value = normcolor((tev.tev0[3], 'A'))
        elif flag == hsd.TOBJ_TEV_CA_TEX1_A:
            alpha.outputs[0].default_value = normcolor((tev.tev1[3], 'A'))
        else:
            error_output("unknown tev alpha input: 0x%X" % flag)
            return texture.outputs[1]
        return alpha.outputs[0]

def make_tev_op(nodes, links, inputs, tev, iscolor):
    scale_dict = {
        gx.GX_CS_SCALE_1: 1,
        gx.GX_CS_SCALE_2: 2,
        gx.GX_CS_SCALE_4: 4,
        gx.GX_CS_DIVIDE_2: 0.5,
    }
    if iscolor:
        if tev.color_op == gx.GX_TEV_ADD or tev.color_op == gx.GX_TEV_SUB:
            last_node = make_tev_op_add_sub(nodes, links, inputs, tev, iscolor)
            if not tev.color_bias == gx.GX_TB_ZERO:
                bias = nodes.new('ShaderNodeMixRGB')
                bias.inputs[0].default_value = 1
                if tev.color_bias == gx.GX_TB_ADDHALF:
                    bias.blend_type = 'ADD'
                else:
                    bias.blend_type = 'SUBTRACT'
                links.new(last_node, bias.inputs[1])
                bias.inputs[2].default_value = [0.5, 0.5, 0.5, 1]
                last_node = bias.outputs[0]

            scale = nodes.new('ShaderNodeMixRGB')
            scale.blend_type = 'MULTIPLY'
            scale.inputs[0].default_value = 1
            if tev.color_clamp == gx.GX_TRUE:
                scale.use_clamp = True
            links.new(last_node, scale.inputs[1])
            scale.inputs[2].default_value = [scale_dict[tev.color_scale]] * 4
            last_node = scale.outputs[0]
        else:
            last_node = make_tev_op_comp(nodes, links, inputs, tev, iscolor)
            if tev.color_clamp == gx.GX_TRUE:
                scale = nodes.new('ShaderNodeMixRGB')
                scale.operation = 'MULTIPLY'
                scale.inputs[0].default_value = 1
                scale.use_clamp = True
                links.new(last_node, scale.inputs[1])
                scale.inputs[2].default_value = [scale_dict[tev.color_scale]] * 4
                last_node = scale.outputs[0]
    else:
        if tev.alpha_op == gx.GX_TEV_ADD or tev.alpha_op == gx.GX_TEV_SUB:
            last_node = make_tev_op_add_sub(nodes, links, inputs, tev, iscolor)
            if not tev.alpha_bias == gx.GX_TB_ZERO:
                bias = nodes.new('ShaderNodeMath')
                bias.operation = 'ADD'
                links.new(last_node, bias.inputs[0])
                if tev.alpha_bias == gx.GX_TB_ADDHALF:
                    bias.inputs[1].default_value = 0.5
                else:
                    bias.inputs[1].default_value = -0.5
                last_node = bias.outputs[0]

            scale = nodes.new('ShaderNodeMath')
            scale.operation = 'MULTIPLY'
            if tev.alpha_clamp == gx.GX_TRUE:
                scale.use_clamp = True
            links.new(last_node, scale.inputs[0])
            scale.inputs[1].default_value = scale_dict[tev.alpha_scale]
            last_node = scale.outputs[0]
        else:
            last_node = make_tev_op_comp(nodes, links, inputs, tev, iscolor)
            if tev.alpha_clamp == gx.GX_TRUE:
                scale = nodes.new('ShaderNodeMath')
                scale.operation = 'MULTIPLY'
                scale.use_clamp = True
                links.new(last_node, scale.inputs[0])
                scale.inputs[1].default_value = 1
                last_node = scale.outputs[0]
    return last_node

def make_tev_op_add_sub(nodes, links, inputs, tev, iscolor):
    if iscolor:
        sub0 = nodes.new('ShaderNodeMixRGB')
        sub0.inputs[0].default_value = 1
        sub0.blend_type = 'SUBTRACT'
        sub0.inputs[1].default_value = [1,1,1,1]
        links.new(inputs[2], sub0.inputs[2])

        mul0 = nodes.new('ShaderNodeMixRGB')
        mul0.inputs[0].default_value = 1
        mul0.blend_type = 'MULTIPLY'
        links.new(inputs[1], mul0.inputs[1])
        links.new(inputs[2], mul0.inputs[2])

        mul1 = nodes.new('ShaderNodeMixRGB')
        mul1.inputs[0].default_value = 1
        mul1.blend_type = 'MULTIPLY'
        links.new(inputs[0], mul1.inputs[1])
        links.new(sub0.outputs[0], mul1.inputs[2])

        add0 = nodes.new('ShaderNodeMixRGB')
        add0.inputs[0].default_value = 1
        add0.blend_type = 'ADD'
        links.new(mul1.outputs[0], add0.inputs[1])
        links.new(mul0.outputs[0], add0.inputs[2])

        if tev.color_op == gx.GX_TEV_ADD:
            #OUT = [3] + ((1.0 - [2])*[0] + [2]*[1])

            add1 = nodes.new('ShaderNodeMixRGB')
            add1.inputs[0].default_value = 1
            add1.blend_type = 'ADD'
            links.new(inputs[3], add1.inputs[1])
            links.new(add0.outputs[0], add1.inputs[2])

            return add1.outputs[0]
        else: # GX_TEV_SUB
            #OUT = [3] - ((1.0 - [2])*[0] + [2]*[1])

            sub1 = nodes.new('ShaderNodeMixRGB')
            sub1.inputs[0].default_value = 1
            sub1.blend_type = 'SUBTRACT'
            links.new(inputs[3], sub1.inputs[1])
            links.new(add0.outputs[0], sub1.inputs[2])

            return sub1.outputs[0]

    else:
        sub0 = nodes.new('ShaderNodeMath')
        sub0.operation = 'SUBTRACT'
        sub0.inputs[1].default_value = 1.0
        links.new(inputs[2], sub0.inputs[2])

        mul0 = nodes.new('ShaderNodeMath')
        mul0.operation = 'MULTIPLY'
        links.new(inputs[1], mul0.inputs[1])
        links.new(inputs[2], mul0.inputs[2])

        mul1 = nodes.new('ShaderNodeMath')
        mul1.operation = 'MULTIPLY'
        links.new(inputs[0], mul1.inputs[1])
        links.new(sub0.outputs[0], mul1.inputs[2])

        add0 = nodes.new('ShaderNodeMath')
        add0.operation = 'ADD'
        links.new(mul1.outputs[0], add0.inputs[1])
        links.new(mul0.outputs[0], add0.inputs[2])

        if tev.alpha_op == gx.GX_TEV_ADD:
            #OUT = [3] + ((1.0 - [2])*[0] + [2]*[1])

            add1 = nodes.new('ShaderNodeMath')
            add1.operation = 'ADD'
            links.new(inputs[3], add1.inputs[1])
            links.new(add0.outputs[0], add1.inputs[2])

            return add1.outputs[0]
        else: # GX_TEV_SUB
            #OUT = [3] - ((1.0 - [2])*[0] + [2]*[1])

            sub1 = nodes.new('ShaderNodeMath')
            sub1.operation = 'SUBTRACT'
            links.new(inputs[3], sub1.inputs[1])
            links.new(add0.outputs[0], sub1.inputs[2])

            return sub1.outputs[0]


def make_tev_op_comp(nodes, links, inputs, tev, iscolor):
    #TODO:
    return inputs[0]
    pass

pedesc_src_factor_dict = {
gx.GX_BL_ZERO        : 'GX_BL_ZERO',
gx.GX_BL_ONE         : 'GX_BL_ONE',
gx.GX_BL_DSTCLR      : 'GX_BL_DSTCLR',
gx.GX_BL_INVDSTCLR   : 'GX_BL_INVDSTCLR',
gx.GX_BL_SRCALPHA    : 'GX_BL_SRCALPHA',
gx.GX_BL_INVSRCALPHA : 'GX_BL_INVSRCALPHA',
gx.GX_BL_DSTALPHA    : 'GX_BL_DSTALPHA',
gx.GX_BL_INVDSTALPHA : 'GX_BL_INVDSTALPHA',
}

pedesc_dst_factor_dict = {
gx.GX_BL_ZERO        : 'GX_BL_ZERO',
gx.GX_BL_ONE         : 'GX_BL_ONE',
gx.GX_BL_SRCCLR      : 'GX_BL_SRCCLR',
gx.GX_BL_INVSRCCLR   : 'GX_BL_INVSRCCLR',
gx.GX_BL_SRCALPHA    : 'GX_BL_SRCALPHA',
gx.GX_BL_INVSRCALPHA : 'GX_BL_INVSRCALPHA',
gx.GX_BL_DSTALPHA    : 'GX_BL_DSTALPHA',
gx.GX_BL_INVDSTALPHA : 'GX_BL_INVDSTALPHA',
}

pedesc_type_dict = {
    gx.GX_BM_NONE     : 'GX_BM_NONE',
    gx.GX_BM_BLEND    : 'GX_BM_BLEND',
    gx.GX_BM_LOGIC    : 'GX_BM_LOGIC',
    gx.GX_BM_SUBTRACT : 'GX_BM_SUBTRACT',
}

map_col_op_dict = {
    hsd.TEX_COLORMAP_ALPHA_MASK : 'MIX',
    hsd.TEX_COLORMAP_RGB_MASK   : 'MIX',
    hsd.TEX_COLORMAP_BLEND      : 'MIX',
    hsd.TEX_COLORMAP_MODULATE   : 'MULTIPLY',
    hsd.TEX_COLORMAP_REPLACE    : 'ADD',
    hsd.TEX_COLORMAP_ADD        : 'ADD',
    hsd.TEX_COLORMAP_SUB        : 'SUBTRACT',
}
map_alpha_op_dict = {
    hsd.TEX_ALPHAMAP_ALPHA_MASK : 'MIX',
    hsd.TEX_ALPHAMAP_BLEND      : 'MIX',
    hsd.TEX_ALPHAMAP_MODULATE   : 'MULTIPLY',
    hsd.TEX_ALPHAMAP_REPLACE    : 'ADD',
    hsd.TEX_ALPHAMAP_ADD        : 'ADD',
    hsd.TEX_ALPHAMAP_SUB        : 'SUBTRACT',
}


def load_light(light):
    global light_count
    name = ''
    if light.name:
        name = 'Light_' + light.name
    else:
        name = 'Light' + str(light_count)

    type = light.flags & hsd.LOBJ_TYPE_MASK

    #TODO: replace with background settings or something
    """
    if type == hsd.LOBJ_AMBIENT:
        #I'll have to find some workaround for this
        #this hack works pretty well for now at least
        #add two hemisphere lights in opposite directions and only use diffuse
        lamps = []
        for i in range(2):
            lampdata = bpy.data.lights.new(name = name + 'AMBIENT', type = 'HEMI')
            lampdata.use_specular = False
            lampdata.color = [x / 255 for x in light.lightcolor[:3]]
            lamp = bpy.data.objects.new(name = name, object_data = lampdata)
            if light.pos:
                lamp.matrix_basis = Matrix.Translation(Vector(light.pos.wobjposition))
            lamps.append(lamp)
            bpy.context.scene.collection.objects.link(lamp)

        lamps[1].matrix_basis @= Matrix.Rotation(math.pi, 4, 'X')
        lamps[1].parent = lamps[0]
        return lamps[0]
    """

    if type == hsd.LOBJ_INFINITE:
        lampdata = bpy.data.lights.new(name = name, type = 'SUN')
    elif type == hsd.LOBJ_POINT:
        lampdata = bpy.data.lights.new(name = name, type = 'POINT')
    elif type == hsd.LOBJ_SPOT:
        lampdata = bpy.data.lights.new(name = name, type = 'SPOT')
    else:
        return

    lampdata.color = [x / 255 for x in light.lightcolor[:3]]
    #not supported
    #TODO: do something with nodes?
    """
    if light.flags & hsd.LOBJ_DIFFUSE:
        lampdata.use_diffuse = True
    else:
        lampdata.use_diffuse = False
    if light.flags & hsd.LOBJ_SPECULAR:
        lampdata.use_specular = True
    else:
        lampdata.use_specular = False
    """

    lamp = bpy.data.objects.new(name = name, object_data = lampdata)
    if light.pos:
        #orient light into Y_UP direction
        lamp.matrix_basis = Matrix.Translation(Vector(light.pos.wobjposition)) @ Matrix.Rotation(-math.pi / 2, 4, [1.0,0.0,0.0])

    if light.interest:
        #orient the light
        notice_output('INTEREST: %f %f %f' % tuple(light.interest.wobjposition))
        bpy.ops.object.empty_add(type='PLAIN_AXES', view_align=False)
        target = bpy.context.object
        target.matrix_basis = Matrix.Translation(Vector(light.interest.wobjposition))
        constraint = lamp.constraints.new(type = 'TRACK_TO')
        constraint.target = target
        constraint.track_axis = 'TRACK_Z'
        constraint.up_axis = 'UP_X'
        bpy.ops.object.select_all(action='DESELECT')
        lamp.select = True
        bpy.ops.object.visual_transform_apply()
        bpy.data.objects.remove(target, True)


    bpy.context.scene.collection.objects.link(lamp)
    lamp_obj = lamp

    correct_coordinate_orientation(lamp)

    light_count += 1
    return lamp

def load_model(root_joint, mesh_dict, material_dict):

    #create new armature
    global armature_count
    arm_name = None
    if root_joint.name:
        arm_name = 'Armature_' + root_joint.name
    else:
        arm_name = 'Armature' + str(armature_count)
    arm_data = bpy.data.armatures.new(name = arm_name)
    armature = bpy.data.objects.new(name = arm_name, object_data = arm_data)

    #TODO: Seperate Object hierarchy from armatures via Skeleton flags
    #rotate armature into proper orientation
    #needed due to different coordinate systems
    armature.matrix_basis = Matrix.Translation(Vector((0,0,0)))
    correct_coordinate_orientation(armature)

    #make an instance in the scene
    bpy.context.scene.collection.objects.link(armature)
    arm_object = armature
    arm_object.select_set(True)

    #using the hack the bones will be too small to see otherwise
    global ikhack
    if ikhack:
        arm_data.display_type = 'STICK'

    #add bones
    bpy.context.view_layer.objects.active = armature

    #add bones to armature
    global bone_count
    bone_count = 0
    bones = build_bone_hierarchy(arm_data, root_joint)


    bpy.ops.object.mode_set(mode = 'POSE')
    add_geometry(armature, bones, mesh_dict)
    add_contraints(armature, bones)
    add_instances(armature, bones, mesh_dict)


    bpy.context.view_layer.update()
    bpy.ops.object.mode_set(mode = 'OBJECT')

    armature_count += 1

    return armature


def add_geometry(armature, bones, mesh_dict):
    for hsd_bone in bones:
        #TODO: Find out what to do with particles ?
        if hsd_bone.flags & hsd.JOBJ_INSTANCE:
            #We can't copy objects from other bones here since they may not be parented Yet
            pass
        else:
            if not hsd_bone.flags & (hsd.JOBJ_PTCL | hsd.JOBJ_SPLINE):
                dobj = hsd_bone.u
                while dobj:
                    pobj = dobj.pobj
                    while pobj:
                        mesh = mesh_dict[pobj.id]
                        mesh.parent = armature
                        #apply deformation and rigid transformations temporarily stored in the hsd_mesh
                        #this is done here because the meshes are created before the object hierarchy exists
                        apply_bone_weights(mesh, pobj, hsd_bone, armature)
                        #remove degenerate geometry
                        #most of the time it's generated from tristrips changing orientation (for example in a plane)
                        mesh.data.validate(verbose=False, clean_customdata=False)
                        pobj = pobj.next
                    dobj = dobj.next

def robj_get_by_type(joint, type, subtype):
    robj = joint.robj
    while robj:
        if (robj.flags & 0x80000000):
            if (robj.flags & 0x70000000) == type:
                if not subtype:
                    return robj
                else:
                    if (robj.flags & 0x0FFFFFFF) == subtype:
                        return robj
        robj = robj.next
    return None

def add_contraints(armature, bones):
    for hsd_joint in bones:
        if hsd_joint.flags & hsd.JOBJ_TYPE_MASK == hsd.JOBJ_EFFECTOR:
            if not hsd_joint.temp_parent:
                notice_output("IK Effector has no Parent")
                continue
            if hsd_joint.temp_parent.flags & hsd.JOBJ_TYPE_MASK == hsd.JOBJ_JOINT2:
                chain_length = 3
                pole_data_joint = hsd_joint.temp_parent.temp_parent
            elif hsd_joint.temp_parent.flags & hsd.JOBJ_TYPE_MASK == hsd.JOBJ_JOINT1:
                chain_length = 2
                pole_data_joint = hsd_joint.temp_parent
            target_robj = robj_get_by_type(hsd_joint, 0x10000000, 1)
            poletarget_robj = robj_get_by_type(pole_data_joint, 0x10000000, 0)
            length_robj = robj_get_by_type(hsd_joint.temp_parent, 0x40000000, 0)
            if not length_robj:
                notice_output("No Pole angle and bone length constraint on IK Effector Parent")
                continue
            bone_length = length_robj.val0
            pole_angle = length_robj.val1
            if length_robj.flags & 0x4:
                pole_angle += math.pi #+180°
            #This is a hack needed due to how the IK systems differ
            #May break on models using a different exporter than the one used for XD/Colosseum
            #(Or just some inconveniently placed children)
            effector = armature.data.bones[hsd_joint.temp_name]
            effector_pos = Vector(effector.matrix_local.translation)
            effector_name = effector.name
            bpy.context.view_layer.objects.active = armature
            bpy.ops.object.mode_set(mode = 'EDIT')
            position = Vector(effector.parent.matrix_local.translation)
            direction = Vector(effector.parent.matrix_local.col[0][0:3]).normalized()
            direction *= bone_length * effector.parent.matrix_local.to_scale()[0]
            position += direction
            #XXX contrary to documentation, .translate() doesn't seem to exist on EditBones in 2.81
            #Swap this back when this gets fixed
            #armature.data.edit_bones[effector_name].translate(position - effector_pos)
            headpos = Vector(armature.data.edit_bones[effector_name].head[:]) + (position - effector_pos)
            armature.data.edit_bones[effector_name].head[:] = headpos[:]
            tailpos = Vector(armature.data.edit_bones[effector_name].tail[:]) + (position - effector_pos)
            armature.data.edit_bones[effector_name].tail[:] = tailpos[:]
            #
            """
            true_effector = effector
            distance = abs(effector.head.length - bone_length)
            for child in armature.data.bones[hsd_joint.temp_parent.temp_name].children:
                l = abs(child.head.length - bone_length)
                if l < distance:
                    true_effector = child
                    distance = l
            """
            bpy.ops.object.mode_set(mode = 'POSE')
            #if hsd_joint.temp_parent.flags & hsd.JOBJ_SKELETON:
            #adding the constraint

            c = armature.pose.bones[effector_name].constraints.new(type = 'IK')
            c.chain_count = chain_length
            if target_robj:
                c.target = armature
                c.subtarget = target_robj.u.temp_name
                if poletarget_robj:
                    c.pole_target = armature
                    c.pole_subtarget = poletarget_robj.u.temp_name
                    c.pole_angle = pole_angle
            #else:
            #    notice_output("No Pos constraint RObj on IK Effector")
            #else:
            #    notice_output("Adding IK contraint to Bone without Bone parents has no effect")



def correct_coordinate_orientation(obj):
    #correct orientation due to coordinate system differences
    obj.matrix_basis @= Matrix.Rotation(math.pi / 2, 4, [1.0,0.0,0.0])

def add_instances(armature, bones, mesh_dict):
    #TODO: this is broken, as far as I can tell this should copy hierarchy down from the instanced bone as well
    for bone in bones:
        if bone.flags & hsd.JOBJ_INSTANCE:
            child = bone.child
            dobj = child.u
            while dobj:
                pobj = dobj.pobj
                while pobj:
                    mesh = mesh_dict[pobj.id]
                    copy = mesh.copy()
                    copy.parent = armature
                    #copy.parent_bone = bone.temp_name
                    #correct_coordinate_orientation(copy)
                    copy.matrix_local = bone.temp_matrix
                    bpy.context.scene.collection.objects.link(copy)

                    pobj = pobj.next
                dobj = dobj.next



def make_textures(hsd_textures, texture_dict):
    image_dict = {}
    imported_images_check = {}
    global image_count
    image_count = 0
    image = None
    for hsd_texture in hsd_textures:
        #make sure we don't import images twice
        id = 0
        tlut = 0
        if hsd_texture.imagedesc:
            id = hsd_texture.imagedesc.image_ptr_id
        if hsd_texture.tlutdesc:
            tlut = hsd_texture.tlutdesc.id
        if (id, tlut) in imported_images_check:
            image = imported_images_check[(id, tlut)]
        else:
            image_path = ''
            #TODO: remove support for reading textures from directory
            #image = read_image(image_path)

            import_into_memory = True

            image = img.read_image_from_scene(hsd_texture, image_path, import_into_memory)
            if import_into_memory:
                #make sure the image doesn't unload and is stored in .blend files
                image.pack()
                #setting this before packing erases the image for some reason
                image.alpha_mode = 'CHANNEL_PACKED'

            imported_images_check[(id, tlut)] = image
        image_dict[hsd_texture.id] = image

        image_name = ''
        if hsd_texture.class_name:
            image_name = hsd_texture.class_name
        else:
            image_name = 'image' + '_' + str(image_count)
        tex = bpy.data.textures.new(image_name, type = 'IMAGE')
        tex.image = image
        tex.use_alpha = True
        if hsd_texture.imagedesc.mipmap > 0:
            tex.use_mipmap = True
        if hsd_texture.wrap_s == gx.GX_CLAMP:
            tex.extension = 'EXTEND' #'CLIP'
        elif hsd_texture.wrap_s == gx.GX_REPEAT:
            tex.extension = 'REPEAT'
        else:
            #mirror
            tex.extension = 'EXTEND' #?
            tex.use_mirror_x = True
            if hsd_texture.wrap_t == gx.GX_MIRROR:
                tex.use_mirror_y = True
        tex.repeat_x = hsd_texture.repeat_s
        tex.repeat_y = hsd_texture.repeat_t


        texture_dict[hsd_texture.id] = tex
        image_count += 1
    return image_dict


def read_image(image_path):
    image = None
    #realpath = os.path.expanduser(image_path)
    try:
        image = bpy.data.images.load(image_path, check_existing = True)
        notice_output('Read Image ' + image_path)
    except:
        pass
    return image

def make_mesh(pobj, mesh_dict):
    if not pobj.displist:
        return
    name = ''
    if pobj.name:
        name = pobj.name
    ob = make_mesh_object(pobj, name)



    mesh_dict[pobj.id] = ob
    return ob


def make_material(mobj, texture_dict):
    material = mobj.mat
    mat = bpy.data.materials.new('')

    #TODO: add rendermode flags

    #XXX: Print material flags etc
    print(mat.name)
    notice_output('MOBJ FLAGS:\nrendermode: %.8X' % mobj.rendermode)
    if mobj.pedesc:
        pedesc = mobj.pedesc
        notice_output('PEDESC FLAGS:\nflags: %.2X\nref0: %.2X\nref1: %.2X\ndst_alpha: %.2X\ntype: %.2X\nsrc_factor: %.2X\ndst_factor: %.2X\nlogic_op: %.2X\nz_comp: %.2X\nalpha_comp0: %.2X\nalpha_op: %.2X\nalpha_comp1: %.2X' % \
                       (pedesc.flags, pedesc.ref0, pedesc.ref1, pedesc.dst_alpha, pedesc.type, pedesc.src_factor, pedesc.dst_factor, pedesc.logic_op, pedesc.z_comp, pedesc.alpha_comp0, pedesc.alpha_op, pedesc.alpha_comp1))

    #HSD_RenderDesc currently not supported

    #TODO: This is just an easily breaking hack to emulate ambient material color
    mat.raytrace_mirror.use = True
    mat.raytrace_mirror.reflect_factor = 0.5
    mat.raytrace_mirror.distance = 0.0000000000000000000000000001
    mat.raytrace_mirror.fade_to = 'FADE_TO_SKY'
    mat.mirror_color = [x / 255 for x in material.ambient[:3]]

    mat.use_face_texture = True


    mat.diffuse_color = [x / 255 for x in material.diffuse[:3]]
    mat.diffuse_shader = 'LAMBERT'
    mat.diffuse_intensity = 1
    mat.specular_color = [x / 255 for x in material.specular[:3]]
    mat.specular_shader = 'COOKTORR'
    mat.specular_intensity = material.shininess / 50
    mat.alpha = material.alpha
    mat.alpha *= material.diffuse[3]
    if material.alpha != 1:
        mat.use_transparency = True
        mat.transparency_method = 'Z_TRANSPARENCY'
    mat.ambient = 1
    tobj = mobj.texdesc
    while tobj:
        #XXX: Print tex flags etc

        notice_output('TOBJ FLAGS:\nid: %.8X\nsrc: %.8X\nflag: %.8X' % (tobj.texid, tobj.src, tobj.flag))
        if tobj.tev:
            tev = tobj.tev
            notice_output('TEV FLAGS:\ncolor_op: %.2X\nalpha_op: %.2X\ncolor_bias: %.2X\nalpha_bias: %.2X\n\
                           color_scale: %.2X\nalpha_scale: %.2X\ncolor_clamp: %.2X\nalpha_clamp: %.2X\n\
                           color_a: %.2X color_b: %.2X color_c: %.2X color_d: %.2X\n\
                           alpha_a: %.2X alpha_b: %.2X alpha_c: %.2X alpha_d: %.2X\n\
                           konst: %.2X%.2X%.2X%.2X tev0: %.2X%.2X%.2X%.2X tev1: %.2X%.2X%.2X%.2X\n\
                           active: %.8X' % ((tev.color_op, tev.alpha_op, tev.color_bias, tev.alpha_bias,\
                                            tev.color_scale, tev.alpha_scale, tev.color_clamp, tev.alpha_clamp, \
                                            tev.color_a, tev.color_b, tev.color_c, tev.color_d, \
                                            tev.alpha_a, tev.alpha_b, tev.alpha_c, tev.alpha_d) + \
                                            tuple(tev.konst) + tuple(tev.tev0) + tuple(tev.tev1) + \
                                            (tev.active,)))


        add_texture_image(mat, tobj, texture_dict)
        tobj = tobj.next
    return mat


def add_texture_image(mat, tobj, texture_dict):
    #TODO:

    #mat.use_shadeless = True
    mtex = mat.texture_slots.add()
    mtex.texture = texture_dict[tobj.id]

    coordinates = tobj.flag & hsd.TEX_COORD_MASK
    if coordinates == hsd.TEX_COORD_REFLECTION:
        mtex.texture_coords = 'REFLECTION'
    else:
        #other stuff not supported without nodes
        mtex.texture_coords = 'UV'

    #HSD has two seperate blend modes for color and alpha, we'll just use the color one for most things for now
    colormap = tobj.flag & hsd.TEX_COLORMAP_MASK
    alphamap = tobj.flag & hsd.TEX_ALPHAMAP_MASK
    color_blending = tobj.blending

    #TODO: I'm not sure about these
    if colormap == hsd.TEX_COLORMAP_MODULATE:
        mtex.blend_type = 'MULTIPLY'
    elif colormap == hsd.TEX_COLORMAP_REPLACE:
        mtex.blend_type = 'MIX'
        color_blending = 1.0 #?
    elif colormap == hsd.TEX_COLORMAP_PASS:
        #No idea what the point of pass is
        colormap = hsd.TEX_COLORMAP_NONE
    elif colormap == hsd.TEX_COLORMAP_ADD:
        mtex.blend_type = 'ADD'
    elif colormap == hsd.TEX_COLORMAP_SUB:
        mtex.blend_type = 'SUBSTRACT'
    else:
        mtex.blend_type = 'MIX'

    #the default values for these get in the way
    mtex.use_map_color_diffuse = False
    mtex.use_map_diffuse = False

    if colormap != hsd.TEX_COLORMAP_NONE:
        if tobj.flag & hsd.TEX_LIGHTMAP_DIFFUSE:
            mtex.use_map_color_diffuse = True
            mtex.use_map_diffuse = True
            mtex.diffuse_color_factor = color_blending
            mtex.diffuse_factor = color_blending
        if tobj.flag & hsd.TEX_LIGHTMAP_SPECULAR:
            mtex.use_map_color_spec = True
            mtex.use_map_specular = True
            mtex.specular_color_factor = color_blending
            mtex.specular_factor = color_blending
        if tobj.flag & hsd.TEX_LIGHTMAP_AMBIENT:
            #TODO: Is there a color map for ambient ?
            mtex.use_map_ambient = True
            mtex.ambient_factor = color_blending
        if tobj.flag & hsd.TEX_LIGHTMAP_EXT:
            mtex.use_map_color_reflection = True
            mtex.use_map_reflect = True
            mtex.reflection_color_factor = color_blending
            mtex.reflection_factor = color_blending
    if tobj.flag & hsd.TEX_BUMP:
        mtex.use_map_normal = True
        mtex.bump_method = 'BUMP_MEDIUM_QUALITY' #?
        mtex.bump_objectspace = 'BUMP_VIEWSPACE' #?
        mtex.normal_factor = tobj.blending
    if alphamap != hsd.TEX_ALPHAMAP_NONE and alphamap != hsd.TEX_ALPHAMAP_PASS:
        mtex.use_map_alpha = True
        if alphamap != hsd.TEX_ALPHAMAP_REPLACE:
            mtex.alpha_factor = tobj.blending
        else:
            mtex.alpha_factor = 1.0

    mtex.scale = tobj.scale
    mtex.offset = tobj.translate


    # currently only direct UV coordinates are supported
    mtex.uv_layer = 'uvtex_' + str(tobj.src - gx.GX_TG_TEX0)
    return mat


def make_mesh_object(pobj, name):
    displist = pobj.displist
    vtxdesclist = pobj.vtxdesclist
    displistsize = pobj.displistsize

    print('POBJ FLAGS: %.8X' % pobj.flags)

    i = 0 #index of the vtxdesc that holds vertex position data
    for vtxdesc in vtxdesclist:
        if vtxdesc.attr == gx.GX_VA_POS:
            break
        i += 1
    if not i < len(vtxdesclist):
        error_output("Mesh contains no position information")
        return None
    #vertices, faces = read_geometry(vtxdesclist, displist, i)
    #TODO: move the loop here to avoid redundancy
    sources, facelists, normdicts = read_geometry(vtxdesclist, displist, displistsize)
    vertices = sources[i]
    faces = facelists[i]

    # Create mesh and object
    me = bpy.data.meshes.new(name + 'Mesh')
    ob = bpy.data.objects.new(name, me)
    ob.location = Vector((0,0,0))
    # Link object to scene
    bpy.context.scene.collection.objects.link(ob)

    # Create mesh from given verts, edges, faces. Either edges or
    # faces should be [], or you ask for problems


    me.from_pydata(vertices, [], faces)



    if pobj.u:
        type = pobj.flags & hsd.POBJ_TYPE_MASK
        if type == hsd.POBJ_SHAPEANIM:
            shape_set = pobj.u
            make_shapeset(ob, shape_set, normdicts[i])
            make_rigid_skin(pobj)
        elif type == hsd.POBJ_ENVELOPE:
            envelope_list = pobj.u
            envelope_vtxdesc_idx = -1
            for vtxnum, vtxdesc in enumerate(vtxdesclist):
                if vtxdesc.attr == gx.GX_VA_PNMTXIDX: #?
                    envelope_vtxdesc_idx = vtxnum
            if not envelope_vtxdesc_idx < 0:
                make_deform_skin(pobj, envelope_list, sources[envelope_vtxdesc_idx], facelists[envelope_vtxdesc_idx], faces)
            else:
                error_output('INVALID ENVELOPE: %.8X' % (pobj.id))

        else:
            #skin
            #deprecated, probably still used somewhere though
            joint = pobj.u
            make_skin(pobj, joint)

    else:
        make_rigid_skin(pobj)


    #me.calc_normals()
    print(me.name)
    #print_primitives(pobj.vtxdesclist, pobj.displist, pobj.displistsize)
    pobj.normals = None
    for vtxnum, vtxdesc in enumerate(vtxdesclist):
        if vtxdesc_is_tex(vtxdesc):
            uvlayer = make_texture_layer(me, vtxdesc, sources[vtxnum], facelists[vtxnum])
        elif vtxdesc.attr == gx.GX_VA_NRM or vtxdesc.attr == gx.GX_VA_NBT:
            assign_normals_to_mesh(pobj, me, vtxdesc, sources[vtxnum], facelists[vtxnum])
            me.use_auto_smooth = True
        elif (vtxdesc.attr == gx.GX_VA_CLR0 or
              vtxdesc.attr == gx.GX_VA_CLR1):
            add_color_layer(me, vtxdesc, sources[vtxnum], facelists[vtxnum])

    # Update mesh with new data
    me.update(calc_edges = True, calc_edges_loose = False)
    #remove degenerate faces (These mostly occur due to triangle strips creating invisible faces when changing orientation)

    print_primitives(pobj.vtxdesclist, pobj.displist, pobj.displistsize)

    return ob

def make_deform_skin(pobj, envelope_list, source, faces, g_faces):
    #temporarily store vertex group info in the hsd object
    #envelope indices can only be GX_DIRECT


    indices = {}
    for j, face in enumerate(g_faces):
        for i, vtx in enumerate(face):
            indices[vtx] = source[faces[j][i]] // 3 # see GXPosNrmMtx
    indices = list(indices.items())

    #HSD envelopes do *NOT* correspond to Blender's envelope setting for skinning
    envelopes = []
    for envelope in envelope_list:
        envelopes.append([(entry.weight, entry.joint) for entry in envelope])

    pobj.skin = (indices, envelopes)

def make_skin(pobj, joint):
    pobj.skin = (None, joint.id)

def make_rigid_skin(pobj):
    pobj.skin = (None, None)


def apply_bone_weights(mesh, hsd_mesh, hsd_bone, armature):
    #apply weights now that the bones actually exist

    bpy.context.view_layer.objects.active = mesh

    #TODO: this is inefficient, I should probably sort the vertices by the envelope index beforehand

    if hsd_mesh.skin[0]:
        #envelope
        bpy.ops.object.mode_set(mode = 'EDIT')
        joint_groups = {}
        matrices = []
        envelopes = hsd_mesh.skin[1]
        for envelope in envelopes:
            matrix = Matrix([[0] * 4] * 4)
            coord = envelope_coord_system(hsd_bone)
            if envelope[0][0] == 1.0:
                joint = envelope[0][1]
                if not joint.id in joint_groups:
                    group = mesh.vertex_groups.new(name=joint.temp_name)
                    joint_groups[joint.id] = group
                if coord:
                    matrix = joint.temp_matrix @ get_hsd_invbind(joint)
                else:
                    matrix = joint.temp_matrix
            else:
                for weight, joint in envelope:
                    if not joint.id in joint_groups:
                        group = mesh.vertex_groups.new(name=joint.temp_name)
                        joint_groups[joint.id] = group
                    matrix += (weight * (joint.temp_matrix @ get_hsd_invbind(joint)))
            if coord:
                matrix = matrix @ coord
            matrices.append(matrix)

        bpy.ops.object.mode_set(mode = 'OBJECT')

        indices = hsd_mesh.skin[0]
        for vertex, index in indices:
            mesh.data.vertices[vertex].co = matrices[index] @ mesh.data.vertices[vertex].co
            for weight, joint in envelopes[index]:
                joint_groups[joint.id].add([vertex], weight, 'REPLACE')

        for matrix in matrices:
            print(matrix)

        if hsd_mesh.normals:
            #XXX: Is this actually needed?
            matrix_indices = dict(indices)
            normal_matrices = []
            for matrix in matrices:
                normal_matrix = matrix.to_3x3()
                normal_matrix.invert()
                normal_matrix.transpose()
                normal_matrices.append(normal_matrix.to_4x4())

            for loop in mesh.data.loops:
                hsd_mesh.normals[loop.index] = (normal_matrices[matrix_indices[loop.vertex_index]] @ Vector(hsd_mesh.normals[loop.index])).normalized()[:]
            mesh.data.normals_split_custom_set(hsd_mesh.normals)

    else:
        if hsd_mesh.skin[1]:
            #No idea if this is right, don't have any way to test right now
            matrix = Matrix([[0] * 4] * 4)
            group0 = mesh.vertex_groups.new(name=hsd_bone.temp_name)
            matrix += 0.5 * (hsd_bone.temp_matrix @ get_hsd_invbind(hsd_bone))
            joint = hsd_mesh.skin[1]
            group1 = mesh.vertex_groups.new(name=hsd_bone.temp_name)
            matrix += 0.5 * (joint.temp_matrix @ get_hsd_invbind(hsd_bone))

            mesh.matrix_global = matrix

            group0.add([v.index for v in mesh.data.vertices], 0.5, 'REPLACE')
            group1.add([v.index for v in mesh.data.vertices], 0.5, 'REPLACE')

            if hsd_mesh.normals:
                for loop in mesh.data.loops:
                    matrix = matrix.inverted().transposed()
                    hsd_mesh.normals[loop.index] = (matrix @ Vector(hsd_mesh.normals[loop.index])).normalized()[:]
                mesh.data.normals_split_custom_set(hsd_mesh.normals)

        else:
            mesh.matrix_local = hsd_bone.temp_matrix #* get_hsd_invbind(hsd_bone)
            #TODO: get matrix relative to parent bone and set parent mode to bone
            group = mesh.vertex_groups.new(name=hsd_bone.temp_name)
            group.add([v.index for v in mesh.data.vertices], 1.0, 'REPLACE')
            if hsd_mesh.normals:
                mesh.data.normals_split_custom_set(hsd_mesh.normals)


    mod = mesh.modifiers.new('Skinmod', 'ARMATURE')
    mod.object = armature
    mod.use_bone_envelopes = False
    mod.use_vertex_groups = True



def print_primitives(vtxdesclist, displist, displistsize):
    stride = 0
    for vtxdesc in vtxdesclist:
        stride += get_vtxdesc_element_size(vtxdesc)
        print('INDEX_TYPE: ' + attr_type_dict[vtxdesc.attr_type])
        print('ATTR: ' + attr_dict[vtxdesc.attr])
        cnt = ''
        type = ''
        if vtxdesc.attr == gx.GX_VA_POS:
            cnt = pos_cnt_dict[vtxdesc.comp_cnt]
        elif vtxdesc.attr == gx.GX_VA_NRM or vtxdesc.attr == gx.GX_VA_NBT:
            cnt = nrm_cnt_dict[vtxdesc.comp_cnt]
        elif vtxdesc.attr == gx.GX_VA_CLR0 or vtxdesc.attr == gx.GX_VA_CLR1:
            cnt = clr_cnt_dict[vtxdesc.comp_cnt]
            type = clr_comp_type_dict[vtxdesc.comp_type]
        elif vtxdesc_is_tex(vtxdesc):
            cnt = tex_cnt_dict[vtxdesc.comp_cnt]
        if type == '':
            type = comp_type_dict[vtxdesc.comp_type]
        if not vtxdesc_is_mtx(vtxdesc):
            print('COMP_TYPE: ' + type)
        if cnt != '':
            print('COMP_CNT: ' + cnt)

    c = 0
    opcode = displist[c] & gx.GX_OPCODE_MASK
    size_limit = displistsize * 0x20
    while opcode != gx.GX_NOP and c < size_limit:
        print('PRIMITIVE: ' + op_dict[opcode])
        c += 1
        vtxcount = struct.unpack('>H', displist[c:c + 2])[0]
        c += 2
        c += stride * vtxcount
        opcode = displist[c] & gx.GX_OPCODE_MASK

attr_type_dict = {
    gx.GX_NONE: 'GX_NONE',
    gx.GX_DIRECT: 'GX_DIRECT',
    gx.GX_INDEX8: 'GX_INDEX8',
    gx.GX_INDEX16: 'GX_INDEX16'
}

attr_dict = {
    gx.GX_VA_PNMTXIDX: 'GX_VA_PNMTXIDX',
    gx.GX_VA_TEX0MTXIDX: 'GX_VA_TEX0MTXIDX',
    gx.GX_VA_TEX1MTXIDX: 'GX_VA_TEX1MTXIDX',
    gx.GX_VA_TEX2MTXIDX: 'GX_VA_TEX2MTXIDX',
    gx.GX_VA_TEX3MTXIDX: 'GX_VA_TEX3MTXIDX',
    gx.GX_VA_TEX4MTXIDX: 'GX_VA_TEX4MTXIDX',
    gx.GX_VA_TEX5MTXIDX: 'GX_VA_TEX5MTXIDX',
    gx.GX_VA_TEX6MTXIDX: 'GX_VA_TEX6MTXIDX',
    gx.GX_VA_TEX7MTXIDX: 'GX_VA_TEX7MTXIDX',
    gx.GX_VA_POS: 'GX_VA_POS',
    gx.GX_VA_NRM: 'GX_VA_NRM',
    gx.GX_VA_CLR0: 'GX_VA_CLR0',
    gx.GX_VA_CLR1: 'GX_VA_CLR1',
    gx.GX_VA_TEX0: 'GX_VA_TEX0',
    gx.GX_VA_TEX1: 'GX_VA_TEX1',
    gx.GX_VA_TEX2: 'GX_VA_TEX2',
    gx.GX_VA_TEX3: 'GX_VA_TEX3',
    gx.GX_VA_TEX4: 'GX_VA_TEX4',
    gx.GX_VA_TEX5: 'GX_VA_TEX5',
    gx.GX_VA_TEX6: 'GX_VA_TEX6',
    gx.GX_VA_TEX7: 'GX_VA_TEX7',
    gx.GX_POS_MTX_ARRAY: 'GX_POS_MTX_ARRAY',
    gx.GX_NRM_MTX_ARRAY: 'GX_NRM_MTX_ARRAY',
    gx.GX_TEX_MTX_ARRAY: 'GX_TEX_MTX_ARRAY',
    gx.GX_LIGHT_ARRAY: 'GX_LIGHT_ARRAY',
    gx.GX_VA_NBT: 'GX_VA_NBT',
    gx.GX_VA_MAX_ATTR: 'GX_VA_MAX_ATTR',
    gx.GX_VA_NULL: 'GX_VA_NULL'
}

comp_type_dict = {
    gx.GX_U8: 'GX_U8',
    gx.GX_S8: 'GX_S8',
    gx.GX_U16: 'GX_U16',
    gx.GX_S16: 'GX_S16',
    gx.GX_F32: 'GX_F32'
}

clr_comp_type_dict = {
    gx.GX_RGB565: 'GX_RGB565',
    gx.GX_RGB8: 'GX_RGB8',
    gx.GX_RGBX8: 'GX_RGBX8',
    gx.GX_RGBA4: 'GX_RGBA4',
    gx.GX_RGBA6: 'GX_RGBA6',
    gx.GX_RGBA8: 'GX_RGBA8'
}

pos_cnt_dict = {
    gx.GX_POS_XY: 'GX_POS_XY',
    gx.GX_POS_XYZ: 'GX_POS_XYZ'
}
nrm_cnt_dict = {
    gx.GX_NRM_XYZ: 'GX_NRM_XYZ',
    gx.GX_NRM_NBT: 'GX_NRM_NBT',
    gx.GX_NRM_NBT3: 'GX_NRM_NBT3'
}
clr_cnt_dict = {
    gx.GX_CLR_RGB: 'GX_CLR_RGB',
    gx.GX_CLR_RGBA: 'GX_CLR_RGBA'
}
tex_cnt_dict = {
    gx.GX_TEX_S: 'GX_TEX_S',
    gx.GX_TEX_ST: 'GX_TEX_ST'
}

op_dict = {
    gx.GX_NOP: 'GX_NOP',
    gx.GX_DRAW_QUADS: 'GX_DRAW_QUADS',
    gx.GX_DRAW_TRIANGLES: 'GX_DRAW_TRIANGLES',
    gx.GX_DRAW_TRIANGLE_STRIP: 'GX_DRAW_TRIANGLE_STRIP',
    gx.GX_DRAW_TRIANGLE_FAN: 'GX_DRAW_TRIANGLE_FAN',
    gx.GX_DRAW_LINES: 'GX_DRAW_LINES',
    gx.GX_DRAW_LINE_STRIP: 'GX_DRAW_LINE_STRIP',
    gx.GX_DRAW_POINTS: 'GX_DRAW_POINTS',
}

def make_shapeset(ob, shape_set, normdict):
    #ob.shape_key_add(from_mix = False)
    #TODO: implement normals
    for i in range(shape_set.nb_shape + 1):
        shapekey = ob.shape_key_add(from_mix = False)
        source = shape_set.vertex_desc.base_ptr
        descfmt = get_vtxdesc_element_direct_fmt(shape_set.vertex_desc)
        descsize = struct.calcsize(descfmt)

        indexfmt = get_vtxdesc_element_fmt(shape_set.vertex_desc)
        indexsize = struct.calcsize(indexfmt)

        for j in range(shape_set.nb_vertex_index):
            #Dunno if this works for meshes with normalized vertex indices
            index = struct.unpack(indexfmt, shape_set.vertex_idx_list[i][j * indexsize:(j + 1) * indexsize])[0]
            pos = shape_set.vertex_desc.stride * index
            value = struct.unpack(descfmt, source[pos:pos + descsize])
            value = list(value)
            shapekey.data[normdict[j]].co = value

def assign_normals_to_mesh(pobj, meshdata, vtxdesc, source, faces):
    #temporarily store normals in pobj to then be applied when bone deformations are done
    normals = [None] * len(meshdata.loops)
    for polygon in meshdata.polygons:
        face = faces[polygon.index]
        range = polygon.loop_indices
        minr = min(range)

        if vtxdesc.attr == gx.GX_VA_NBT:
            for i in range:
                normals[i] = source[face[i - minr]][0:3]
        else:
            for i in range:
                normals[i] = source[face[i - minr]]
    pobj.normals = normals

def add_color_layer(meshdata, vtxdesc, source, faces):
    if vtxdesc.attr == gx.GX_VA_CLR0:
        color_num = '0'
    elif vtxdesc.attr == gx.GX_VA_CLR1:
        color_num = '1'
    color_layer = meshdata.vertex_colors.new(name = 'color_' + color_num)
    alpha_layer = meshdata.vertex_colors.new(name = 'alpha_' + color_num)
    for polygon in meshdata.polygons:
        face = faces[polygon.index]
        range = polygon.loop_indices
        minr = min(range)

        for i in range:
            color = source[face[i - minr]]
            color = interpret_color(vtxdesc, color)
            color_layer.data[i].color[0:3] = color[0:3]
            alpha_layer.data[i].color[0:3] = [color[3]] * 3

#convert srgb colors to linear color space
#blender does this for images but it assumes raw color inputs are already linear so we need to do the conversion
def tolin(color):
    new_color = []
    for C in color[0:3]:
        if(C <= 0.0404482362771082):
            lin = C/12.92
        else:
            lin = pow(((C+0.055)/1.055), 2.4)
        new_color.append(lin)
    if len(color) > 3:
        new_color.append(color[3])
    return tuple(new_color)


def interpret_color(vtxdesc, raw_color):
    color = [0] * 4
    if vtxdesc.comp_type == gx.GX_RGB565:
        color[0] = (raw_color[0] >> 3) * 0x8
        color[1] = (((raw_color[0] & 0x7) << 3) | (raw_color[1] >> 5)) * 0x4
        color[2] = (raw_color[1] & 0x1F) * 0x8
        color[3] = 0xFF
    elif vtxdesc.comp_type == gx.GX_RGB8:
        color[0] = raw_color[0]
        color[1] = raw_color[1]
        color[2] = raw_color[2]
        color[3] = 0xFF
    elif vtxdesc.comp_type == gx.GX_RGBX8:
        color[0] = raw_color[0]
        color[1] = raw_color[1]
        color[2] = raw_color[2]
        color[3] = 0xFF
    elif vtxdesc.comp_type == gx.GX_RGBA4:
        color[0] = (raw_color[0] >> 4) << 4
        color[1] = (raw_color[0] & 0xF) << 4
        color[2] = (raw_color[1] >> 4) << 4
        color[3] = (raw_color[1] & 0xF) << 4
    elif vtxdesc.comp_type == gx.GX_RGBA6:
        color[0] = (raw_color[0] >> 2) << 2
        color[1] = ((raw_color[0] & 0x3) << 6) | ((raw_color[1] >> 4) << 2)
        color[2] = ((raw_color[1] & 0xF) << 4) | ((raw_color[2] >> 6) << 2)
        color[3] = (raw_color[2] & 0x3F) << 2
    elif vtxdesc.comp_type == gx.GX_RGBA8:
        color[0] = raw_color[0]
        color[1] = raw_color[1]
        color[2] = raw_color[2]
        color[3] = raw_color[3]
    color = [x / 255 for x in color]
    if vtxdesc.comp_cnt == gx.GX_CLR_RGB:
        color[3] = 1
    return tolin(color)

def make_texture_layer(meshdata, vtxdesc, source, faces):
    uvtex = meshdata.uv_layers.new()
    uvtex.name = 'uvtex_' + str(vtxdesc.attr - gx.GX_VA_TEX0)
    uvlayer = meshdata.uv_layers[uvtex.name]
    for polygon in meshdata.polygons:
        face = faces[polygon.index]
        range = polygon.loop_indices
        minr = min(range)

        for i in range:
            coords = source[face[i - minr]]
            #blender's UV coordinate origin is in the bottom left for some reason
            uvlayer.data[i].uv = [coords[0], 1 - coords[1]]
    return uvtex

def get_hsd_invbind(hsd_joint):
    identity = Matrix()
    identity.identity()
    if hsd_joint.invbind:
        return Matrix(hsd_joint.invbind)
    else:
        if hsd_joint.temp_parent:
            return get_hsd_invbind(hsd_joint.temp_parent)
        else:
            return identity


#This is needed for correctly applying all this envelope stuff
def envelope_coord_system(hsd_joint):
    #r: Root
    #x: First parent bone
    #m: Referenced joint
    if hsd_joint.flags & hsd.JOBJ_SKELETON_ROOT: # r == x == m
        return None
    else:
        #find first parent bone
        hsd_x = find_skeleton(hsd_joint)
        x_inverse = get_hsd_invbind(hsd_joint)
        if hsd_x.id == hsd_joint.id: # r != x == m
            return x_inverse.inverted()
        elif hsd_x.flags & hsd.JOBJ_SKELETON_ROOT: # r == x != m
            return (hsd_x.temp_matrix).inverted() @ hsd_joint.temp_matrix
        else: # r != x != m
            return (hsd_x.temp_matrix @ x_inverse).inverted() @ hsd_joint.temp_matrix

def find_skeleton(hsd_joint):
    while hsd_joint:
        if hsd_joint.flags & (hsd.JOBJ_SKELETON_ROOT|hsd.JOBJ_SKELETON):
            return hsd_joint
        hsd_joint = hsd_joint.temp_parent
    return None


def read_geometry(vtxdesclist, displist, displistsize, normalize_indices = True):
    #TODO: remove normalize_indices option: should always be normalized
    descfmts = []
    descsizes = []
    normdicts= []
    stride = 0
    for vtxdesc in vtxdesclist:
        fmt = get_vtxdesc_element_fmt(vtxdesc)
        descfmts.append(fmt)
        size = struct.calcsize(fmt)
        descsizes.append(size)
        stride += size
    #comp_frac = vtxdesc.comp_frac
    #TODO: add comp_frac to direct values

    sources = []
    facelists = []
    offset = 0
    for vtxnum, vtxdesc in enumerate(vtxdesclist):
        faces = []
        norm_dict = {}
        norm_index = 0
        c = 0
        opcode = displist[c] & gx.GX_OPCODE_MASK
        #On the console the displaylist would be copied in a chunk, limit reading to that area
        size_limit = displistsize * 0x20
        while opcode != gx.GX_NOP and c < size_limit:
            c += 1
            vtxcount = struct.unpack('>H', displist[c:c + 2])[0]
            c += 2

            indices = []
            for i in range(vtxcount):
                index = struct.unpack(descfmts[vtxnum], displist[c + offset:c + offset + descsizes[vtxnum]])
                if not len(index) > 1:
                    index = index[0]
                else:
                    index = list(index)
                indices.append(index)
                c += stride

            if normalize_indices and not vtxdesc.attr_type == gx.GX_DIRECT:
                i = 0
                for index in indices:
                    if not index in norm_dict.keys():
                        norm_dict[index] = norm_index
                        norm_index += 1
                    indices[i] = norm_dict[index]
                    i += 1

            if opcode == gx.GX_DRAW_QUADS:
                for i in range(vtxcount // 4):
                    idx = i * 4
                    face = [indices[idx + 3],
                            indices[idx + 2],
                            indices[idx + 1],
                            indices[idx + 0]]
                    faces.append(face)
            elif opcode == gx.GX_DRAW_TRIANGLES:
                for i in range(vtxcount // 3):
                    idx = i * 3
                    face = [indices[idx + 0],
                            indices[idx + 2],
                            indices[idx + 1]]
                    faces.append(face)
            elif opcode == gx.GX_DRAW_TRIANGLE_STRIP:
                for i in range(vtxcount - 2):
                    if i % 2 == 0:
                        face = [indices[i + 1],
                                indices[i + 0],
                                indices[i + 2]]
                    else:
                        face = [indices[i + 0],
                                indices[i + 1],
                                indices[i + 2]]
                    faces.append(face)
            elif opcode == gx.GX_DRAW_TRIANGLE_FAN:
                first_index = indices[0]
                #latest_index = indices[1]
                for i in range(vtxcount - 2):
                    idx = i + 1
                    face = [first_index,
                            indices[idx + 1],
                            indices[idx]]
                    #latest_index = indices[idx]
                    faces.append(face)
            elif opcode == gx.GX_DRAW_LINES:
                notice_output("GX_DRAW_LINES not supported, skipped")
            elif opcode == gx.GX_DRAW_LINE_STRIP:
                notice_output("GX_DRAW_LINE_STRIP not supported, skipped")
            elif opcode == gx.GX_DRAW_POINTS:
                notice_output("GX_DRAW_POINTS not supported, skipped")
            else:
                notice_output("Unsupported geometry primitive, skipped")
            opcode = displist[c] & gx.GX_OPCODE_MASK

        vertices = []
        if vtxdesc.attr_type == gx.GX_DIRECT:
            #this means the indices are actually the raw data they would be indexing
            i = 0
            new_faces = []
            for face in faces:
                new_face = []
                for f in face:
                    vertices.append(f)
                    new_face.append(i)
                    i += 1
                new_faces.append(new_face)
            faces = new_faces
        else:
            if normalize_indices:
                indices = []
                norm_indices = []
                for key, value in norm_dict.items():
                    indices.append(key)
                    norm_indices.append(value)
                indices = [x for _,x in sorted(zip(norm_indices,indices))]
                vertices = read_vertex_data(vtxdesc, indices)
            else:
                #temporary solution
                _, end, _ = get_displaylist_element_bounds(vtxdesclist, displist, vtxnum)
                vertices = read_vertex_data(vtxdesc, [i for i in range(end)])
        sources.append(vertices)
        facelists.append(faces)
        normdicts.append(norm_dict)
        offset += descsizes[vtxnum]

    return sources, facelists, normdicts


def read_vertex_data(vtxdesc, indices):
    #TODO: add support for NBT
    data = []
    base_ptr = vtxdesc.base_ptr
    descfmt = get_vtxdesc_element_direct_fmt(vtxdesc)
    descsize = struct.calcsize(descfmt)
    if vtxdesc.attr == gx.GX_VA_NBT and vtxdesc.comp_cnt == gx.GX_NRM_NBT3:
        #Normal, Binormal and Tangent are individually indexed
        for index in indices:
            value = []
            for i in range(3):
                pos = vtxdesc.stride * index[i] + i * descsize
                value[i*3:i*3+3] = struct.unpack(descfmt, base_ptr[pos:pos + descsize])[0:3]
            if not vtxdesc.attr_type == gx.GX_F32:
                value = [v / (1 << vtxdesc.comp_frac) for v in value]
            else:
                value = list(value)
            data.append(value)
    else:
        for index in indices:
            pos = vtxdesc.stride * index
            value = struct.unpack(descfmt, base_ptr[pos:pos + descsize])
            #print(vtxdesc.attr)
            if not (vtxdesc_is_mtx(vtxdesc) or
                    vtxdesc.attr == gx.GX_VA_CLR0 or
                    vtxdesc.attr == gx.GX_VA_CLR1 or
                    vtxdesc.attr_type == gx.GX_F32):
                if not len(value) > 1:
                    value = value[0] / (1 << vtxdesc.comp_frac)
                else:
                    value = [v / (1 << vtxdesc.comp_frac) for v in value]
            else:
                if not len(value) > 1:
                    value = value[0]
                else:
                    value = list(value)
            data.append(value)
    return data


def get_displaylist_element_bounds(vtxdesclist, displist, i = 0):
    offset = 0
    for vtxdesc in vtxdesclist[0:i]:
        offset += get_vtxdesc_element_size(vtxdesc)
    stride = offset
    for vtxdesc in vtxdesclist[i:]:
        stride += get_vtxdesc_element_size(vtxdesc)
    descfmt = get_vtxdesc_element_fmt(vtxdesclist[i])
    descsize = struct.calcsize(descfmt)
    if vtxdesclist[i].attr_type == gx.GX_DIRECT:
        return 0, 0, 0
    start = 100000
    end = 0
    indices = []

    c = 0
    opcode = displist[c]
    while opcode != gx.GX_NOP:
        c += 1
        vtxcount = struct.unpack('>H', displist[c:c + 2])[0]
        c += 2
        for i in range(vtxcount):
            index = struct.unpack(descfmt, displist[c + offset:c + offset + descsize])[0]
            if not index in indices:
                if index < start:
                    start = index
                if index > end:
                    end = index
                indices.append(index)
            c += stride
        opcode = displist[c]
    return start, end, len(indices)


def get_vtxdesc_element_size(vtxdesc):
    return struct.calcsize(get_vtxdesc_element_fmt(vtxdesc))

def get_vtxdesc_element_fmt(vtxdesc):
    if vtxdesc.attr_type == gx.GX_NONE:
        return 'x'

    if vtxdesc.attr_type == gx.GX_DIRECT:
        return get_vtxdesc_element_direct_fmt(vtxdesc)
    else:
        if vtxdesc.comp_cnt == gx.GX_NRM_NBT3:
            if vtxdesc.attr_type == gx.GX_INDEX8:
                return '>3B'
            else:
                return '>3H'
        if vtxdesc.attr_type == gx.GX_INDEX8:
            return '>B'
        else:
            return '>H'
    return 'x'

def get_vtxdesc_element_direct_fmt(vtxdesc):
    if vtxdesc_is_mtx(vtxdesc):
        return '>B'
    type = ''
    if (vtxdesc.attr == gx.GX_VA_CLR0 or
        vtxdesc.attr == gx.GX_VA_CLR1):
        if vtxdesc.comp_type == gx.GX_RGBA8:
            return '>4B'
        elif vtxdesc.comp_type == gx.GX_RGBA6:
            return '>3B'
        elif vtxdesc.comp_type == gx.GX_RGBA4:
            return '>2B'
        elif vtxdesc.comp_type == gx.GX_RGBX8:
            return '>4B'
        elif vtxdesc.comp_type == gx.GX_RGB8:
            return '>3B'
        else:
            return '>2B'
    else:
        if vtxdesc.comp_type == gx.GX_F32:
            type = 'f'
        elif vtxdesc.comp_type == gx.GX_S16:
            type = 'h'
        elif vtxdesc.comp_type == gx.GX_U16:
            type = 'H'
        elif vtxdesc.comp_type == gx.GX_S8:
            type = 'b'
        else:
            type = 'B'
    if vtxdesc.attr == gx.GX_VA_POS:
        if vtxdesc.comp_cnt == gx.GX_POS_XY:
            return '>' + type * 2
        else:
            return '>' + type * 3
    elif vtxdesc.attr == gx.GX_VA_NRM:
        #gx.GX_NRM_XYZ:
        return '>' + type * 3
    elif vtxdesc_is_tex(vtxdesc):
        if vtxdesc.comp_cnt == gx.GX_TEX_S:
            return '>' + type
        else:
            return '>' + type * 2
    elif vtxdesc.attr == gx.GX_VA_NBT:
        if vtxdesc.comp_cnt == gx.GX_NRM_NBT3:
            return '>' + type * 3
        else:
            return '>' + type * 9
    notice_output("Unsupported Attribute, probably Array")
    return 'x'

def vtxdesc_is_mtx(vtxdesc):
    return (vtxdesc.attr == gx.GX_VA_PNMTXIDX or
            vtxdesc.attr == gx.GX_VA_TEX0MTXIDX or
            vtxdesc.attr == gx.GX_VA_TEX1MTXIDX or
            vtxdesc.attr == gx.GX_VA_TEX2MTXIDX or
            vtxdesc.attr == gx.GX_VA_TEX3MTXIDX or
            vtxdesc.attr == gx.GX_VA_TEX4MTXIDX or
            vtxdesc.attr == gx.GX_VA_TEX5MTXIDX or
            vtxdesc.attr == gx.GX_VA_TEX6MTXIDX or
            vtxdesc.attr == gx.GX_VA_TEX7MTXIDX)

def vtxdesc_is_tex(vtxdesc):
    return (vtxdesc.attr == gx.GX_VA_TEX0 or
            vtxdesc.attr == gx.GX_VA_TEX1 or
            vtxdesc.attr == gx.GX_VA_TEX2 or
            vtxdesc.attr == gx.GX_VA_TEX3 or
            vtxdesc.attr == gx.GX_VA_TEX4 or
            vtxdesc.attr == gx.GX_VA_TEX5 or
            vtxdesc.attr == gx.GX_VA_TEX6 or
            vtxdesc.attr == gx.GX_VA_TEX7)

def build_bone_hierarchy(arm_data, root_joint):

    return create_bone_rec(arm_data, root_joint, None, None, False)



def create_bone_rec(arm_data, hsd_bone, parent, hsd_parent, copy):
    bones = []
    global bone_count
    global ikhack
    bpy.ops.object.mode_set(mode = 'EDIT')
    name = None

    name = 'Bone' + str(bone_count)
    notice_output('BONE: %d SCALE: %f %f %f ROTATION: %f %f %f TRANSLATION: %f %f %f FLAGS: %.8X' % (\
    bone_count, hsd_bone.scale[0], hsd_bone.scale[1], hsd_bone.scale[2], hsd_bone.rotation[0], hsd_bone.rotation[1], hsd_bone.rotation[2], \
    hsd_bone.position[0], hsd_bone.position[1], hsd_bone.position[2], hsd_bone.flags))

    if hsd_bone.flags & hsd.JOBJ_PTCL:
        print('JOBJ_PTCL ' + str(bone_count))
        print('Address: %.8X' % hsd_bone.id)
    if hsd_bone.flags & hsd.JOBJ_SPLINE:
        print('JOBJ_SPLINE ' + str(bone_count))
        print('Address: %.8X' % hsd_bone.id)
        # s0{ u8 flags?; u8; u8; u8 n; f32; * s1; f32; * s2; * s3; }
        """
        spline = hsd_bone.u
        print('Flags: %.4X' % spline.flags)
        print('N: %.4X' % spline.n)
        print('Float 0: %.8f' % spline.f0)
        print('S1: %s' % (spline.s1 != None))
        if spline.s1:
            print('\n'.join([str(x) for x in spline.s1]))
        print('Float 1: %.8f' % spline.f1)
        print('S2: %s' % (spline.s2 != None))
        if spline.s2:
            print('\n'.join([str(x) for x in spline.s2]))
        print('S3: %s' % (spline.s3 != None))
        if spline.s3:
            print('\n'.join([str(x) for x in spline.s3]))
        """

    bone_count += 1
    bone = arm_data.edit_bones.new(name = name)
    if ikhack:
        bone.tail = Vector((0.0, 1e-3, 0.0))
    else:
        bone.tail = Vector((0.0, 1.0, 0.0))
    scale_x = Matrix.Scale(hsd_bone.scale[0], 4, [1.0,0.0,0.0])
    scale_y = Matrix.Scale(hsd_bone.scale[1], 4, [0.0,1.0,0.0])
    scale_z = Matrix.Scale(hsd_bone.scale[2], 4, [0.0,0.0,1.0])
    rotation_x = Matrix.Rotation(hsd_bone.rotation[0], 4, 'X')
    rotation_y = Matrix.Rotation(hsd_bone.rotation[1], 4, 'Y')
    rotation_z = Matrix.Rotation(hsd_bone.rotation[2], 4, 'Z')
    translation = Matrix.Translation(Vector(hsd_bone.position))
    # Parent * T * R * S
    #bone_matrix = translation * rotation_z * rotation_y * rotation_x * scale_z * scale_y * scale_x
    bone_matrix = compileSRTmtx(hsd_bone.scale, hsd_bone.rotation, hsd_bone.position)
    #bone_matrix = Matrix()
    hsd_bone.temp_matrix_local = bone_matrix
    if parent:
        bone_matrix = hsd_parent.temp_matrix @ bone_matrix
        bone.parent = parent
    bone.matrix = bone_matrix
    hsd_bone.temp_matrix = bone_matrix
    hsd_bone.temp_name = bone.name
    hsd_bone.temp_parent = hsd_parent

    #bone.use_relative_parent = True
    if hsd_bone.child and not hsd_bone.flags & hsd.JOBJ_INSTANCE:
        bones += create_bone_rec(arm_data, hsd_bone.child, bone, hsd_bone, copy)
    if hsd_bone.next:
        bones += create_bone_rec(arm_data, hsd_bone.next, parent, hsd_parent, copy)

    bones.append(hsd_bone)
    return bones

def compileSRTmtx(scale, rotation, position):
    scale_x = Matrix.Scale(scale[0], 4, [1.0,0.0,0.0])
    scale_y = Matrix.Scale(scale[1], 4, [0.0,1.0,0.0])
    scale_z = Matrix.Scale(scale[2], 4, [0.0,0.0,1.0])
    rotation_x = Matrix.Rotation(rotation[0], 4, 'X')
    rotation_y = Matrix.Rotation(rotation[1], 4, 'Y')
    rotation_z = Matrix.Rotation(rotation[2], 4, 'Z')
    translation = Matrix.Translation(Vector(position))
    return translation @ rotation_z @ rotation_y @ rotation_x @ scale_z @ scale_y @ scale_x


def load(operator, context, filepath="", offset=0, scene_name='scene_data', data_type='SCENE', import_animation = True, ik_hack = True, max_frame = 1000, use_max_frame = True):
    global ikhack
    ikhack = ik_hack
    global anim_max_frame
    if use_max_frame:
        anim_max_frame = max_frame
    else:
        anim_max_frame = 1000000000
    #bpy.data.scenes[0].render.engine = 'CYCLES'
    return load_hsd(filepath, context, offset, scene_name, data_type, import_animation)

if __name__ == "__main__":
    #load_hsd("./testassets/D1_out#4.fdat")
    load_hsd("./testassets/chopper_0100.fdat")
