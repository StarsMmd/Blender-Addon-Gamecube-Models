import struct
import collections
import gc


if "bpy" in locals():
    import importlib
    if "gx" in locals():
        importlib.reload(gx)
    if "util" in locals():
        importlib.reload(util)

from . import gx, util
"""
import gx, util
"""
#empty object dummy for the HSD structs
class HSD_Object:
    id = 0

#HSD constants
TEX_COORD_UV =                    0
TEX_COORD_REFLECTION =            1
TEX_COORD_HILIGHT =               2
TEX_COORD_SHADOW =                3
TEX_COORD_TOON =                  4
TEX_COORD_GRADATION =             5
TEX_COORD_MASK =                  (0x0f)

TEX_LIGHTMAP_DIFFUSE =            (0x1<<4)
TEX_LIGHTMAP_SPECULAR =           (0x1<<5)
TEX_LIGHTMAP_AMBIENT =            (0x1<<6)
TEX_LIGHTMAP_EXT =                (0x1<<7)
TEX_LIGHTMAP_SHADOW =             (0x1<<8)
TEX_LIGHTMAP_MASK =               (TEX_LIGHTMAP_DIFFUSE | TEX_LIGHTMAP_SPECULAR | TEX_LIGHTMAP_AMBIENT | TEX_LIGHTMAP_EXT | TEX_LIGHTMAP_SHADOW)

TEX_COLORMAP_NONE =               (0<<16)
TEX_COLORMAP_ALPHA_MASK =         (1<<16)
TEX_COLORMAP_RGB_MASK =           (2<<16)
TEX_COLORMAP_BLEND =              (3<<16)
TEX_COLORMAP_MODULATE =           (4<<16)
TEX_COLORMAP_REPLACE =            (5<<16)
TEX_COLORMAP_PASS =               (6<<16)
TEX_COLORMAP_ADD =                (7<<16)
TEX_COLORMAP_SUB =                (8<<16)
TEX_COLORMAP_MASK =               (0x0f<<16)

TEX_ALPHAMAP_NONE =               (0<<20)
TEX_ALPHAMAP_ALPHA_MASK =         (1<<20)
TEX_ALPHAMAP_BLEND =              (2<<20)
TEX_ALPHAMAP_MODULATE =           (3<<20)
TEX_ALPHAMAP_REPLACE =            (4<<20)
TEX_ALPHAMAP_PASS =               (5<<20)
TEX_ALPHAMAP_ADD =                (6<<20)
TEX_ALPHAMAP_SUB =                (7<<20)
TEX_ALPHAMAP_MASK =               (0x0f<<20)

TEX_BUMP =                        (0x1<<24)
TEX_MTX_DIRTY =                   (1<<31)

RENDER_CONSTANT =				  (1<<0)
RENDER_VERTEX =					  (1<<1)

RENDER_DIFFUSE_BITS =			  (3<<0)
RENDER_DIFFUSE_SHIFT =			  0
RENDER_DIFFUSE_MAT0 =			  (0<<0)
RENDER_DIFFUSE_MAT =			  (1<<0)
RENDER_DIFFUSE_VTX =			  (2<<0)
RENDER_DIFFUSE_BOTH =			  (3<<0)
RENDER_DIFFUSE =				  (1<<2)
RENDER_SPECULAR =				  (1<<3)
CHANNEL_FIELD =					  (RENDER_CONSTANT| RENDER_VERTEX  |  RENDER_DIFFUSE | RENDER_SPECULAR)
RENDER_TEX0 =					  (1<<4)
RENDER_TEX1 =					  (1<<5)
RENDER_TEX2 =					  (1<<6)
RENDER_TEX3 =					  (1<<7)
RENDER_TEX4 =					  (1<<8)
RENDER_TEX5 =					  (1<<9)
RENDER_TEX6 =					  (1<<10)
RENDER_TEX7 =					  (1<<11)
RENDER_TEXTURES =				  (RENDER_TEX0|RENDER_TEX1|RENDER_TEX2|RENDER_TEX3|RENDER_TEX4|RENDER_TEX5|RENDER_TEX6|RENDER_TEX7)
RENDER_TOON =					  (1<<12)
RENDER_ALPHA_BITS =			      (3<<13)
RENDER_ALPHA_SHIFT =			  13
RENDER_ALPHA_COMPAT =			  (0<<13)
RENDER_ALPHA_MAT =				  (1<<13)
RENDER_ALPHA_VTX =				  (2<<13)
RENDER_ALPHA_BOTH =				  (3<<13)

RENDER_SHADOW =					  (1<<26)
RENDER_ZMODE_ALWAYS =			  (1<<27)
RENDER_DF_NONE =				  (1<<28)
RENDER_NO_ZUPDATE =				  (1<<29)
RENDER_XLU =					  (1<<30)
RENDER_USER =					  (1<<31)
POBJ_TYPE_MASK =	 			  (3<<12)
POBJ_SKIN =	 					  (0<<12)
POBJ_SHAPEANIM =	 			  (1<<12)
POBJ_ENVELOPE =					  (2<<12)
POBJ_CULLFRONT =				  (1<<14)
POBJ_CULLBACK =					  (1<<15)

HSD_TRSP_OPA =                    1 << 0
HSD_TRSP_XLU =                    1 << 1
HSD_TRSP_TEXEDGE =                1 << 2
HSD_TRSP_ALL =                    HSD_TRSP_OPA|HSD_TRSP_XLU|HSD_TRSP_TEXEDGE

JOBJ_ANIM_CLASSICAL_SCALING =	  0x01

JOBJ_SKELETON =					  (1<<0)
JOBJ_SKELETON_ROOT =			  (1<<1)
JOBJ_ENVELOPE_MODEL =			  (1<<2)
JOBJ_CLASSICAL_SCALING =		  (1<<3)
JOBJ_HIDDEN =					  (1<<4)
JOBJ_PTCL =						  (1<<5)
JOBJ_MTX_DIRTY =				  (1<<6)
JOBJ_LIGHTING =					  (1<<7)
JOBJ_TEXGEN =					  (1<<8)
JOBJ_BILLBOARD_SHIFT =			  (9)
JOBJ_BILLBOARD_FIELD =			  (0x7<<JOBJ_BILLBOARD_SHIFT)
JOBJ_BILLBOARD =				  (0x1<<JOBJ_BILLBOARD_SHIFT)
JOBJ_VBILLBOARD =				  (0x2<<JOBJ_BILLBOARD_SHIFT)
JOBJ_HBILLBOARD =				  (0x3<<JOBJ_BILLBOARD_SHIFT)
JOBJ_RBILLBOARD =				  (0x4<<JOBJ_BILLBOARD_SHIFT)
JOBJ_INSTANCE =					  (1<<12)
JOBJ_PBILLBOARD =				  (1<<13)
JOBJ_SPLINE =					  (1<<14)
JOBJ_FLIP_IK =					  (1<<15)
JOBJ_SPECULAR =					  (1<<16)
JOBJ_USE_QUATERNION =			  (1<<17)

JOBJ_TRSP_SHIFT =				  (18)
JOBJ_OPA =						  (HSD_TRSP_OPA << JOBJ_TRSP_SHIFT)
JOBJ_XLU =						  (HSD_TRSP_XLU << JOBJ_TRSP_SHIFT)
JOBJ_TEXEDGE =					  (HSD_TRSP_TEXEDGE << JOBJ_TRSP_SHIFT)
JOBJ_TRSP_MASK =				  (JOBJ_OPA|JOBJ_XLU|JOBJ_TEXEDGE)
JOBJ_TRSP_ALL =					  JOBJ_TRSP_MASK

JOBJ_TYPE_SHIFT =				  (21)
JOBJ_TYPE_MASK =				  (3 << JOBJ_TYPE_SHIFT)
JOBJ_NULL =						  (0 << JOBJ_TYPE_SHIFT)
JOBJ_JOINT1 =					  (1 << JOBJ_TYPE_SHIFT)
JOBJ_JOINT2 =					  (2 << JOBJ_TYPE_SHIFT)
JOBJ_EFFECTOR =					  (3 << JOBJ_TYPE_SHIFT)


JOBJ_USER_DEFINED_MTX =			  (1<<23)
JOBJ_MTX_INDEPEND_PARENT =		  (1<<24)
JOBJ_MTX_INDEPEND_SRT =			  (1<<25)

JOBJ_ROOT_SHIFT =				  28
JOBJ_ROOT_OPA =					  (HSD_TRSP_OPA << JOBJ_ROOT_SHIFT)
JOBJ_ROOT_XLU =					  (HSD_TRSP_XLU << JOBJ_ROOT_SHIFT)
JOBJ_ROOT_TEXEDGE =				  (HSD_TRSP_TEXEDGE << JOBJ_ROOT_SHIFT)
JOBJ_ROOT_TRSP_MASK =			  (JOBJ_ROOT_OPA|JOBJ_ROOT_XLU|JOBJ_ROOT_TEXEDGE)
JOBJ_ROOT_TRSP_ALL =			  JOBJ_ROOT_TRSP_MASK

JOBJ =							  (1<<31)
JOBJ_SHADOW =					  (1<<31)




COBJ_PROJECTION_PERSPECTIVE =	  (1)
COBJ_PROJECTION_FRUSTUM =		  (2)
COBJ_PROJECTION_ORTHO =			  (3)



LOBJ_AMBIENT =					  (0<<0)
LOBJ_INFINITE =					  (1<<0)
LOBJ_POINT =					  (2<<0)
LOBJ_SPOT =						  (3<<0)
LOBJ_TYPE_MASK =	 			  (LOBJ_AMBIENT|LOBJ_INFINITE|LOBJ_POINT|LOBJ_SPOT)

LOBJ_DIFFUSE =					  (1<<2)
LOBJ_SPECULAR =					  (1<<3)
LOBJ_ALPHA =					  (1<<4)
LOBJ_HIDDEN =					  (1<<5)
LOBJ_RAW_PARAM =				  (1<<6)
LOBJ_DIFF_DIRTY =				  (1<<7)
LOBJ_SPEC_DIRTY =				  (1<<8)


LOBJ_LIGHT_ATTN_NONE =			  (0)
LOBJ_LIGHT_ATTN =				  (1<<0)

HSD_A_J_ROTX =					  (1)
HSD_A_J_ROTY =					  (2)
HSD_A_J_ROTZ =					  (3)
HSD_A_J_PATH =					  (4)
HSD_A_J_TRAX =					  (5)
HSD_A_J_TRAY =					  (6)
HSD_A_J_TRAZ =					  (7)
HSD_A_J_SCAX =					  (8)
HSD_A_J_SCAY =					  (9)
HSD_A_J_SCAZ =					  (10)
HSD_A_J_NODE =					  (11)
HSD_A_J_BRANCH =				  (12)
HSD_A_J_SETBYTE0 =				  (20)
HSD_A_J_SETBYTE1 =				  (HSD_A_J_SETBYTE0+1)
HSD_A_J_SETBYTE2 =				  (HSD_A_J_SETBYTE0+2)
HSD_A_J_SETBYTE3 =				  (HSD_A_J_SETBYTE0+3)
HSD_A_J_SETBYTE4 =				  (HSD_A_J_SETBYTE0+4)
HSD_A_J_SETBYTE5 =				  (HSD_A_J_SETBYTE0+5)
HSD_A_J_SETBYTE6 =				  (HSD_A_J_SETBYTE0+6)
HSD_A_J_SETBYTE7 =				  (HSD_A_J_SETBYTE0+7)
HSD_A_J_SETBYTE8 =				  (HSD_A_J_SETBYTE0+8)
HSD_A_J_SETBYTE9 =				  (HSD_A_J_SETBYTE0+9)
HSD_A_J_SETFLOAT0 =				  (30)
HSD_A_J_SETFLOAT1 =				  (HSD_A_J_SETFLOAT0+1)
HSD_A_J_SETFLOAT2 =				  (HSD_A_J_SETFLOAT0+2)
HSD_A_J_SETFLOAT3 =				  (HSD_A_J_SETFLOAT0+3)
HSD_A_J_SETFLOAT4 =				  (HSD_A_J_SETFLOAT0+4)
HSD_A_J_SETFLOAT5 =				  (HSD_A_J_SETFLOAT0+5)
HSD_A_J_SETFLOAT6 =				  (HSD_A_J_SETFLOAT0+6)
HSD_A_J_SETFLOAT7 =				  (HSD_A_J_SETFLOAT0+7)
HSD_A_J_SETFLOAT8 =				  (HSD_A_J_SETFLOAT0+8)
HSD_A_J_SETFLOAT9 =				  (HSD_A_J_SETFLOAT0+9)

AOBJ_NO_ANIM =					  (1<<30)
AOBJ_ANIM_LOOP =				  (1<<29)
AOBJ_NO_UPDATE =				  (1<<28)
AOBJ_FIRST_PLAY =				  (1<<27)
AOBJ_ANIM_REWINDED =			  (1<<26)

HSD_A_OP_MASK =					  (0xf)
HSD_A_OP_SHIFT =				  (0)
HSD_A_PACK0_MASK =				  (0x70)
HSD_A_PACK0_SHIFT =				  (4)
HSD_A_PACK0_BIT =				  (3)
HSD_A_PACK_EXT =				  (0x80)
HSD_A_PACK1_MASK =				  (0x7f)
HSD_A_PACK1_BIT =				  (7)
HSD_A_PACK1_SHIFT =				  (0)

HSD_A_WAIT_MASK =				  (0x7f)
HSD_A_WAIT_SHIFT =				  (0)
HSD_A_WAIT_BIT =				  (7)
HSD_A_WAIT_EXT =				  (0x80)

HSD_A_OP_NONE =					  (0)
HSD_A_OP_CON =					  (1)
HSD_A_OP_LIN =					  (2)
HSD_A_OP_SPL0 =					  (3)
HSD_A_OP_SPL =					  (4)
HSD_A_OP_SLP =					  (5)
HSD_A_OP_KEY =					  (6)

HSD_A_FRAC_MASK =				  0x1f
HSD_A_FRAC_TYPE_SHIFT =			  5
HSD_A_FRAC_TYPE_MASK =			  (0x7<<HSD_A_FRAC_TYPE_SHIFT)
HSD_A_FRAC_FLOAT =				  (0<<HSD_A_FRAC_TYPE_SHIFT)
HSD_A_FRAC_S16 =				  (1<<HSD_A_FRAC_TYPE_SHIFT)
HSD_A_FRAC_U16 =				  (2<<HSD_A_FRAC_TYPE_SHIFT)
HSD_A_FRAC_S8 =					  (3<<HSD_A_FRAC_TYPE_SHIFT)
HSD_A_FRAC_U8 =					  (4<<HSD_A_FRAC_TYPE_SHIFT)

HSD_A_S_SHAPE =					  (1)
HSD_A_S_W0 =					  (2)
HSD_A_S_W1 =					  (HSD_A_S_W0+ 1)
HSD_A_S_W2 =					  (HSD_A_S_W0+ 2)
HSD_A_S_W3 =					  (HSD_A_S_W0+ 3)
HSD_A_S_W4 =					  (HSD_A_S_W0+ 4)
HSD_A_S_W5 =					  (HSD_A_S_W0+ 5)
HSD_A_S_W6 =					  (HSD_A_S_W0+ 6)
HSD_A_S_W7 =					  (HSD_A_S_W0+ 7)
HSD_A_S_W8 =					  (HSD_A_S_W0+ 8)
HSD_A_S_W9 =					  (HSD_A_S_W0+ 9)
HSD_A_S_W10 =					  (HSD_A_S_W0+10)
HSD_A_S_W11 =					  (HSD_A_S_W0+11)
HSD_A_S_W12 =					  (HSD_A_S_W0+12)
HSD_A_S_W13 =					  (HSD_A_S_W0+13)
HSD_A_S_W14 =					  (HSD_A_S_W0+14)
HSD_A_S_W15 =					  (HSD_A_S_W0+15)

SHAPESET_AVERAGE =	 			  (1<<0)
SHAPESET_ADDITIVE =	 			  (1<<1)
SHAPESET_INTERP_LINERE =	 	  (1<<2)
SHAPESET_INTERP_CARDINAL =		  (1<<3)
SHAPESET_INTERP_WEIGHT =		  (1<<4)


HSD_A_C_EYEX =					  (1)
HSD_A_C_EYEY =					  (2)
HSD_A_C_EYEZ =					  (3)
HSD_A_C_EYEP =					  (4)
HSD_A_C_ATX =	 				  (5)
HSD_A_C_ATY =	 				  (6)
HSD_A_C_ATZ =	 				  (7)
HSD_A_C_ATP =	 				  (8)
HSD_A_C_ROLL =					  (9)
HSD_A_C_FOVY =					  (10)
HSD_A_C_NEAR =					  (11)
HSD_A_C_FAR =					  (12)


HSD_A_W_PATH =					  (4)
HSD_A_W_TRAX =					  (5)
HSD_A_W_TRAY =					  (6)
HSD_A_W_TRAZ =					  (7)

HSD_A_L_LITC_R =				  (9)
HSD_A_L_LITC_G =				  (10)
HSD_A_L_LITC_B =				  (11)
HSD_A_L_LITC_A =				  (22)
HSD_A_L_VIS =	  				  (12)
HSD_A_L_CUTOFF =				  (19)

HSD_A_M_AMBIENT_R =				  (1)
HSD_A_M_AMBIENT_G =				  (2)
HSD_A_M_AMBIENT_B =				  (3)
HSD_A_M_DIFFUSE_R =				  (4)
HSD_A_M_DIFFUSE_G =				  (5)
HSD_A_M_DIFFUSE_B =				  (6)
HSD_A_M_SPECULAR_R =			  (7)
HSD_A_M_SPECULAR_G =			  (8)
HSD_A_M_SPECULAR_B =			  (9)
HSD_A_M_ALPHA =					  (10)

HSD_A_T_TIMG =					  (1)
HSD_A_T_TRAU =					  (2)
HSD_A_T_TRAV =					  (3)
HSD_A_T_SCAU =					  (4)
HSD_A_T_SCAV =					  (5)
HSD_A_T_ROTX =					  (6)
HSD_A_T_ROTY =					  (7)
HSD_A_T_ROTZ =					  (8)
HSD_A_T_BLEND =					  (9)
HSD_A_T_TCLT =					  (10)
HSD_A_T_LOD_BIAS =                11
HSD_A_T_KONST_R =                 12
HSD_A_T_KONST_G =                 13
HSD_A_T_KONST_B =                 14
HSD_A_T_KONST_A =                 15
HSD_A_T_TEV0_R =                  16
HSD_A_T_TEV0_G =                  17
HSD_A_T_TEV0_B =                  18
HSD_A_T_TEV0_A =                  19
HSD_A_T_TEV1_R =                  20
HSD_A_T_TEV1_G =                  21
HSD_A_T_TEV1_B =                  22
HSD_A_T_TEV1_A =                  23
HSD_A_T_TS_BLEND =                24

ENABLE_COLOR_UPDATE =	          (1<<0)
ENABLE_ALPHA_UPDATE =	          (1<<1)
ENABLE_DST_ALPHA =	              (1<<2)
BEFORE_TEX =			          (1<<3)
ENABLE_COMPARE =		          (1<<4)
ENABLE_ZUPDATE =		          (1<<5)
ENABLE_DITHER =		              (1<<6)

#u8 color_a, color_b, color_c, color_d;
TOBJ_TEV_CC_KONST_RGB =           (0x01<<7|0)
TOBJ_TEV_CC_KONST_RRR =           (0x01<<7|1)
TOBJ_TEV_CC_KONST_GGG =           (0x01<<7|2)
TOBJ_TEV_CC_KONST_BBB =           (0x01<<7|3)
TOBJ_TEV_CC_KONST_AAA =           (0x01<<7|4)
TOBJ_TEV_CC_TEX0_RGB =            (0x01<<7|5)
TOBJ_TEV_CC_TEX0_AAA =            (0x01<<7|6)
TOBJ_TEV_CC_TEX1_RGB =            (0x01<<7|7)
TOBJ_TEV_CC_TEX1_AAA =            (0x01<<7|8)

#u8 alpha_a, alpha_b, alpha_c, alpha_d;
TOBJ_TEV_CA_KONST_R =             (0x01<<6|0)
TOBJ_TEV_CA_KONST_G =             (0x01<<6|1)
TOBJ_TEV_CA_KONST_B =             (0x01<<6|2)
TOBJ_TEV_CA_KONST_A =             (0x01<<6|3)
TOBJ_TEV_CA_TEX0_A =              (0x01<<6|4)
TOBJ_TEV_CA_TEX1_A =              (0x01<<6|5)

#u32 active;
TOBJ_TEVREG_ACTIVE_KONST_R = 	  (0x01<<0)
TOBJ_TEVREG_ACTIVE_KONST_G = 	  (0x01<<1)
TOBJ_TEVREG_ACTIVE_KONST_B = 	  (0x01<<2)
TOBJ_TEVREG_ACTIVE_KONST_A = 	  (0x01<<3)
TOBJ_TEVREG_ACTIVE_KONST =        (TOBJ_TEVREG_ACTIVE_KONST_R|TOBJ_TEVREG_ACTIVE_KONST_G|TOBJ_TEVREG_ACTIVE_KONST_B|TOBJ_TEVREG_ACTIVE_KONST_A)
TOBJ_TEVREG_ACTIVE_TEV0_R = 	  (0x01<<4)
TOBJ_TEVREG_ACTIVE_TEV0_G = 	  (0x01<<5)
TOBJ_TEVREG_ACTIVE_TEV0_B = 	  (0x01<<6)
TOBJ_TEVREG_ACTIVE_TEV0_A = 	  (0x01<<7)
TOBJ_TEVREG_ACTIVE_TEV0 =         (TOBJ_TEVREG_ACTIVE_TEV0_R|TOBJ_TEVREG_ACTIVE_TEV0_G|TOBJ_TEVREG_ACTIVE_TEV0_B|TOBJ_TEVREG_ACTIVE_TEV0_A)
TOBJ_TEVREG_ACTIVE_TEV1_R = 	  (0x01<<8)
TOBJ_TEVREG_ACTIVE_TEV1_G = 	  (0x01<<9)
TOBJ_TEVREG_ACTIVE_TEV1_B = 	  (0x01<<10)
TOBJ_TEVREG_ACTIVE_TEV1_A = 	  (0x01<<11)
TOBJ_TEVREG_ACTIVE_TEV1 =         (TOBJ_TEVREG_ACTIVE_TEV1_R|TOBJ_TEVREG_ACTIVE_TEV1_G|TOBJ_TEVREG_ACTIVE_TEV1_B|TOBJ_TEVREG_ACTIVE_TEV1_A)
TOBJ_TEVREG_ACTIVE_COLOR_TEV = 	  (0x01<<30)
TOBJ_TEVREG_ACTIVE_ALPHA_TEV = 	  (0x01<<31)
#end HSD constants


#HSD struct definitions for Python
_HSD_NAMES = (
    'HSD_ArchiveHeader',
    'HSD_ArchiveRelocationInfo',
    'HSD_ArchivePublicInfo',
    'HSD_ArchiveExternInfo',
    'HSD_SceneDesc',
    'HSD_SceneModelSet',
    'HSD_Joint',
    'HSD_DObjDesc',
    'HSD_PObjDesc',
    'HSD_ShapeSetDesc',
    'HSD_ShapeIndex',
    'HSD_EnvelopeDesc',
    'HSD_VtxDescList',
    'HSD_MObjDesc',
    'HSD_PEDesc',
    #'GXColor',
    'HSD_Material',
    'HSD_TObjDesc',
    'HSD_TObjTevDesc',
    'HSD_TexLODDesc',
    'HSD_TlutDesc',
    'HSD_ImageDesc',
    'HSD_SceneCameraSet',
    'HSD_CameraAnim',
    #'Viewport',
    'HSD_CameraDesc',
    'HSD_SceneLightSet',
    'HSD_LightAnim',
    'HSD_WObjAnim',
    'HSD_LightDesc',
    #'HSD_AttnDesc',
    'HSD_SList',
    'HSD_LightPointDesc',
    'HSD_LightSpotDesc',
    'HSD_WObjDesc',
    'HSD_FObjDesc',
    'HSD_AObjDesc',
    'HSD_AnimJoint',
    'HSD_MatAnimJoint',
    'HSD_MatAnim',
    'HSD_TexAnim',
    'HSD_ShapeAnimJoint',
    'HSD_ShapeAnimDObj',
    'HSD_ShapeAnim',
    'HSD_FogDesc',
    #'Particle', #placeholder
    'HSD_RenderDesc',
    #'HSD_RenderAnim',
    'HSD_RObjAnim',
    'HSD_RObj',
    #'HSD_FogAdjDesc',

    'Spline',
)

_HSD_FORMATS = {
    'HSD_ArchiveHeader':            ('I', 'I', 'I', 'I', 'I'),
    'HSD_ArchiveRelocationInfo':    ('I'),
    'HSD_ArchivePublicInfo':        ('I', 'I'),
    'HSD_ArchiveExternInfo':        ('I', 'I'),
    'HSD_SceneDesc':                ('I', 'I', 'I', 'I'),
    'HSD_SceneModelSet':            ('I', 'I', 'I', 'I'),
    'HSD_Joint':                    ('I', 'I', 'I', 'I', 'I', '3f', '3f', '3f', 'I', 'I'),
    'HSD_DObjDesc':                 ('I', 'I', 'I', 'I'),
    'HSD_PObjDesc':                 ('I', 'I', 'I', 'H', 'H', 'I', 'I'),
    'HSD_ShapeSetDesc':             ('H', 'H', 'I', 'I', 'I', 'I', 'I', 'I'),
    'HSD_ShapeIndex':               ('B', 'B', 'B'),
    'HSD_EnvelopeDesc':             ('I', 'f'),
    'HSD_VtxDescList':              ('I', 'I', 'I', 'I', 'Bx', 'H', 'I'), #removed pad byte
    'HSD_MObjDesc':                 ('I', 'I', 'I', 'I', 'I', 'I'),
    'HSD_PEDesc':                   ('B', 'B', 'B', 'B', 'B', 'B', 'B', 'B', 'B', 'B', 'B', 'B'),
    #'GXColor':                      ('B', 'B', 'B', 'B'),
    'HSD_Material':                 ('4B', '4B', '4B', 'f', 'f'),
    'HSD_TObjDesc':                 ('I', 'I', 'I', 'I', '3f', '3f', '3f', 'I', 'I', 'B', 'Bxx', 'I', 'f', 'I', 'I', 'I', 'I', 'I'),
    'HSD_TObjTevDesc':              ('B', 'B', 'B', 'B', 'B', 'B', 'B', 'B', 'B', 'B', 'B', 'B', 'B', 'B', 'B', 'B', '4B', '4B', '4B', 'I'),
    'HSD_TexLODDesc':               ('I', 'f', 'B', 'B', 'I'),
    'HSD_TlutDesc':                 ('I', 'I', 'I', 'H'),
    'HSD_ImageDesc':                ('I', 'H', 'H', 'I', 'I', 'f', 'f'),
    'HSD_SceneCameraSet':           ('I', 'I'),
    'HSD_CameraAnim':               ('I', 'I', 'I'),
    #'Viewport':                     ('H', 'H', 'H', 'H'),
    'HSD_CameraDesc':               ('I', 'H', 'H', '4H', '4H', 'I', 'I', 'f', 'I', 'f', 'f', 'f', 'f'),
    'HSD_SceneLightSet':            ('I', 'I'),
    'HSD_LightAnim':                ('I', 'I', 'I', 'I'),
    'HSD_WObjAnim':                 ('I', 'I'),
    'HSD_LightDesc':                ('I', 'I', 'H', 'H', '4B', 'I', 'I', 'I'),
    'HSD_AttnDesc':                 ('3f', '3f'),
    'HSD_SList':                    ('I', 'I'),
    'HSD_LightPointDesc':           ('f', 'f', 'I'),
    'HSD_LightSpotDesc':            ('f', 'I', 'f', 'f', 'I'),
    'HSD_WObjDesc':                 ('I', '3f', 'I'),
    'HSD_FObjDesc':                 ('I', 'I', 'f', 'B', 'B', 'Bx', 'I'), #removed pad byte
    'HSD_AObjDesc':                 ('I', 'f', 'I', 'I'),
    'HSD_AnimJoint':                ('I', 'I', 'I', 'I', 'I'),
    'HSD_MatAnimJoint':             ('I', 'I', 'I'),
    'HSD_MatAnim':                  ('I', 'I', 'I', 'I'),
    'HSD_TexAnim':                  ('I', 'I', 'I', 'I', 'I', 'H', 'H'),
    'HSD_ShapeAnimJoint':           ('I', 'I', 'I'),
    'HSD_ShapeAnimDObj':            ('I', 'I'),
    'HSD_ShapeAnim':                ('I', 'I'),
    'HSD_FogDesc':                  ('I', 'I', 'f', 'f', '4B'),
    #'Particle': #placeholder        ('I'),
    'HSD_RenderDesc':               ('I', 'I', 'I'),
    #'HSD_RenderAnim':               ('I'),
    'HSD_RObjAnim':                 ('I'),
    'HSD_RObj':                     ('I', 'I', 'I'),
    #'HSD_FogAdjDesc':               ('I'),

    'Spline':                       ('H', 'H', 'f', 'I', 'f', 'I', 'I'),
}

_HSD_COMPONENTS = {
    'HSD_ArchiveHeader':            'file_size data_size nb_reloc nb_public nb_extern',
    'HSD_ArchiveRelocationInfo':    'offset',
    'HSD_ArchivePublicInfo':        'entry name',
    'HSD_ArchiveExternInfo':        'entry name',
    'HSD_SceneDesc':                'modelsets cameraset lightsets fog',
    'HSD_SceneModelSet':            'joint animjoints matanimjoints shapeanimjoints',
    'HSD_Joint':                    'name flags child next u rotation scale position invbind robj',
    'HSD_DObjDesc':                 'name next mobj pobj',
    'HSD_PObjDesc':                 'name next vtxdesclist flags displistsize displist u',
    'HSD_ShapeSetDesc':             'flags nb_shape nb_vertex_index vertex_desc vertex_idx_list nb_normal_index normal_desc normal_idx_list',
    'HSD_ShapeIndex':               'id0 id1 id2',
    'HSD_EnvelopeDesc':             'joint weight',
    'HSD_VtxDescList':              'attr attr_type comp_cnt comp_type comp_frac stride base_ptr',
    'HSD_MObjDesc':                 'class_name rendermode texdesc mat renderdesc pedesc',
    'HSD_PEDesc':                   'flags ref0 ref1 dst_alpha type src_factor dst_factor logic_op z_comp alpha_comp0 alpha_op alpha_comp1',
    #'GXColor':                      'r g b a',
    'HSD_Material':                 'ambient diffuse specular alpha shininess',
    'HSD_TObjDesc':                 'class_name next texid src rotate scale translate wrap_s wrap_t repeat_s repeat_t flag blending magFilt imagedesc tlutdesc lod tev', #id is replaced with texid
    'HSD_TObjTevDesc':              'color_op alpha_op color_bias alpha_bias color_scale alpha_scale color_clamp alpha_clamp color_a color_b color_c color_d alpha_a alpha_b alpha_c alpha_d konst tev0 tev1 active',
    'HSD_TexLODDesc':               'minFilt LODBias bias_clamp edgeLODEnable max_aniso',
    'HSD_TlutDesc':                 'lut fmt tlut_name n_entries',
    'HSD_ImageDesc':                'image_ptr width height format mipmap minLOD maxLOD',
    'HSD_SceneCameraSet':           'camdesc camanimlist',
    'HSD_CameraAnim':               'aobj eyeposanim interestanim',
    #'Viewport':                     'ix iw iy ih',
    'HSD_CameraDesc':               'name flags perspectiveflags viewport scissor pos interest roll upvector near far fov aspect',
    'HSD_SceneLightSet':            'lightdesc lightanimlist',
    'HSD_LightAnim':                'next aobj eyeposanim interestanim',
    'HSD_WObjAnim':                 'aobj robjanim',
    'HSD_LightDesc':                'name link flags attnflags lightcolor pos interest u',
    'HSD_AttnDesc':                 'angle dist',
    'HSD_SList':                    'next data',
    'HSD_LightPointDesc':           'ref_br ref_dist',
    'HSD_LightSpotDesc':            'cutoff spotflags ref_br ref_dist distattnflags',
    'HSD_WObjDesc':                 'name wobjposition robj',
    'HSD_FObjDesc':                 'next length startframe type frac_value frac_slope ad',
    'HSD_AObjDesc':                 'flags endframe fobjdesc joint',
    'HSD_AnimJoint':                'child next aobjdesc robjanim flags',
    'HSD_MatAnimJoint':             'child next matanim',
    'HSD_MatAnim':                  'next aobjdesc texanim renderanim',
    'HSD_TexAnim':                  'next id aobjdesc imagetbl tluttbl nb_imagetbl nb_tluttbl',
    'HSD_ShapeAnimJoint':           'child next shapeanim',
    'HSD_ShapeAnimDObj':            'next shapeanim',
    'HSD_ShapeAnim':                'next aobjdesc',
    'HSD_FogDesc':                  'type adjdesc startz endz color',
    #'Particle':                     'placeholder',
    'HSD_RenderDesc':               'toontobjdesc gradtobjdesc terminator',
    #'HSD_RenderAnim':               'placeholder',
    'HSD_RObjAnim':                 'placeholder',
    'HSD_RObj':                     'next flags u',
    #'HSD_FogAdjDesc':               'placeholder',

    'Spline':                     'flags n f0 s1 f1 s2 s3',
}
"""
_HSD_STRUCTS = {}

for name in _HSD_NAMES:
    _HSD_STRUCTS[name] = collections.namedtuple(name, _HSD_COMPONENTS[name])
"""
#to avoid duplicate object creation and infinite recursion
_created_structs = {}

for name in _HSD_NAMES:
    _created_structs[name] = {}

def HSD_read_struct_components(fmts, data):
    result = []
    i = 0
    for fmt in fmts:
        size = struct.calcsize(fmt)
        j = i + size
        unpack = struct.unpack('>' + fmt, data[i:j])
        if len(unpack) > 1:
            result.append(list(unpack))
        else:
            result.append(unpack[0])
        i = j
    return result

#returns object and whether it already exists
def HSD_read_struct(name, data, offset):
    if not offset < 0:
        if offset in _created_structs[name]:
            return (_created_structs[name][offset], True)
        struct = HSD_Object()
        for component, value in zip(_HSD_COMPONENTS[name].split(' '), HSD_read_struct_components(_HSD_FORMATS[name], data[offset:])):
            setattr(struct, component, value)
        struct.id = offset
        #_HSD_STRUCTS[name]._make(HSD_read_struct_components(_HSD_FORMATS[name], data[offset:]))
        _created_structs[name][offset] = struct
        return (struct, False)
    else:
        struct = HSD_Object()
        for component, value in zip(_HSD_COMPONENTS[name].split(' '), HSD_read_struct_components(_HSD_FORMATS[name], data[0:])):
            setattr(struct, component, value)
        struct.id = -1
        return (struct, False)

def HSD_reset_created_structs():
    for name in _HSD_NAMES:
        _created_structs[name] = {}
    gc.collect()

def HSD_get_struct_size(name):
    return struct.calcsize(''.join(_HSD_FORMATS[name]))

def HSD_get_struct_dict(name):
    return _created_structs[name]

def HSD_get_archive_section(info_data, header, name):
    public_size = HSD_get_struct_size('HSD_ArchivePublicInfo')
    extern_size = HSD_get_struct_size('HSD_ArchiveExternInfo')
    name_location = info_data[header.nb_public * public_size + header.nb_extern * extern_size:]

    for i in range(header.nb_public):
        public_info, _ = HSD_read_struct('HSD_ArchivePublicInfo', info_data[i * public_size:], -1)
        string = util.read_c_string(name_location[public_info.name:])
        if string == name:
            return public_info

    info_data = info_data[header.nb_public * public_size:]

    for i in range(header.nb_extern):
        extern_info, _ = HSD_read_struct('HSD_ArchiveExternInfo', info_data[i * extern_size:], -1)
        string = util.read_c_string(name_location[extern_info.name:])
        if string == name:
            return extern_info

    return None

def HSD_init_array(data, offset, func):
    if offset == 0:
        return None, True
    elif offset >= len(data):
        return None, False
    set = []
    while True:
        if not (offset < len(data) - 4):
            return None, False
        set_offset = util.read_u32(data[offset:])
        if set_offset == 0:
            break
        object, valid = func(data, set_offset)
        if not valid:
            return None, False
        set.append(object)
        offset += 4
    return set, True

def HSD_init_FogArray(data, offset, func):
    #What is this ?
    if offset == 0:
        return None, True
    elif offset >= len(data):
        return None, False
    if not (offset < len(data) - 4):
        return None, False
    set_offset = util.read_u32(data[offset:])
    if set_offset != 0:
        object, valid = func(data, set_offset)
        if not valid:
            return None, False
    else:
        return None, True
    return object, True

def HSD_initialize_scene(data, info, rel):
    scenedesc, old = HSD_read_struct('HSD_SceneDesc', data, info.entry)
    if old:
        return scenedesc
    scenedesc.modelsets, valid = HSD_init_array(data, scenedesc.modelsets, HSD_init_SceneModelSet)
    if not valid:
        return None
    #TODO: Disabled due to bug, Fix! falsely reports invalid scene
    #scenedesc.cameraset, valid = HSD_init_SceneCameraSet(data, scenedesc.cameraset)
    #if not valid:
    #    return None
    scenedesc.lightsets, valid = HSD_init_array(data, scenedesc.lightsets, HSD_init_SceneLightSet)
    if not valid:
        return None
    scenedesc.fog, valid = HSD_init_FogArray(data, scenedesc.fog, HSD_init_FogDesc)
    if not valid:
        return None
    return scenedesc

#no need writing this into all the functions
def offset_check(func):
    def wrapper(data, offset):
        if offset == 0:
            return None, True
        elif offset >= len(data):
            return None, False
        return func(data, offset)
    return wrapper

@offset_check
def HSD_init_SceneModelSet(data, offset):
    scenemodelset, old = HSD_read_struct('HSD_SceneModelSet', data, offset)
    if old:
        return scenemodelset, True
    scenemodelset.joint, valid = HSD_init_Joint(data, scenemodelset.joint)
    if not valid:
        return None, False
    scenemodelset.animjoints, valid = HSD_init_array(data, scenemodelset.animjoints, HSD_init_AnimJoint)
    if not valid:
        return None, False
    scenemodelset.matanimjoints, valid = HSD_init_array(data, scenemodelset.matanimjoints, HSD_init_MatAnimJoint)
    if not valid:
        return None, False
    scenemodelset.shapeanimjoints, valid = HSD_init_array(data, scenemodelset.shapeanimjoints, HSD_init_ShapeAnimJoint)
    if not valid:
        return None, False
    return scenemodelset, True

@offset_check
def HSD_init_Joint(data, offset):
    joint, old = HSD_read_struct('HSD_Joint', data, offset)
    if old:
        return joint, True
    joint.name, valid = HSD_init_string(data, joint.name)
    if not valid:
        return None, False
    joint.child, valid = HSD_init_Joint(data, joint.child)
    if not valid:
        return None, False
    joint.next, valid = HSD_init_Joint(data, joint.next)
    if not valid:
        return None, False
    if joint.flags & JOBJ_PTCL:
        #Particle data
        #TODO:
        joint.u = None
    elif joint.flags & JOBJ_SPLINE:
        #Spline data
        joint.u, valid = HSD_init_Spline(data, joint.u)
        if not valid:
            return None, False
    else:
        #Mesh data
        joint.u, valid = HSD_init_DObjDesc(data, joint.u)
        if not valid:
            return None, False
    joint.invbind, valid = HSD_init_Mtx(data, joint.invbind)
    if not valid:
        return None, False
    joint.robj, valid = HSD_init_RObj(data, joint.robj)
    if not valid:
        return None, False
    return joint, True

@offset_check
def HSD_init_Spline(data, offset):
    spline, old = HSD_read_struct('Spline', data, offset)
    if old:
        return spline, True
    if (spline.flags >> 8) == 0:
        if spline.s1:
            p = data[spline.s1:]
            spline.s1 = []
            for i in range(spline.n):
                v = []
                for j in range(3):
                    v.append(struct.unpack('>f', p[i * 12 + j * 4: i * 12 + (j + 1) * 4]))
                spline.s1.append(v)
        else:
            spline.s1 = None
        if not spline.s3:
            spline.s3 = None
    elif (spline.flags >> 8) == 3:
        if spline.s1:
            p = data[spline.s1:]
            spline.s1 = []
            for i in range(spline.n + 2):
                v = []
                for j in range(3):
                    v.append(struct.unpack('>f', p[i * 12 + j * 4: i * 12 + (j + 1) * 4]))
                spline.s1.append(v)
        else:
            spline.s1 = None
        if spline.s3:
            p = data[spline.s3:]
            spline.s3 = []
            for i in range(spline.n - 1):
                v = []
                for j in range(5):
                    v.append(struct.unpack('>f', p[i * 20 + j * 4: i * 20 + (j + 1) * 4]))
                spline.s3.append(v)
        else:
            spline.s3 = None
    else:
        pass
    if spline.s2:
        p = data[spline.s2:]
        spline.s2 = []
        for i in range(spline.n):
            spline.s2.append(struct.unpack('>f', p[i * 4: (i + 1) * 4]))
    else:
        spline.s2 = None

    return spline, True

@offset_check
def HSD_init_DObjDesc(data, offset):
    dobjdesc, old = HSD_read_struct('HSD_DObjDesc', data, offset)
    if old:
        return dobjdesc, True
    dobjdesc.name, valid = HSD_init_string(data, dobjdesc.name)
    if not valid:
        return None, False
    dobjdesc.next, valid = HSD_init_DObjDesc(data, dobjdesc.next)
    if not valid:
        return None, False
    dobjdesc.mobj, valid = HSD_init_MObjDesc(data, dobjdesc.mobj)
    if not valid:
        return None, False
    dobjdesc.pobj, valid = HSD_init_PObjDesc(data, dobjdesc.pobj)
    if not valid:
        return None, False
    return dobjdesc, True

@offset_check
def HSD_init_PObjDesc(data, offset):
    pobjdesc, old = HSD_read_struct('HSD_PObjDesc', data, offset)
    if old:
        return pobjdesc, True
    pobjdesc.next, valid = HSD_init_PObjDesc(data, pobjdesc.next)
    if not valid:
        return None, False
    offset = pobjdesc.vtxdesclist
    size = HSD_get_struct_size('HSD_VtxDescList')
    pobjdesc.vtxdesclist = []
    while True:
        vtxdesc, valid = HSD_init_VtxDescList(data, offset)
        if not valid:
            return None, False
        if vtxdesc.attr == 0xFF:
            break
        pobjdesc.vtxdesclist.append(vtxdesc)
        offset += size
    #raw pointer
    if pobjdesc.displist == 0:
        pobjdesc.displist = None
    elif pobjdesc.displist < len(data):
        pobjdesc.displist = data[pobjdesc.displist:]
    else:
        return None, False
    type = pobjdesc.flags & POBJ_TYPE_MASK
    if type == POBJ_SKIN:
        #skin: only one additional bone for control
        pobjdesc.u, valid = HSD_init_Joint(data, pobjdesc.u)
        if not valid:
            return None, False
    elif type == POBJ_SHAPEANIM:
        #shape keys
        pobjdesc.u, valid = HSD_init_ShapeSetDesc(data, pobjdesc.u)
        if not valid:
            return None, False
    else:
        #envelope
        envelopes, valid = HSD_init_array(data, pobjdesc.u, HSD_init_EnvelopeDesc_array)
        if not valid or len(envelopes) > 10:
            #only ten influence Matrices are available
            return None, False
        pobjdesc.u = envelopes
    return pobjdesc, True

@offset_check
def HSD_init_ShapeSetDesc(data, offset):
    shapesetdesc, old = HSD_read_struct('HSD_ShapeSetDesc', data, offset)
    if old:
        return shapesetdesc, True
    shapesetdesc.vertex_desc, valid = HSD_init_VtxDescList(data, shapesetdesc.vertex_desc)
    if not valid:
        return None, False
    shapesetdesc.vertex_idx_list, valid = HSD_init_index_array(data, shapesetdesc.vertex_idx_list, shapesetdesc.nb_shape, shapesetdesc.nb_vertex_index)
    if not valid:
        return None, False
    shapesetdesc.normal_desc, valid = HSD_init_VtxDescList(data, shapesetdesc.normal_desc)
    if not valid:
        return None, False
    shapesetdesc.normal_idx_list, valid = HSD_init_index_array(data, shapesetdesc.normal_idx_list, shapesetdesc.nb_shape, shapesetdesc.nb_normal_index)
    if not valid:
        return None, False
    return shapesetdesc, True


def HSD_init_index_array(data, offset, nb_shape, nb_t_index):
    if offset == 0:
        return None, True
    elif offset >= len(data):
        return None, False
    shape_array_offset = offset
    idx_list = []
    size = HSD_get_struct_size('HSD_ShapeIndex')
    for i in range(nb_shape + 1):
        if not (shape_array_offset < len(data) - 4):
            return None, False
        set_offset = util.read_u32(data[shape_array_offset:])
        if set_offset == 0:
            break
        set = []
        #idx_list.append(set)
        #for j in range(nb_t_index):
        #    #shape_index, valid = HSD_init_ShapeIndex(data, set_offset)
        #    if not valid:
        #        return None, False
        #    set.append(shape_index)
        #    set_offset += size
        idx_list.append(data[set_offset:])
        shape_array_offset += 4
    return idx_list, True

@offset_check
def HSD_init_ShapeIndex(data, offset):
    idx, _ = HSD_read_struct('HSD_ShapeIndex', data, offset)
    return idx, True

@offset_check
def HSD_init_EnvelopeDesc_array(data, offset):
    size = HSD_get_struct_size('HSD_EnvelopeDesc')
    envdescs = []
    while True:
        envdesc, valid = HSD_init_EnvelopeDesc(data, offset)
        if not valid:
            return None, False
        if not envdesc.joint:
            break
        envdescs.append(envdesc)
        offset += size
        if not offset < len(data):
            return None, False
    return envdescs, True

@offset_check
def HSD_init_EnvelopeDesc(data ,offset):
    envdesc, old = HSD_read_struct('HSD_EnvelopeDesc', data, offset)
    if old:
        return envdesc, True
    envdesc.joint, valid = HSD_init_Joint(data, envdesc.joint)
    if not valid:
        return None, False
    return envdesc, True

@offset_check
def HSD_init_VtxDescList(data, offset):
    vtxdesc, old = HSD_read_struct('HSD_VtxDescList', data, offset)
    if old:
        return vtxdesc, True
    #raw pointer
    if vtxdesc.base_ptr < len(data):
        vtxdesc.base_ptr = data[vtxdesc.base_ptr:]
    else:
        return None, False
    return vtxdesc, True

@offset_check
def HSD_init_MObjDesc(data, offset):
    mobjdesc, old = HSD_read_struct('HSD_MObjDesc', data, offset)
    if old:
        return mobjdesc, True
    mobjdesc.class_name, valid = HSD_init_string(data, mobjdesc.class_name)
    if not valid:
        return None, False
    mobjdesc.texdesc, valid = HSD_init_TObjDesc(data, mobjdesc.texdesc)
    if not valid:
        return None, False
    mobjdesc.mat, valid = HSD_init_Material(data, mobjdesc.mat)
    if not valid:
        return None, False
    mobjdesc.renderdesc, valid = HSD_init_RenderDesc(data, mobjdesc.renderdesc)
    if not valid:
        return None, False
    mobjdesc.pedesc, valid = HSD_init_PEDesc(data, mobjdesc.pedesc)
    if not valid:
        return None, False
    return mobjdesc, True

@offset_check
def HSD_init_PEDesc(data, offset):
    pedesc, _ = HSD_read_struct('HSD_PEDesc', data, offset)
    return pedesc, True

@offset_check
def HSD_init_Material(data, offset):
    mat, _ = HSD_read_struct('HSD_Material', data, offset)
    return mat, True

@offset_check
def HSD_init_TObjDesc(data, offset):
    tobjdesc, old = HSD_read_struct('HSD_TObjDesc', data, offset)
    if old:
        return tobjdesc, True
    tobjdesc.next, valid = HSD_init_TObjDesc(data, tobjdesc.next)
    if not valid:
        return None, False
    tobjdesc.imagedesc, valid = HSD_init_ImageDesc(data, tobjdesc.imagedesc)
    if not valid:
        return None, False
    tobjdesc.tlutdesc, valid = HSD_init_TlutDesc(data, tobjdesc.tlutdesc)
    if not valid:
        return None, False
    tobjdesc.lod, valid = HSD_init_LODDesc(data, tobjdesc.lod)
    if not valid:
        return None, False
    tobjdesc.tev, valid = HSD_init_TObjTevDesc(data, tobjdesc.tev)
    if not valid:
        return None, False
    return tobjdesc, True

@offset_check
def HSD_init_TObjTevDesc(data, offset):
    tevdesc, _ = HSD_read_struct('HSD_TObjTevDesc', data, offset)
    return tevdesc, True

@offset_check
def HSD_init_LODDesc(data, offset):
    loddesc, _ = HSD_read_struct('HSD_TexLODDesc', data, offset)
    return loddesc, True

@offset_check
def HSD_init_TlutDesc(data, offset):
    tlutdesc, old = HSD_read_struct('HSD_TlutDesc', data, offset)
    if old:
        return tlutdesc, True
    #raw pointer
    if tlutdesc.lut == 0:
        tlutdesc.lut_id = 0
        tlutdesc.lut = None
    elif tlutdesc.lut < len(data):
        tlutdesc.lut_id = tlutdesc.lut
        tlutdesc.lut = data[tlutdesc.lut:]
    else:
        return None, False
    return tlutdesc, True

@offset_check
def HSD_init_ImageDesc(data, offset):
    imagedesc, old = HSD_read_struct('HSD_ImageDesc', data, offset)
    if old:
        return imagedesc, True
    #raw pointer
    if imagedesc.image_ptr < len(data):
        imagedesc.image_ptr_id = imagedesc.image_ptr
        imagedesc.image_ptr = data[imagedesc.image_ptr:]
    else:
        return None, False
    return imagedesc, True

@offset_check
def HSD_init_SceneCameraSet(data, offset):
    cameraset, old = HSD_read_struct('HSD_SceneCameraSet', data, offset)
    if old:
        return cameraset, True
    cameraset.camdesc, valid = HSD_init_CameraDesc(data, cameraset.camdesc)
    if not valid:
        return None, False
    cameraset.camanimlist, valid = HSD_init_array(data, cameraset.camanimlist, HSD_init_CameraAnim)
    if not valid:
        return None, False
    return cameraset, True

@offset_check
def HSD_init_CameraAnim(data, offset):
    camanim, old = HSD_read_struct('HSD_CameraAnim', data, offset)
    if old:
        return camanim, True
    camanim.aobj, valid = HSD_init_AObjDesc(data, camanim.aobj)
    if not valid:
        return None, False
    camanim.eyeposanim, valid = HSD_init_WObjDesc(data, camanim.eyeposanim)
    if not valid:
        return None, False
    camanim.interestanim, valid = HSD_init_WObjDesc(data, camanim.interestanim)
    if not valid:
        return None, False
    return camanim, True

@offset_check
def HSD_init_CameraDesc(data, offset):
    camdesc, old = HSD_read_struct('HSD_CameraDesc', data, offset)
    if old:
        return camdesc, True
    camdesc.name, valid = HSD_init_string(data, camdesc.name)
    if not valid:
        return None, False
    camdesc.pos, valid = HSD_init_WObjDesc(data, camdesc.pos)
    if not valid:
        return None, False
    camdesc.interest, valid = HSD_init_WObjDesc(data, camdesc.interest)
    if not valid:
        return None, False
    camdesc.upvector, valid = HSD_init_Vec(data, camdesc.upvector)
    if not valid:
        return None, False
    return camdesc, True

@offset_check
def HSD_init_SceneLightSet(data, offset):
    lightset, old = HSD_read_struct('HSD_SceneLightSet', data, offset)
    if old:
        return lightset, True
    lightset.lightdesc, valid = HSD_init_LightDesc(data, lightset.lightdesc)
    if not valid:
        return None, False
    lightset.lightanimlist, valid = HSD_init_array(data, lightset.lightanimlist, HSD_init_LightAnim)
    if not valid:
        return None, False
    return lightset, True

@offset_check
def HSD_init_LightAnim(data, offset):
    lightanim, old = HSD_read_struct('HSD_LightAnim', data, offset)
    if old:
        return lightanim, True
    lightanim.next, valid = HSD_init_LightAnim(data, lightanim.next)
    if not valid:
        return None, False
    lightanim.aobj, valid = HSD_init_AObjDesc(data, lightanim.aobj)
    if not valid:
        return None, False
    lightanim.eyeposanim, valid = HSD_init_WObjAnim(data, lightanim.eyeposanim)
    if not valid:
        return None, False
    lightanim.interestanim, valid = HSD_init_WObjAnim(data, lightanim.interestanim)
    if not valid:
        return None, False
    return lightanim, True

@offset_check
def HSD_init_WObjAnim(data, offset):
    wobjanim, old = HSD_read_struct('HSD_WObjAnim', data, offset)
    if old:
        return wobjanim, True
    wobjanim.aobj, valid = HSD_init_AObjDesc(data, wobjanim.aobj)
    if not valid:
        return None, False
    wobjanim.robjanim, valid = HSD_init_RObjAnim(data, wobjanim.robjanim)
    if not valid:
        return None, False
    return wobjanim, True

@offset_check
def HSD_init_LightDesc(data, offset):
    light, old = HSD_read_struct('HSD_LightDesc', data, offset)
    if old:
        return light, True
    light.name, valid = HSD_init_string(data, light.name)
    if not valid:
        return None, False
    light.link, valid = HSD_init_LightDesc(data, light.link)
    if not valid:
        return None, False
    light.pos, valid = HSD_init_WObjDesc(data, light.pos)
    if not valid:
        return None, False
    light.interest, valid = HSD_init_WObjDesc(data, light.interest)
    if not valid:
        return None, False
    if light.attnflags & LOBJ_LIGHT_ATTN:
        light.u, valid = HSD_init_AttnDesc(data, light.u)
    else:
        if light.flags == LOBJ_INFINITE:
            light.u, valid = HSD_init_float(data, light.u)
        elif light.flags == LOBJ_POINT:
            light.u, valid = HSD_init_LightPointDesc(data, light.u)
        elif light.flags == LOBJ_SPOT:
            light.u, valid = HSD_init_LightSpotDesc(data, light.u)
        else:
            #LOBJ_AMBIENT
            #nothing ?
            pass
    if not valid:
        return None, False
    return light, True

@offset_check
def HSD_init_AttnDesc(data, offset):
    attndesc, _ = HSD_read_struct('HSD_AttnDesc', data, offset)
    return attndesc, True

@offset_check
def HSD_init_SList(data, offset):
    slist, old = HSD_read_struct('HSD_SList', data, offset)
    if old:
        return slist, True
    #raw pointer
    if slist.data == 0:
        slist.data = None
    elif slist.data < len(data):
        slist.data = data[slist.data:]
    else:
        return None, False
    return slist, True

@offset_check
def HSD_init_LightPointDesc(data, offset):
    pointdesc, _ = HSD_read_struct('HSD_LightPointDesc', data, offset)
    return pointdesc, True

@offset_check
def HSD_init_LightSpotDesc(data, offset):
    spotdesc, _ = HSD_read_struct('HSD_LightSpotDesc', data, offset)
    return spotdesc, True

@offset_check
def HSD_init_WObjDesc(data, offset):
    wobjdesc, old = HSD_read_struct('HSD_WObjDesc', data, offset)
    if old:
        return wobjdesc, True
    wobjdesc.name, valid = HSD_init_string(data, wobjdesc.name)
    if not valid:
        return None, False
    wobjdesc.robj, valid = HSD_init_RObj(data, wobjdesc.robj)
    if not valid:
        return None, False
    return wobjdesc, True

@offset_check
def HSD_init_FObjDesc(data, offset):
    fobjdesc, old = HSD_read_struct('HSD_FObjDesc', data, offset)
    if old:
        return fobjdesc, True
    fobjdesc.next, valid = HSD_init_FObjDesc(data, fobjdesc.next)
    if not valid:
        return None, False
    #raw pointer
    if fobjdesc.ad == 0:
        fobjdesc.ad = None
    elif fobjdesc.ad < len(data):
        fobjdesc.ad = data[fobjdesc.ad:]
    else:
        return None, False
    return fobjdesc, True

@offset_check
def HSD_init_AObjDesc(data, offset):
    aobj, old = HSD_read_struct('HSD_AObjDesc', data, offset)
    if old:
        return aobj, True
    aobj.fobjdesc, valid = HSD_init_FObjDesc(data, aobj.fobjdesc)
    if not valid:
        return None, False
    aobj.joint, valid = HSD_init_Joint(data, aobj.joint)
    if not valid:
        return None, False
    return aobj, True

@offset_check
def HSD_init_AnimJoint(data, offset):
    animjoint, old = HSD_read_struct('HSD_AnimJoint', data, offset)
    if old:
        return animjoint, True
    animjoint.child, valid = HSD_init_AnimJoint(data, animjoint.child)
    if not valid:
        return None, False
    animjoint.next, valid = HSD_init_AnimJoint(data, animjoint.next)
    if not valid:
        return None, False
    animjoint.aobjdesc, valid = HSD_init_AObjDesc(data, animjoint.aobjdesc)
    if not valid:
        return None, False
    animjoint.robjanim, valid = HSD_init_RObjAnim(data, animjoint.robjanim)
    if not valid:
        return None, False
    return animjoint, True

@offset_check
def HSD_init_MatAnimJoint(data, offset):
    matanimjoint, old = HSD_read_struct('HSD_MatAnimJoint', data, offset)
    if old:
        return matanimjoint, True
    matanimjoint.child, valid = HSD_init_MatAnimJoint(data, matanimjoint.child)
    if not valid:
        return None, False
    matanimjoint.next, valid = HSD_init_MatAnimJoint(data, matanimjoint.next)
    if not valid:
        return None, False
    matanimjoint.matanim, valid = HSD_init_MatAnim(data, matanimjoint.matanim)
    if not valid:
        return None, False
    return matanimjoint, True

@offset_check
def HSD_init_MatAnim(data, offset):
    matanim, old = HSD_read_struct('HSD_MatAnim', data, offset)
    if old:
        return matanim, True
    matanim.next, valid = HSD_init_MatAnim(data, matanim.next)
    if not valid:
        return None, False
    matanim.aobjdesc, valid = HSD_init_AObjDesc(data, matanim.aobjdesc)
    if not valid:
        return None, False
    matanim.texanim, valid = HSD_init_TexAnim(data, matanim.texanim)
    if not valid:
        return None, False
    matanim.renderanim, valid = HSD_init_RenderAnim(data, matanim.renderanim)
    if not valid:
        return None, False
    return matanim, True

@offset_check
def HSD_init_TexAnim(data, offset):
    texanim, old = HSD_read_struct('HSD_TexAnim', data, offset)
    if old:
        return texanim, True
    texanim.next, valid = HSD_init_TexAnim(data, texanim.next)
    if not valid:
        return None, False
    texanim.aobjdesc, valid = HSD_init_AObjDesc(data, texanim.aobjdesc)
    if not valid:
        return None, False
    texanim.imagetbl, valid = HSD_init_tbl_array(data, texanim.imagetbl, texanim.nb_imagetbl, HSD_init_ImageDesc)
    if not valid:
        return None, False
    texanim.tluttbl, valid = HSD_init_tbl_array(data, texanim.tluttbl, texanim.nb_tluttbl, HSD_init_TlutDesc)
    if not valid:
        return None, False
    return texanim, True

def HSD_init_tbl_array(data, offset, nb, func):
    if offset == 0:
        return None, True
    elif offset >= len(data):
        return None, False
    set = []
    for i in range(nb):
        if not (offset < len(data) - 4):
            return None, False
        set_offset = util.read_u32(data[offset:])
        if set_offset == 0:
            continue
        object, valid = func(data, set_offset)
        if not valid:
            return None, False
        set.append(object)
        offset += 4
    return set, True

@offset_check
def HSD_init_ShapeAnimJoint(data, offset):
    shapeanimjoint, old = HSD_read_struct('HSD_ShapeAnimJoint', data, offset)
    if old:
        return shapeanimjoint, True
    shapeanimjoint.child, valid = HSD_init_ShapeAnimJoint(data, shapeanimjoint.child)
    if not valid:
        return None, False
    shapeanimjoint.next, valid = HSD_init_ShapeAnimJoint(data, shapeanimjoint.next)
    if not valid:
        return None, False
    shapeanimjoint.shapeanim, valid = HSD_init_ShapeAnimDObj(data, shapeanimjoint.shapeanim)
    if not valid:
        return None, False
    return shapeanimjoint, True

@offset_check
def HSD_init_ShapeAnimDObj(data, offset):
    shapeanimdobj, old = HSD_read_struct('HSD_ShapeAnimDObj', data, offset)
    if old:
        return shapeanimdobj, True
    shapeanimdobj.next, valid = HSD_init_ShapeAnimDObj(data, shapeanimdobj.next)
    if not valid:
        return None, False
    shapeanimdobj.shapeanim, valid = HSD_init_ShapeAnim(data, shapeanimdobj.shapeanim)
    if not valid:
        return None, False
    return shapeanimdobj, True

@offset_check
def HSD_init_ShapeAnim(data, offset):
    shapeanim, old = HSD_read_struct('HSD_ShapeAnim', data, offset)
    if old:
        return shapeanim, True
    shapeanim.next, valid = HSD_init_ShapeAnim(data, shapeanim.next)
    if not valid:
        return None, False
    shapeanim.aobjdesc, valid = HSD_init_AObjDesc(data, shapeanim.aobjdesc)
    if not valid:
        return None, False
    return shapeanim, True

@offset_check
def HSD_init_FogDesc(data, offset):
    fog, old = HSD_read_struct('HSD_FogDesc', data, offset)
    if old:
        return fog, True
    fog.adjdesc, valid = HSD_init_FogAdjDesc(data, offset)
    if not valid:
        return None, False
    return fog, True

@offset_check
def HSD_init_Particle(data, offset):
    return None, True #TODO:

@offset_check
def HSD_init_RenderDesc(data, offset):
    return None, True #TODO:

@offset_check
def HSD_init_RenderAnim(data, offset):
    return None, True #TODO:

@offset_check
def HSD_init_RObjAnim(data, offset):
    robjanim, old = HSD_read_struct('HSD_RObjAnim', data, offset)
    if old:
        return robjanim, True
    return robjanim, True

#Reference/Constraint ?
@offset_check
def HSD_init_RObj(data, offset):
    robj, old = HSD_read_struct('HSD_RObj', data, offset)
    if old:
        return robj, True
    robj.next, valid = HSD_init_RObj(data, robj.next)
    if not valid:
        return None, False
    if (robj.flags & 0x70000000 == 0x10000000):
        robj.u, valid = HSD_init_Joint(data, robj.u)
    elif (robj.flags & 0x70000000 == 0x40000000):
        if robj.u:
            robj.val0 = struct.unpack('>f', data[robj.u + 0:robj.u + 4])[0]
            robj.val1 = struct.unpack('>f', data[robj.u + 4:robj.u + 8])[0]
    if not valid:
        return None, False

    """
    #placeholder0 : next
    #HSD_RObj *
    #placeholder1 : flags
    #4: type
    #28: constraint type
    #palceholder2 : u
    # type = 0x10000000 : jobj
    # type = 0x00000000 : rvalue

    #Rvalue:
    #Float
    #JObj
    if robj.placeholder1 & 10000000: #90  03
        robj.jobj, valid = HSD_init_Joint(data, robj.jobj)
        if not valid:
            return None, False
    elif robj.placeholder1 & 40000000: #C0  01
        robj.jobj, valid = HSD_init_RObj(data, robj.jobj)
        if not valid:
            return None, False
    """
    return robj, True

@offset_check
def HSD_init_FogAdjDesc(data, offset):
    return None, True #TODO:

@offset_check
def HSD_init_Mtx(data, offset):
    rows = []
    for i in range(3):
        rows.append(list(struct.unpack('>4f', data[offset:offset + 16])))
        offset += 16
    rows.append([0,0,0,1])
    return rows, True

@offset_check
def HSD_init_string(data, offset):
    return util.read_c_string(data[offset:]), True

@offset_check
def HSD_init_Vec(data, offset):
    vec = (struct.unpack('>3f', data[offset:offset + 3 * 4]))
    return vec, True

@offset_check
def HSD_init_float(data, offset):
    float = struct.unpack('>f', data[offset:offset + 4])[0]
    return float, True
