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

        def anim_data(anim):
            out = []
            if not isinstance(anim, Node):
                return out
            frame = getattr(anim, 'frame', None)
            while isinstance(frame, Node):
                out.append(frame)
                frame = getattr(frame, 'next', None)
            out.append(anim)
            return out

        for j in joints:
            # Per joint: colour-track data follows the material-animation chain
            # in forward order. The texture animations form a separate band,
            # emitted in reverse material-animation order (a later MA's texture
            # animation precedes an earlier one's) while each MA's own
            # texture_animation linked-list stays forward — their data blocks
            # first, then the structs.
            ma_tex_chains = []
            ma = getattr(j, 'animation', None)
            while isinstance(ma, Node):
                mas.append(ma)
                data.extend(anim_data(getattr(ma, 'animation', None)))
                chain = []
                ta = getattr(ma, 'texture_animation', None)
                while isinstance(ta, Node):
                    chain.append(ta)
                    ta = getattr(ta, 'next', None)
                if chain:
                    ma_tex_chains.append(chain)
                ma = getattr(ma, 'next', None)
            for chain in reversed(ma_tex_chains):
                for ta in chain:
                    data.extend(anim_data(getattr(ta, 'animation', None)))
            for chain in reversed(ma_tex_chains):
                tas.extend(chain)
        return data + tas + mas + joints

