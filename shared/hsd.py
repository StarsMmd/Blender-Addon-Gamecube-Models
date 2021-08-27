HSD constants
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