"""Synthetic binary builders for DAT format test data."""
import struct


def build_archive_header(data_size, reloc_count=0, pub_count=0, ext_count=0):
    """
    Build a 32-byte ArchiveHeader.

    Layout: file_size(4) data_size(4) reloc_count(4) pub_count(4)
            ext_count(4) padding(12)
    """
    # section info follows data + relocation table
    section_info_size = (pub_count + ext_count) * 8
    file_size = 32 + data_size + reloc_count * 4 + section_info_size
    header = struct.pack(
        '>IIIII',
        file_size,
        data_size,
        reloc_count,
        pub_count,
        ext_count,
    )
    header += b'\x00' * 12  # padding to reach 32 bytes
    return header


def build_uint(value):
    return struct.pack('>I', value)


def build_float(value):
    return struct.pack('>f', value)


def build_vec3(x, y, z):
    return struct.pack('>fff', x, y, z)


def build_frame(next_ptr=0, data_length=0, start_frame=0.0,
                ftype=0, frac_value=0, frac_slope=0, ad_ptr=0):
    """
    Build binary for one Frame (FObject) struct.

    Struct layout (20 bytes with 1-byte alignment pad before ad):
      uint  next        (4)
      uint  data_length (4)
      float start_frame (4)
      uchar type        (1)
      uchar frac_value  (1)
      uchar frac_slope  (1)
      uchar <pad>       (1)
      uint  ad          (4)
    """
    data  = struct.pack('>I', next_ptr)
    data += struct.pack('>I', data_length)
    data += struct.pack('>f', start_frame)
    data += struct.pack('>BBB', ftype, frac_value, frac_slope)
    data += b'\x00'          # alignment padding
    data += struct.pack('>I', ad_ptr)
    return data


def build_minimal_dat(data_section: bytes) -> bytes:
    """Wrap raw data_section bytes in a minimal valid DAT file (no sections, no relocs)."""
    header = build_archive_header(len(data_section))
    return header + data_section


# ---------------------------------------------------------------------------
# Struct size constants (sum of all field widths including alignment padding)
# ---------------------------------------------------------------------------

JOINT_SIZE     = 64   # 4+4+4+4+4+12+12+12+4+4  (matrix and string are pointers = 4 each)
MESH_SIZE      = 16   # 4+4+4+4
POBJECT_SIZE   = 24   # 4+4+4+2+2+4+4
ANIMJOINT_SIZE = 20   # 4+4+4+4+4
FRAME_SIZE     = 20   # 4+4+4+1+1+1+1pad+4
SPLINE_SIZE    = 24   # 2+2+4+4+4+4+4
VERTEX_SIZE    = 24   # 4+4+4+4+1+1pad+2+4


# ---------------------------------------------------------------------------
# Node binary builders
# ---------------------------------------------------------------------------

def build_joint(name_ptr=0, flags=0, child_ptr=0, next_ptr=0, property_ptr=0,
                rotation=(0.0, 0.0, 0.0), scale=(0.0, 0.0, 0.0),
                position=(0.0, 0.0, 0.0), invbind_ptr=0, ref_ptr=0):
    """
    Build binary for one Joint struct (64 bytes).

    All pointer fields (name, child, next, inverse_bind, reference) are 4-byte
    data-section offsets.  rotation/scale/position are inline vec3 (12 bytes each).

      ptr  name         (4)
      uint flags        (4)
      ptr  child        (4)
      ptr  next         (4)
      uint property     (4)   ← raw pointer, resolved in loadFromBinary
      vec3 rotation     (12)
      vec3 scale        (12)
      vec3 position     (12)
      ptr  inverse_bind (4)
      ptr  reference    (4)
    """
    data  = struct.pack('>I',   name_ptr)
    data += struct.pack('>I',   flags)
    data += struct.pack('>I',   child_ptr)
    data += struct.pack('>I',   next_ptr)
    data += struct.pack('>I',   property_ptr)
    data += struct.pack('>fff', *rotation)
    data += struct.pack('>fff', *scale)
    data += struct.pack('>fff', *position)
    data += struct.pack('>I',   invbind_ptr)
    data += struct.pack('>I',   ref_ptr)
    return data  # 64 bytes


def build_mesh(name_ptr=0, next_ptr=0, mobject_ptr=0, pobject_ptr=0):
    """
    Build binary for one Mesh (DObject) struct (16 bytes).

      ptr name    (4)
      ptr next    (4)
      ptr mobject (4)
      ptr pobject (4)
    """
    data  = struct.pack('>I', name_ptr)
    data += struct.pack('>I', next_ptr)
    data += struct.pack('>I', mobject_ptr)
    data += struct.pack('>I', pobject_ptr)
    return data  # 16 bytes


def build_pobject(name_ptr=0, next_ptr=0, vertex_list_ptr=0, flags=0,
                  display_list_chunk_count=0, display_list_address=0,
                  property_ptr=0):
    """
    Build binary for one PObject struct (24 bytes).

      ptr    name                     (4)
      ptr    next                     (4)
      ptr    vertex_list              (4)
      ushort flags                    (2)
      ushort display_list_chunk_count (2)
      uint   display_list_address     (4)
      uint   property                 (4)   ← raw pointer, resolved by loadFromBinary
    """
    data  = struct.pack('>I',  name_ptr)
    data += struct.pack('>I',  next_ptr)
    data += struct.pack('>I',  vertex_list_ptr)
    data += struct.pack('>HH', flags, display_list_chunk_count)
    data += struct.pack('>I',  display_list_address)
    data += struct.pack('>I',  property_ptr)
    return data  # 24 bytes


def build_vertex_list_terminator():
    """
    Build a single Vertex with attribute=0xFF (terminator), rest zeroed.
    This signals VertexList.loadFromBinary() to stop reading.
    Returns VERTEX_SIZE (24) bytes.
    """
    data  = struct.pack('>I', 0xFF)  # attribute = 0xFF
    data += b'\x00' * (VERTEX_SIZE - 4)
    return data


def build_animjoint(child_ptr=0, next_ptr=0, animation_ptr=0,
                    render_animation_ptr=0, flags=0):
    """
    Build binary for one AnimationJoint struct (20 bytes).

      ptr  child            (4)
      ptr  next             (4)
      ptr  animation        (4)
      ptr  render_animation (4)
      uint flags            (4)
    """
    data  = struct.pack('>I', child_ptr)
    data += struct.pack('>I', next_ptr)
    data += struct.pack('>I', animation_ptr)
    data += struct.pack('>I', render_animation_ptr)
    data += struct.pack('>I', flags)
    return data  # 20 bytes


def build_spline(flags=0, n=0, f0=0.0, s1=0, f1=0.0, s2=0, s3=0):
    """
    Build binary for one Spline struct (24 bytes).

      ushort flags (2)
      ushort n     (2)
      float  f0    (4)
      uint   s1    (4)   ← pointer to vec3 array, resolved by loadFromBinary
      float  f1    (4)
      uint   s2    (4)   ← pointer to float array
      uint   s3    (4)   ← pointer to vec5 array
    """
    data  = struct.pack('>HH', flags, n)
    data += struct.pack('>f',  f0)
    data += struct.pack('>I',  s1)
    data += struct.pack('>f',  f1)
    data += struct.pack('>I',  s2)
    data += struct.pack('>I',  s3)
    return data  # 24 bytes


def build_particle():
    """Particle has no fields; its binary contribution is zero bytes."""
    return b''


def build_relocation_table(offsets):
    """Build a relocation table from a list of data-section offsets."""
    data = b''
    for offset in offsets:
        data += struct.pack('>I', offset)
    return data


def build_section_info(root_offset, name_offset):
    """Build an 8-byte section info entry: root_node_offset(4) + section_name_offset(4)."""
    return struct.pack('>II', root_offset, name_offset)


def build_dat_with_sections(data_section, relocations, sections, section_names):
    """
    Build a complete DAT binary with header, data section, relocations,
    section info entries, and section name strings.

    Parameters:
        data_section  — raw bytes for the data section
        relocations   — list of uint offsets for the relocation table
        sections      — list of (root_offset, is_public) tuples
        section_names — list of section name strings (same order as sections)

    Returns the full binary as bytes.
    """
    pub_count = sum(1 for _, is_pub in sections if is_pub)
    ext_count = sum(1 for _, is_pub in sections if not is_pub)

    # Pad data section to 4-byte alignment
    while len(data_section) % 4 != 0:
        data_section += b'\x00'

    reloc_data = build_relocation_table(relocations)

    # Build section info entries — public first, then external
    public_sections = [(off, name) for (off, is_pub), name in zip(sections, section_names) if is_pub]
    external_sections = [(off, name) for (off, is_pub), name in zip(sections, section_names) if not is_pub]
    ordered = public_sections + external_sections

    # Section name strings are concatenated; compute offsets relative to start of strings block
    name_offset = 0
    section_info_data = b''
    name_offsets = []
    for _, name in ordered:
        name_offsets.append(name_offset)
        name_offset += len(name) + 1  # +1 for null terminator

    for i, (root_off, _) in enumerate(ordered):
        section_info_data += build_section_info(root_off, name_offsets[i])

    names_data = b''
    for _, name in ordered:
        names_data += name.encode('utf-8') + b'\x00'

    # File size = header(32) + data + relocs + section_info + names
    total_after_header = len(data_section) + len(reloc_data) + len(section_info_data) + len(names_data)
    file_size = 32 + total_after_header

    header = struct.pack('>IIIII',
        file_size,
        len(data_section),
        len(relocations),
        pub_count,
        ext_count,
    )
    header += b'\x00' * 12  # padding to 32 bytes

    return header + data_section + reloc_data + section_info_data + names_data


# ---------------------------------------------------------------------------
# Additional size constants
# ---------------------------------------------------------------------------

# Animation/  (all ptrs = 4 bytes each)
ANIMATION_SIZE          = 16   # uint(4) + float(4) + ptr(4) + ptr(4)
ANIMATIONREFERENCE_SIZE =  0   # no fields

# Camera/
# Camera: ptr(4)+ushort(2)+ushort(2)+ushort[4](8)+ushort[4](8)+ptr(4)+ptr(4)+float(4)+ptr(4)+float(4)*4
CAMERA_SIZE             = 56   # 4+2+2+8+8+4+4+4+4+4+4+4+4
CAMERAANIMATION_SIZE    = 12   # ptr(4) + ptr(4) + ptr(4)
CAMERASET_SIZE          =  8   # ptr(4) + ptr(4)
VIEWPORT_SIZE           =  8   # ushort(2)*4

# Colors/ (all is_cachable=False, inline)
RGBACOLOR_SIZE          =  4   # uchar*4
RGB565COLOR_SIZE        =  2   # ushort
RGB5A3COLOR_SIZE        =  2   # ushort
RGBA4COLOR_SIZE         =  2   # ushort
RGBA6COLOR_SIZE         =  3   # uchar[3]
RGB8COLOR_SIZE          =  3   # uchar*3
RGBX8COLOR_SIZE         =  4   # uchar*4
I8COLOR_SIZE            =  1   # uchar
IA4COLOR_SIZE           =  1   # uchar
IA8COLOR_SIZE           =  2   # uchar*2

# Fog/
# Fog: uint(4)+ptr(4)+float(4)+float(4)+@RGBAColor(4 inline)
FOG_SIZE                = 20   # 4+4+4+4+4
FOGADJ_SIZE             =  0   # no fields

# Joints/
BONEREFERENCE_SIZE      =  8   # float(4)+float(4)
REFERENCE_SIZE          = 12   # ptr(4)+uint(4)+uint(4)
ENVELOPE_SIZE           =  8   # ptr(4)+float(4)
ENVELOPELIST_SIZE       =  0   # manual parsing, no struct header

# Light/
# Light: ptr(4)+ptr(4)+ushort(2)+ushort(2)+@RGBAColor(4)+ptr(4)+ptr(4)+uint(4)
LIGHT_SIZE              = 28   # 4+4+2+2+4+4+4+4
POINTLIGHT_SIZE         =  8   # float(4)+float(4)
# SpotLight: float(4)+uint(4)+float(4)+float(4)+uint(4)
SPOTLIGHT_SIZE          = 20   # 4+4+4+4+4
ATTN_SIZE               = 24   # vec3(12)+vec3(12)
LIGHTANIMATION_SIZE     = 16   # ptr(4)*4
LIGHTSET_SIZE           =  8   # ptr(4)+ptr(4)

# Material/
# Material: @RGBAColor(4)+@RGBAColor(4)+@RGBAColor(4)+float(4)+float(4)
MATERIAL_SIZE           = 20   # 4+4+4+4+4
MATERIALANIMATION_SIZE  = 16   # ptr(4)*4
MATERIALANIMATIONJOINT_SIZE = 12  # ptr(4)*3
# MaterialObject: ptr(4)+uint(4)+ptr(4)+ptr(4)+ptr(4)+ptr(4)
MATERIALOBJECT_SIZE     = 24   # 4+4+4+4+4+4

# Misc/
SLIST_SIZE              =  8   # ptr(4)+uint(4)

# Rendering/
# Render: ptr(4)+ptr(4)+uint(4)
RENDER_SIZE             = 12   # 4+4+4
RENDERANIMATION_SIZE    =  0   # no fields
# WObject: ptr(4)+vec3(12 inline)+ptr(4)
WOBJECT_SIZE            = 20   # 4+12+4
WOBJECTANIMATION_SIZE   =  8   # ptr(4)+ptr(4)
PIXELENGINE_SIZE        = 12   # uchar*12

# RootNodes/
SCENEDATA_SIZE          = 16   # ptr(4)*4
# BoundBox: ushort(2) + 2pad + uint(4)
BOUNDBOX_SIZE           =  8   # 2+2pad+4

# Shape/
SHAPEANIMATION_SIZE          =  8   # ptr(4)+ptr(4)
SHAPEANIMATIONJOINT_SIZE     = 12   # ptr(4)*3
SHAPEANIMATIONMESH_SIZE      =  8   # ptr(4)+ptr(4)
SHAPEINDEXTRI_SIZE           =  3   # uchar*3

# Texture/
IMAGE_SIZE              = 24   # uint(4)+ushort(2)+ushort(2)+uint(4)+uint(4)+float(4)+float(4)
# Palette: uint(4)+uint(4)+ptr(4)+ushort(2)
PALETTE_SIZE            = 14   # 4+4+4+2
# TextureLOD: uint(4)+float(4)+uchar(1)+uchar(1)+2pad+uint(4)
TEXTURELOD_SIZE         = 16   # 4+4+1+1+2+4
# TextureTEV: uchar*16 + @RGBX8Color(4)*3 + uint(4)
TEXTURETEV_SIZE         = 32   # 16+4+4+4+4
# TextureAnimation: ptr(4)+uint(4)+ptr(4)+ptr(4)+ptr(4)+ushort(2)+ushort(2)
TEXTUREANIMATION_SIZE   = 24   # 4+4+4+4+4+2+2
# Texture: ptr+ptr+uint+uint+vec3+vec3+vec3+uint+uint+uchar+uchar+2pad+uint+float+uint+ptr+ptr+ptr+ptr
TEXTURE_SIZE            = 92   # 4+4+4+4 + 12+12+12 + 4+4 + 1+1+2pad + 4+4+4 + 4+4+4+4


# ---------------------------------------------------------------------------
# Additional node binary builders
# ---------------------------------------------------------------------------

# ---- Animation/ ------------------------------------------------------------

def build_animation(flags=0, end_frame=0.0, frame_ptr=0, joint_ptr=0):
    """
    Build binary for one Animation struct (16 bytes).

      uint  flags      (4)
      float end_frame  (4)
      ptr   frame      (4)  → Frame node
      ptr   joint      (4)  → Joint node
    """
    data  = struct.pack('>I', flags)
    data += struct.pack('>f', end_frame)
    data += struct.pack('>I', frame_ptr)
    data += struct.pack('>I', joint_ptr)
    return data  # 16 bytes


def build_animation_reference():
    """AnimationReference has no fields; binary contribution is zero bytes."""
    return b''


# ---- Camera/ ---------------------------------------------------------------

def build_camera(name_ptr=0, flags=0, perspective_flags=0,
                 viewport=(0, 0, 0, 0), scissor=(0, 0, 0, 0),
                 position_ptr=0, interest_ptr=0, roll=0.0,
                 up_vector_ptr=0, near=0.0, far=0.0,
                 field_of_view=0.0, aspect=0.0):
    """
    Build binary for one Camera struct (56 bytes).

      ptr    name              (4)
      ushort flags             (2)
      ushort perspective_flags (2)
      ushort viewport[4]       (8)   inline bounded array
      ushort scissor[4]        (8)   inline bounded array
      ptr    position          (4)   → WObject
      ptr    interest          (4)   → WObject
      float  roll              (4)
      ptr    up_vector         (4)   → *vec3 explicit pointer
      float  near              (4)
      float  far               (4)
      float  field_of_view     (4)
      float  aspect            (4)
    """
    data  = struct.pack('>I',    name_ptr)
    data += struct.pack('>HH',   flags, perspective_flags)
    data += struct.pack('>4H',   *viewport)
    data += struct.pack('>4H',   *scissor)
    data += struct.pack('>I',    position_ptr)
    data += struct.pack('>I',    interest_ptr)
    data += struct.pack('>f',    roll)
    data += struct.pack('>I',    up_vector_ptr)
    data += struct.pack('>f',    near)
    data += struct.pack('>f',    far)
    data += struct.pack('>f',    field_of_view)
    data += struct.pack('>f',    aspect)
    return data  # 56 bytes


def build_camera_animation(animation_ptr=0, eye_position_ptr=0,
                           interest_ptr=0):
    """
    Build binary for one CameraAnimation struct (12 bytes).

      ptr  animation            (4)  → Animation
      ptr  eye_position_animation (4) → WObject
      ptr  interest_animation   (4)  → WObject
    """
    data  = struct.pack('>I', animation_ptr)
    data += struct.pack('>I', eye_position_ptr)
    data += struct.pack('>I', interest_ptr)
    return data  # 12 bytes


def build_camera_set(camera_ptr=0, animations_ptr=0):
    """
    Build binary for one CameraSet struct (8 bytes).

      ptr  camera     (4)  → Camera
      ptr  animations (4)  → CameraAnimation[] (null-terminated array pointer)
    """
    data  = struct.pack('>I', camera_ptr)
    data += struct.pack('>I', animations_ptr)
    return data  # 8 bytes


def build_viewport(ix=0, iw=0, iy=0, ih=0):
    """
    Build binary for one Viewport struct (8 bytes).

      ushort ix (2)
      ushort iw (2)
      ushort iy (2)
      ushort ih (2)
    """
    return struct.pack('>HHHH', ix, iw, iy, ih)  # 8 bytes


# ---- Colors/ (inline, is_cachable=False) -----------------------------------

def build_rgba_color(red=0, green=0, blue=0, alpha=0):
    """
    Build binary for one RGBAColor (4 bytes).

      uchar red   (1)
      uchar green (1)
      uchar blue  (1)
      uchar alpha (1)
    """
    return struct.pack('>BBBB', red, green, blue, alpha)  # 4 bytes


def build_rgb565_color(raw_value=0):
    """
    Build binary for one RGB565Color (2 bytes).

      ushort raw_value (2)
    """
    return struct.pack('>H', raw_value)  # 2 bytes


def build_rgb5a3_color(raw_value=0):
    """
    Build binary for one RGB5A3Color (2 bytes).

      ushort raw_value (2)
    """
    return struct.pack('>H', raw_value)  # 2 bytes


def build_rgba4_color(raw_value=0):
    """
    Build binary for one RGBA4Color (2 bytes).

      ushort raw_value (2)
    """
    return struct.pack('>H', raw_value)  # 2 bytes


def build_rgba6_color(raw_bytes=(0, 0, 0)):
    """
    Build binary for one RGBA6Color (3 bytes).

      uchar raw_bytes[3] (3)
    """
    return struct.pack('>BBB', *raw_bytes)  # 3 bytes


def build_rgb8_color(red=0, green=0, blue=0):
    """
    Build binary for one RGB8Color (3 bytes).

      uchar red   (1)
      uchar green (1)
      uchar blue  (1)
    """
    return struct.pack('>BBB', red, green, blue)  # 3 bytes


def build_rgbx8_color(red=0, green=0, blue=0):
    """
    Build binary for one RGBX8Color (4 bytes).  padding byte is always 0.

      uchar red     (1)
      uchar green   (1)
      uchar blue    (1)
      uchar padding (1)
    """
    return struct.pack('>BBBB', red, green, blue, 0)  # 4 bytes


def build_i8_color(intensity=0):
    """
    Build binary for one I8Color (1 byte).

      uchar intensity (1)
    """
    return struct.pack('>B', intensity)  # 1 byte


def build_ia4_color(raw_value=0):
    """
    Build binary for one IA4Color (1 byte).

      uchar raw_value (1)
    """
    return struct.pack('>B', raw_value)  # 1 byte


def build_ia8_color(alpha=0, intensity=0):
    """
    Build binary for one IA8Color (2 bytes).

      uchar alpha     (1)
      uchar intensity (1)
    """
    return struct.pack('>BB', alpha, intensity)  # 2 bytes


# ---- Fog/ ------------------------------------------------------------------

def build_fog(fog_type=0, adj_ptr=0, start_z=0.0, end_z=0.0,
              color_red=0, color_green=0, color_blue=0, color_alpha=0):
    """
    Build binary for one Fog struct (20 bytes).

      uint  type       (4)
      ptr   adj        (4)  → FogAdj
      float start_z    (4)
      float end_z      (4)
      @RGBAColor color (4)  inline (no pointer wrapping due to @)
        uchar red   (1)
        uchar green (1)
        uchar blue  (1)
        uchar alpha (1)
    """
    data  = struct.pack('>I', fog_type)
    data += struct.pack('>I', adj_ptr)
    data += struct.pack('>f', start_z)
    data += struct.pack('>f', end_z)
    data += struct.pack('>BBBB', color_red, color_green, color_blue, color_alpha)
    return data  # 20 bytes


def build_fog_adj():
    """FogAdj has no fields; binary contribution is zero bytes."""
    return b''


# ---- Joints/ ---------------------------------------------------------------

def build_bone_reference(length=0.0, pole_angle=0.0):
    """
    Build binary for one BoneReference struct (8 bytes).

      float length      (4)
      float pole_angle  (4)
    """
    data  = struct.pack('>f', length)
    data += struct.pack('>f', pole_angle)
    return data  # 8 bytes


def build_reference(next_ptr=0, flags=0, property_raw=0):
    """
    Build binary for one Reference (RObject) struct (12 bytes).

      ptr  next     (4)  → Reference
      uint flags    (4)
      uint property (4)  raw pointer, resolved in loadFromBinary
    """
    data  = struct.pack('>I', next_ptr)
    data += struct.pack('>I', flags)
    data += struct.pack('>I', property_raw)
    return data  # 12 bytes


def build_envelope(joint_ptr=0, weight=0.0):
    """
    Build binary for one Envelope struct (8 bytes).

      ptr   joint  (4)  → Joint
      float weight (4)
    """
    data  = struct.pack('>I', joint_ptr)
    data += struct.pack('>f', weight)
    return data  # 8 bytes


def build_envelope_list_terminator():
    """
    Build the 4-byte null sentinel that terminates an EnvelopeList.

    EnvelopeList.loadFromBinary reads Envelope records (8 bytes each) until
    joint pointer == 0.  A single null uint (4 bytes) is enough because the
    parser only checks the first 4-byte word (the joint pointer).
    """
    return struct.pack('>I', 0)  # 4 bytes


# ---- Light/ ----------------------------------------------------------------

def build_light(name_ptr=0, link_ptr=0, flags=0, attn_flags=0,
                color_red=0, color_green=0, color_blue=0, color_alpha=0,
                position_ptr=0, interest_ptr=0, property_raw=0):
    """
    Build binary for one Light struct (28 bytes).

      ptr    name      (4)  → string
      ptr    link      (4)  → Light (linked list)
      ushort flags     (2)
      ushort attn_flags(2)
      @RGBAColor color (4)  inline
        uchar red   (1)
        uchar green (1)
        uchar blue  (1)
        uchar alpha (1)
      ptr    position  (4)  → WObject
      ptr    interest  (4)  → WObject
      uint   property  (4)  raw pointer, resolved in loadFromBinary
    """
    data  = struct.pack('>I',    name_ptr)
    data += struct.pack('>I',    link_ptr)
    data += struct.pack('>HH',   flags, attn_flags)
    data += struct.pack('>BBBB', color_red, color_green, color_blue, color_alpha)
    data += struct.pack('>I',    position_ptr)
    data += struct.pack('>I',    interest_ptr)
    data += struct.pack('>I',    property_raw)
    return data  # 28 bytes


def build_point_light(reference_br=0.0, reference_distance=0.0):
    """
    Build binary for one PointLight struct (8 bytes).

      float reference_br       (4)
      float reference_distance (4)
    """
    data  = struct.pack('>f', reference_br)
    data += struct.pack('>f', reference_distance)
    return data  # 8 bytes


def build_spot_light(cutoff=0.0, spot_flags=0, reference_br=0.0,
                     reference_distance=0.0, distance_attn_flags=0):
    """
    Build binary for one SpotLight struct (20 bytes).

      float cutoff               (4)
      uint  spot_flags           (4)
      float reference_br         (4)
      float reference_distance   (4)
      uint  distance_attn_flags  (4)
    """
    data  = struct.pack('>f', cutoff)
    data += struct.pack('>I', spot_flags)
    data += struct.pack('>f', reference_br)
    data += struct.pack('>f', reference_distance)
    data += struct.pack('>I', distance_attn_flags)
    return data  # 20 bytes


def build_attn(angle=(0.0, 0.0, 0.0), distance=(0.0, 0.0, 0.0)):
    """
    Build binary for one Attn struct (24 bytes).

    vec3 is a primitive type (12 bytes inline — not pointer-wrapped).

      vec3 angle    (12)
      vec3 distance (12)
    """
    data  = struct.pack('>fff', *angle)
    data += struct.pack('>fff', *distance)
    return data  # 24 bytes


def build_light_animation(next_ptr=0, animation_ptr=0,
                          eye_position_ptr=0, interest_ptr=0):
    """
    Build binary for one LightAnimation struct (16 bytes).

      ptr  next                     (4)  → LightAnimation
      ptr  animation                (4)  → Animation
      ptr  eye_position_animation   (4)  → WObjectAnimation
      ptr  interest_animation       (4)  → WObjectAnimation
    """
    data  = struct.pack('>I', next_ptr)
    data += struct.pack('>I', animation_ptr)
    data += struct.pack('>I', eye_position_ptr)
    data += struct.pack('>I', interest_ptr)
    return data  # 16 bytes


def build_light_set(light_ptr=0, animations_ptr=0):
    """
    Build binary for one LightSet struct (8 bytes).

      ptr  light      (4)  → Light
      ptr  animations (4)  → LightAnimation[] (null-terminated array pointer)
    """
    data  = struct.pack('>I', light_ptr)
    data += struct.pack('>I', animations_ptr)
    return data  # 8 bytes


# ---- Material/ -------------------------------------------------------------

def build_material(ambient=(0, 0, 0, 0), diffuse=(0, 0, 0, 0),
                   specular=(0, 0, 0, 0), alpha=0.0, shininess=0.0):
    """
    Build binary for one Material struct (20 bytes).

    All three color fields use @RGBAColor — inline (no pointer wrapping).

      @RGBAColor ambient   (4)  [r, g, b, a] uchar each
      @RGBAColor diffuse   (4)
      @RGBAColor specular  (4)
      float      alpha     (4)
      float      shininess (4)
    """
    data  = struct.pack('>BBBB', *ambient)
    data += struct.pack('>BBBB', *diffuse)
    data += struct.pack('>BBBB', *specular)
    data += struct.pack('>f', alpha)
    data += struct.pack('>f', shininess)
    return data  # 20 bytes


def build_material_animation(next_ptr=0, animation_ptr=0,
                             texture_animation_ptr=0, render_animation_ptr=0):
    """
    Build binary for one MaterialAnimation struct (16 bytes).

      ptr  next               (4)  → MaterialAnimation
      ptr  animation          (4)  → Animation
      ptr  texture_animation  (4)  → TextureAnimation
      ptr  render_animation   (4)  → RenderAnimation
    """
    data  = struct.pack('>I', next_ptr)
    data += struct.pack('>I', animation_ptr)
    data += struct.pack('>I', texture_animation_ptr)
    data += struct.pack('>I', render_animation_ptr)
    return data  # 16 bytes


def build_material_animation_joint(child_ptr=0, next_ptr=0, animation_ptr=0):
    """
    Build binary for one MaterialAnimationJoint struct (12 bytes).

      ptr  child     (4)  → MaterialAnimationJoint
      ptr  next      (4)  → MaterialAnimationJoint
      ptr  animation (4)  → MaterialAnimation
    """
    data  = struct.pack('>I', child_ptr)
    data += struct.pack('>I', next_ptr)
    data += struct.pack('>I', animation_ptr)
    return data  # 12 bytes


def build_material_object(class_type_ptr=0, render_mode=0, texture_ptr=0,
                          material_ptr=0, render_data_ptr=0,
                          pixel_engine_data_ptr=0):
    """
    Build binary for one MaterialObject (MObject) struct (24 bytes).

      ptr  class_type        (4)  → string
      uint render_mode       (4)
      ptr  texture           (4)  → Texture
      ptr  material          (4)  → Material
      ptr  render_data       (4)  → Render
      ptr  pixel_engine_data (4)  → PixelEngine
    """
    data  = struct.pack('>I', class_type_ptr)
    data += struct.pack('>I', render_mode)
    data += struct.pack('>I', texture_ptr)
    data += struct.pack('>I', material_ptr)
    data += struct.pack('>I', render_data_ptr)
    data += struct.pack('>I', pixel_engine_data_ptr)
    return data  # 24 bytes


# ---- Misc/ -----------------------------------------------------------------

def build_slist(next_ptr=0, data=0):
    """
    Build binary for one SList struct (8 bytes).

      ptr  next (4)  → SList
      uint data (4)
    """
    d  = struct.pack('>I', next_ptr)
    d += struct.pack('>I', data)
    return d  # 8 bytes


# ---- Rendering/ ------------------------------------------------------------

def build_render(toon_texture_ptr=0, grad_texture_ptr=0, terminator=0):
    """
    Build binary for one Render struct (12 bytes).

      ptr  toon_texture (4)  → Texture
      ptr  grad_texture (4)  → Texture
      uint terminator   (4)
    """
    data  = struct.pack('>I', toon_texture_ptr)
    data += struct.pack('>I', grad_texture_ptr)
    data += struct.pack('>I', terminator)
    return data  # 12 bytes


def build_render_animation(next_ptr=0, animation_ptr=0):
    """
    Build binary for one RenderAnimation struct (8 bytes).

    HSD_ROBJAnimJoint: linked list of animation objects for Reference Objects.

      ptr  next      (4)  → RenderAnimation
      ptr  animation (4)  → Animation
    """
    data  = struct.pack('>I', next_ptr)
    data += struct.pack('>I', animation_ptr)
    return data  # 8 bytes


def build_wobject(name_ptr=0, position=(0.0, 0.0, 0.0), render_ptr=0):
    """
    Build binary for one WObject struct (20 bytes).

    vec3 is a primitive (12 bytes inline, NOT pointer-wrapped).

      ptr  name     (4)  → string
      vec3 position (12) inline
      ptr  render   (4)  → Render
    """
    data  = struct.pack('>I',   name_ptr)
    data += struct.pack('>fff', *position)
    data += struct.pack('>I',   render_ptr)
    return data  # 20 bytes


def build_wobject_animation(animation_ptr=0, render_animation_ptr=0):
    """
    Build binary for one WObjectAnimation struct (8 bytes).

      ptr  animation        (4)  → Animation
      ptr  render_animation (4)  → RenderAnimation
    """
    data  = struct.pack('>I', animation_ptr)
    data += struct.pack('>I', render_animation_ptr)
    return data  # 8 bytes


def build_pixel_engine(flags=0, reference_0=0, reference_1=0,
                       destination_alpha=0, pe_type=0, source_factor=0,
                       destination_factor=0, logic_op=0, z_comp=0,
                       alpha_component_0=0, alpha_op=0, alpha_component_1=0):
    """
    Build binary for one PixelEngine (PE) struct (12 bytes).

      uchar flags              (1)
      uchar reference_0        (1)
      uchar reference_1        (1)
      uchar destination_alpha  (1)
      uchar type               (1)
      uchar source_factor      (1)
      uchar destination_factor (1)
      uchar logic_op           (1)
      uchar z_comp             (1)
      uchar alpha_component_0  (1)
      uchar alpha_op           (1)
      uchar alpha_component_1  (1)
    """
    return struct.pack('>BBBBBBBBBBBB',
                       flags, reference_0, reference_1, destination_alpha,
                       pe_type, source_factor, destination_factor, logic_op,
                       z_comp, alpha_component_0, alpha_op,
                       alpha_component_1)  # 12 bytes


# ---- RootNodes/ ------------------------------------------------------------

def build_scene_data(models_ptr=0, camera_ptr=0, lights_ptr=0, fog_ptr=0):
    """
    Build binary for one SceneData struct (16 bytes).

      ptr  models (4)  → ModelSet[] (null-terminated array pointer)
      ptr  camera (4)  → CameraSet
      ptr  lights (4)  → LightSet[] (null-terminated array pointer)
      ptr  fog    (4)  → Fog
    """
    data  = struct.pack('>I', models_ptr)
    data += struct.pack('>I', camera_ptr)
    data += struct.pack('>I', lights_ptr)
    data += struct.pack('>I', fog_ptr)
    return data  # 16 bytes


def build_bound_box(unknown_1=0, unknown_2=0):
    """
    Build binary for one BoundBox struct (8 bytes).

    Alignment: ushort at offset 0, then uint must align to 4 → 2 bytes padding.

      ushort unknown_1 (2)
      <pad>            (2)
      uint   unknown_2 (4)
    """
    data  = struct.pack('>H', unknown_1)
    data += b'\x00\x00'           # alignment padding
    data += struct.pack('>I', unknown_2)
    return data  # 8 bytes


# ---- Shape/ ----------------------------------------------------------------

def build_shape_animation(next_ptr=0, animation_ptr=0):
    """
    Build binary for one ShapeAnimation struct (8 bytes).

      ptr  next      (4)  → ShapeAnimation
      ptr  animation (4)  → Animation
    """
    data  = struct.pack('>I', next_ptr)
    data += struct.pack('>I', animation_ptr)
    return data  # 8 bytes


def build_shape_animation_joint(child_ptr=0, next_ptr=0, animation_ptr=0):
    """
    Build binary for one ShapeAnimationJoint struct (12 bytes).

      ptr  child     (4)  → ShapeAnimationJoint
      ptr  next      (4)  → ShapeAnimationJoint
      ptr  animation (4)  → ShapeAnimation
    """
    data  = struct.pack('>I', child_ptr)
    data += struct.pack('>I', next_ptr)
    data += struct.pack('>I', animation_ptr)
    return data  # 12 bytes


def build_shape_animation_mesh(next_ptr=0, animation_ptr=0):
    """
    Build binary for one ShapeAnimationMesh struct (8 bytes).

      ptr  next      (4)  → ShapeAnimationMesh
      ptr  animation (4)  → ShapeAnimation
    """
    data  = struct.pack('>I', next_ptr)
    data += struct.pack('>I', animation_ptr)
    return data  # 8 bytes


def build_shape_index_tri(id0=0, id1=0, id2=0):
    """
    Build binary for one ShapeIndexTri struct (3 bytes).

      uchar id0 (1)
      uchar id1 (1)
      uchar id2 (1)
    """
    return struct.pack('>BBB', id0, id1, id2)  # 3 bytes


# ---- Texture/ --------------------------------------------------------------

def build_image(data_address=0, width=0, height=0, fmt=0,
                mipmap=0, min_lod=0.0, max_lod=0.0):
    """
    Build binary for one Image struct (24 bytes).

      uint   data_address (4)
      ushort width        (2)
      ushort height       (2)
      uint   format       (4)
      uint   mipmap       (4)
      float  minLOD       (4)
      float  maxLOD       (4)
    """
    data  = struct.pack('>I',  data_address)
    data += struct.pack('>HH', width, height)
    data += struct.pack('>I',  fmt)
    data += struct.pack('>I',  mipmap)
    data += struct.pack('>f',  min_lod)
    data += struct.pack('>f',  max_lod)
    return data  # 24 bytes


def build_palette(data_address=0, fmt=0, table_name_ptr=0, entry_count=0):
    """
    Build binary for one Palette (TLUT) struct (14 bytes).

      uint   data        (4)  raw data address
      uint   format      (4)
      ptr    table_name  (4)  → string
      ushort entry_count (2)
    """
    data  = struct.pack('>I', data_address)
    data += struct.pack('>I', fmt)
    data += struct.pack('>I', table_name_ptr)
    data += struct.pack('>H', entry_count)
    return data  # 14 bytes


def build_texture_lod(min_filter=0, lod_bias=0.0,
                      bias_clamp=0, enable_edge_lod=0,
                      max_anisotropy=0):
    """
    Build binary for one TextureLOD struct (16 bytes).

    Alignment: two uchars land at offset 8–9; uint must align to 4 → 2 pad bytes.

      uint   min_filter     (4)
      float  LOD_bias       (4)
      uchar  bias_clamp     (1)
      uchar  enable_edge_LOD(1)
      <pad>                 (2)
      uint   max_anisotropy (4)
    """
    data  = struct.pack('>I',  min_filter)
    data += struct.pack('>f',  lod_bias)
    data += struct.pack('>BB', bias_clamp, enable_edge_lod)
    data += b'\x00\x00'         # alignment padding
    data += struct.pack('>I',  max_anisotropy)
    return data  # 16 bytes


def build_texture_tev(color_op=0, alpha_op=0, color_bias=0, alpha_bias=0,
                      color_scale=0, alpha_scale=0, color_clamp=0,
                      alpha_clamp=0, color_a=0, color_b=0, color_c=0,
                      color_d=0, alpha_a=0, alpha_b=0, alpha_c=0, alpha_d=0,
                      konst=(0, 0, 0), tev0=(0, 0, 0), tev1=(0, 0, 0),
                      active=0):
    """
    Build binary for one TextureTEV struct (32 bytes).

      uchar  color_op     (1)
      uchar  alpha_op     (1)
      uchar  color_bias   (1)
      uchar  alpha_bias   (1)
      uchar  color_scale  (1)
      uchar  alpha_scale  (1)
      uchar  color_clamp  (1)
      uchar  alpha_clamp  (1)
      uchar  color_a      (1)
      uchar  color_b      (1)
      uchar  color_c      (1)
      uchar  color_d      (1)
      uchar  alpha_a      (1)
      uchar  alpha_b      (1)
      uchar  alpha_c      (1)
      uchar  alpha_d      (1)   ← 16 bytes of uchars
      @RGBX8Color konst   (4)  inline [r, g, b, pad=0]
      @RGBX8Color tev0    (4)  inline
      @RGBX8Color tev1    (4)  inline
      uint   active       (4)
    """
    data  = struct.pack('>BBBBBBBBBBBBBBBB',
                        color_op, alpha_op, color_bias, alpha_bias,
                        color_scale, alpha_scale, color_clamp, alpha_clamp,
                        color_a, color_b, color_c, color_d,
                        alpha_a, alpha_b, alpha_c, alpha_d)
    # @RGBX8Color: 3 color bytes + 1 padding byte each
    data += struct.pack('>BBBB', konst[0], konst[1], konst[2], 0)
    data += struct.pack('>BBBB', tev0[0],  tev0[1],  tev0[2],  0)
    data += struct.pack('>BBBB', tev1[0],  tev1[1],  tev1[2],  0)
    data += struct.pack('>I',    active)
    return data  # 32 bytes


def build_texture_animation(next_ptr=0, tex_id=0, animation_ptr=0,
                            image_table_ptr=0, palette_table_ptr=0,
                            image_table_count=0, palette_table_count=0):
    """
    Build binary for one TextureAnimation struct (24 bytes).

      ptr    next                (4)  → TextureAnimation
      uint   id                  (4)
      ptr    animation           (4)  → Animation
      ptr    image_table         (4)  → *(Image[image_table_count])
      ptr    palette_table       (4)  → *(Palette[palette_table_count])
      ushort image_table_count   (2)
      ushort palette_table_count (2)
    """
    data  = struct.pack('>I', next_ptr)
    data += struct.pack('>I', tex_id)
    data += struct.pack('>I', animation_ptr)
    data += struct.pack('>I', image_table_ptr)
    data += struct.pack('>I', palette_table_ptr)
    data += struct.pack('>HH', image_table_count, palette_table_count)
    return data  # 24 bytes


def build_texture(name_ptr=0, next_ptr=0, texture_id=0, source=0,
                  rotation=(0.0, 0.0, 0.0), scale=(0.0, 0.0, 0.0),
                  translation=(0.0, 0.0, 0.0),
                  wrap_s=0, wrap_t=0, repeat_s=0, repeat_t=0,
                  flags=0, blending=0.0, mag_filter=0,
                  image_ptr=0, palette_ptr=0, lod_ptr=0, tev_ptr=0):
    """
    Build binary for one Texture (TObject) struct (92 bytes).

    Alignment note: repeat_s and repeat_t are uchars at offset 60–61.
    The following 'flags' field is a uint that must align to 4 → 2 pad bytes.

      ptr    name        (4)
      ptr    next        (4)  → Texture
      uint   texture_id  (4)
      uint   source      (4)
      vec3   rotation    (12) inline
      vec3   scale       (12) inline
      vec3   translation (12) inline
      uint   wrap_s      (4)
      uint   wrap_t      (4)
      uchar  repeat_s    (1)
      uchar  repeat_t    (1)
      <pad>              (2)
      uint   flags       (4)
      float  blending    (4)
      uint   mag_filter  (4)
      ptr    image       (4)  → Image
      ptr    palette     (4)  → Palette
      ptr    lod         (4)  → TextureLOD
      ptr    tev         (4)  → TextureTEV
    """
    data  = struct.pack('>I',   name_ptr)
    data += struct.pack('>I',   next_ptr)
    data += struct.pack('>I',   texture_id)
    data += struct.pack('>I',   source)
    data += struct.pack('>fff', *rotation)
    data += struct.pack('>fff', *scale)
    data += struct.pack('>fff', *translation)
    data += struct.pack('>I',   wrap_s)
    data += struct.pack('>I',   wrap_t)
    data += struct.pack('>BB',  repeat_s, repeat_t)
    data += b'\x00\x00'         # alignment padding before flags (uint)
    data += struct.pack('>I',   flags)
    data += struct.pack('>f',   blending)
    data += struct.pack('>I',   mag_filter)
    data += struct.pack('>I',   image_ptr)
    data += struct.pack('>I',   palette_ptr)
    data += struct.pack('>I',   lod_ptr)
    data += struct.pack('>I',   tev_ptr)
    return data  # 92 bytes
