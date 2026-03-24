
def get_class_from_name(name):
    # This is a trick to get around circular imports

    from ..Nodes.Classes.Animation import Animation, AnimationJoint, AnimationReference, Frame
    from ..Nodes.Classes.Camera import Camera, CameraAnimation, CameraSet, Viewport
    from ..Nodes.Classes.Colors import Color, RGBAColor, RGB565Color, RGBX8Color, RGB8Color, RGBA4Color, RGBA6Color, RGB5A3Color, \
        I8Color, IA4Color, IA8Color
    from ..Nodes.Classes.Fog import Fog, FogAdj
    from ..Nodes.Classes.Joints import BoneReference, Envelope, EnvelopeList, Reference, Joint, ModelSet
    from ..Nodes.Classes.Light import Attn, Light, LightAnimation, LightSet, PointLight, SpotLight
    from ..Nodes.Classes.Material import Material, MaterialAnimation, MaterialAnimationJoint, MaterialObject
    from ..Nodes.Classes.Mesh import Mesh, PObject, Vertex, VertexList
    from ..Nodes.Classes.Misc import SList, Spline
    from ..Nodes.Classes.Rendering import Particle, PixelEngine, Render, RenderAnimation, WObject, WObjectAnimation
    from ..Nodes.Classes.RootNodes import ArchiveHeader, BoundBox, SceneData, SectionInfo
    from ..Nodes.Classes.Shape import ShapeAnimation, ShapeAnimationJoint, ShapeAnimationMesh, ShapeIndexTri, ShapeSet
    from ..Nodes.Classes.Texture import Image, Palette, Texture, TextureAnimation, TextureLOD, TextureTEV

    CLASS_NAMES = {
        "Animation": Animation,
        "AnimationJoint": AnimationJoint,
        "AnimationReference": AnimationReference,
        "Frame": Frame,
        "Camera": Camera,
        "CameraAnimation": CameraAnimation,
        "CameraSet": CameraSet,
        "Viewport": Viewport,
        "Color": Color,
        "RGBAColor": RGBAColor,
        "RGB565Color": RGB565Color,
        "RGBX8Color": RGBX8Color,
        "RGB8Color": RGB8Color,
        "RGBA4Color": RGBA4Color,
        "RGBA6Color": RGBA6Color,
        "RGB5A3Color": RGB5A3Color,
        "I8Color": I8Color,
        "IA4Color": IA4Color,
        "IA8Color": IA8Color,
        "Fog": Fog,
        "FogAdj": FogAdj,
        "BoneReference": BoneReference,
        "Envelope": Envelope,
        "EnvelopeList": EnvelopeList,
        "Joint": Joint,
        "ModelSet": ModelSet,
        "Reference": Reference,
        "Attn": Attn,
        "Light": Light,
        "LightAnimation": LightAnimation,
        "LightSet": LightSet,
        "PointLight": PointLight,
        "SpotLight": SpotLight,
        "Material": Material,
        "MaterialAnimation": MaterialAnimation,
        "MaterialAnimationJoint": MaterialAnimationJoint,
        "MaterialObject": MaterialObject,
        "Mesh": Mesh,
        "PObject": PObject,
        "Vertex": Vertex,
        "VertexList": VertexList,
        "SList": SList,
        "Spline": Spline,
        "Particle": Particle,
        "PixelEngine": PixelEngine,
        "Render": Render,
        "RenderAnimation": RenderAnimation,
        "WObject": WObject,
        "WObjectAnimation": WObjectAnimation,
        "ArchiveHeader": ArchiveHeader,
        "BoundBox": BoundBox,
        "SceneData": SceneData,
        "SectionInfo": SectionInfo,
        "ShapeAnimation": ShapeAnimation,
        "ShapeAnimationJoint": ShapeAnimationJoint,
        "ShapeAnimationMesh": ShapeAnimationMesh,
        "ShapeIndexTri": ShapeIndexTri,
        "ShapeSet": ShapeSet,
        "Image": Image,
        "Palette": Palette,
        "Texture": Texture,
        "TextureAnimation": TextureAnimation,
        "TextureLOD": TextureLOD,
        "TextureTEV": TextureTEV
    }

    return CLASS_NAMES.get(name)
