from ...Node import Node

# Material Animation Joint
class MaterialAnimationJoint(Node):
    class_name = "Material Animation Joint"
    fields = [
        ('child', 'MaterialAnimationJoint'),
        ('next', 'MaterialAnimationJoint'),
        ('animation', 'MaterialAnimation'),
    ]

    # One MaterialAnimationJoint tree serializes bottom-up by layer: all
    # keyframe/animation data first, then TextureAnimation structs, then
    # MaterialAnimation structs, then the MaterialAnimationJoint structs
    # (pre-order). Verified against game-native PKX.
    serializes_subtree = True

    def serializationOrder(self):
        joints = []

        def visit(j):
            joints.append(j)
            child = getattr(j, 'child', None)
            if isinstance(child, Node):
                visit(child)
            nxt = getattr(j, 'next', None)
            if isinstance(nxt, Node):
                visit(nxt)
        visit(self)

        data, tas, mas = [], [], []

        def add_anim_data(anim):
            if not isinstance(anim, Node):
                return
            frame = getattr(anim, 'frame', None)
            while isinstance(frame, Node):
                data.append(frame)
                frame = getattr(frame, 'next', None)
            data.append(anim)

        for j in joints:
            ma = getattr(j, 'animation', None)
            while isinstance(ma, Node):
                mas.append(ma)
                add_anim_data(getattr(ma, 'animation', None))
                ta = getattr(ma, 'texture_animation', None)
                while isinstance(ta, Node):
                    tas.append(ta)
                    add_anim_data(getattr(ta, 'animation', None))
                    ta = getattr(ta, 'next', None)
                ma = getattr(ma, 'next', None)
        return data + tas + mas + joints

