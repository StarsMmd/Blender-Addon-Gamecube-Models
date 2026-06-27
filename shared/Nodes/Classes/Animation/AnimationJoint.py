from ...Node import Node

# Animation Joint
class AnimationJoint(Node):
    class_name = "Animation Joint"
    fields = [
        ('child', 'AnimationJoint'),
        ('next', 'AnimationJoint'),
        ('animation', 'Animation'),
        ('render_animation', 'RenderAnimation'),
        ('flags', 'uint'),
    ]

    # One AnimationJoint tree (mirroring the skeleton) serializes as: all of
    # the tree's keyframe/animation data first (each animated joint's Frames
    # then its Animation, in pre-order), then all the AnimationJoint structs
    # (pre-order, root first). Verified against game-native PKX.
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

        data = []
        for j in joints:
            anim = getattr(j, 'animation', None)
            if isinstance(anim, Node):
                frame = getattr(anim, 'frame', None)
                while isinstance(frame, Node):
                    data.append(frame)
                    frame = getattr(frame, 'next', None)
                data.append(anim)
        return data + joints
