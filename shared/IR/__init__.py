"""Intermediate Representation dataclasses for the import pipeline."""

from .enums import *
from .scene import IRScene
from .skeleton import IRModel, IRBone
from .geometry import IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights, IRShapeKey
from .material import (
    IRMaterial, IRTextureLayer, IRImage,
    CombinerInput, CombinerStage, ColorCombiner, FragmentBlending,
)
from .animation import (
    IRKeyframe, IRSplinePath, IRBoneAnimationSet, IRBoneTrack,
    IRMaterialTrack, IRTextureUVTrack,
    IRShapeAnimationSet, IRShapeTrack,
)
from .constraints import (
    IRIKConstraint, IRBoneReposition, IRCopyLocationConstraint,
    IRTrackToConstraint, IRCopyRotationConstraint, IRLimitConstraint,
)
from .lights import IRLight
from .camera import IRCamera
from .fog import IRFog
from .particles import IRParticleSystem, IRParticleGenerator, IRParticleTexture
