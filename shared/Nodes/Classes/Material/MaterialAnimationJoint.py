from ...Node import Node
from ....IO.Logger import NullLogger

# Material Animation Joint
class MaterialAnimationJoint(Node):
    class_name = "Material Animation Joint"
    fields = [
        ('child', 'MaterialAnimationJoint'),
        ('next', 'MaterialAnimationJoint'),
        ('animation', 'MaterialAnimation'),
    ]

    def build(self, joint, action_name_base, builder):
        """
        joint:            the corresponding Joint node
        action_name_base: base name for material actions (e.g. 'model.dat_MatAnim_0')
        builder:          ModelBuilder
        """
        from ..Mesh.Mesh import Mesh
        logger = builder.logger

        bone_name = getattr(joint, 'temp_name', '???')
        logger.debug("MatAnimJoint build: bone=%s has_animation=%s",
                     bone_name, self.animation is not None)

        # Walk MaterialAnimation linked list in parallel with Mesh (DObject) linked list
        if self.animation and joint.property and isinstance(joint.property, Mesh):
            mat_anim = self.animation
            mesh = joint.property
            while mat_anim and mesh:
                if mesh.mobject and hasattr(mesh.mobject, 'blender_material'):
                    mat_anim.build(mesh.mobject, action_name_base, builder)
                else:
                    logger.debug("  MatAnimJoint: skipping mesh 0x%X (no blender_material)",
                                 getattr(mesh, 'address', 0))
                mat_anim = mat_anim.next
                mesh = mesh.next

        # Recurse child/next in parallel with joint tree
        has_anim_child = self.child is not None
        has_joint_child = joint.child is not None
        has_anim_next = self.next is not None
        has_joint_next = joint.next is not None

        if has_anim_child != has_joint_child:
            logger.warning("MatAnimJoint TREE MISMATCH at bone=%s: anim_child=%s joint_child=%s",
                           bone_name, has_anim_child, has_joint_child)
        if has_anim_next != has_joint_next:
            logger.warning("MatAnimJoint TREE MISMATCH at bone=%s: anim_next=%s joint_next=%s",
                           bone_name, has_anim_next, has_joint_next)

        if self.child and joint.child:
            self.child.build(joint.child, action_name_base, builder)
        if self.next and joint.next:
            self.next.build(joint.next, action_name_base, builder)
