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


def build_vertex_list_terminator():
    """
    Build a single Vertex sentinel that ends a VertexList (24 bytes).

    VertexList.loadFromBinary reads Vertex records until attribute == 0xFF.
    Setting attribute=0xFF with all other fields zero immediately terminates
    the list, leaving vertices=[].

      uint   attribute      (4)  = 0xFF
      uint   attribute_type (4)  = 0
      uint   component_count(4)  = 0
      uint   component_type (4)  = 0
      uchar  component_frac (1)  = 0
      uchar  <pad>          (1)
      ushort stride         (2)  = 0
      uint   base_pointer   (4)  = 0
    """
    data  = struct.pack('>I', 0xFF)   # attribute = 255 → list terminator
    data += struct.pack('>I', 0)      # attribute_type
    data += struct.pack('>I', 0)      # component_count
    data += struct.pack('>I', 0)      # component_type
    data += struct.pack('>B', 0)      # component_frac
    data += b'\x00'                   # alignment pad (stride is ushort → align 2)
    data += struct.pack('>H', 0)      # stride
    data += struct.pack('>I', 0)      # base_pointer
    return data  # 24 bytes
