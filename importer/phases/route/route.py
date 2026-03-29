"""Phase 2 — Section Routing: DAT bytes → section name→type map.

Reads the archive header and section metadata from raw DAT bytes
to determine which node type each section should be parsed as.
"""
try:
    from ....shared.helpers.binary import read, read_many
    from ....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.binary import read, read_many
    from shared.helpers.logger import StubLogger

# Default section name → node type mapping rules (checked in order)
_DEFAULT_RULES = [
    # (match_mode, pattern, node_type)
    ('exact', 'scene_data', 'SceneData'),
    ('exact', 'bound_box', 'BoundBox'),
    ('exact', 'scene_camera', 'CameraSet'),
    ('contains', 'shapeanim_joint', 'ShapeAnimationJoint'),
    ('contains', 'matanim_joint', 'MaterialAnimationJoint'),
    ('contains', '_joint', 'Joint'),
]


def route_sections(dat_bytes, user_overrides=None, logger=StubLogger()):
    """Map section names to node types from raw DAT bytes.

    Args:
        dat_bytes: Raw DAT binary (no container header).
        user_overrides: Optional dict of {section_name: node_type} overrides.
        logger: Logger instance.

    Returns:
        dict of {section_name: node_type_name} for all sections.
    """
    section_names = _read_section_names(dat_bytes)

    section_map = {}
    for name in section_names:
        # Check user overrides first
        if user_overrides and name in user_overrides:
            section_map[name] = user_overrides[name]
            continue

        # Apply default rules
        node_type = _resolve_type(name)
        section_map[name] = node_type

    logger.info("Routed %d section(s): %s", len(section_map), section_map)
    return section_map


def _resolve_type(section_name):
    """Resolve a section name to a node type using default rules."""
    lower = section_name.lower()
    for mode, pattern, node_type in _DEFAULT_RULES:
        if mode == 'exact' and lower == pattern:
            return node_type
        elif mode == 'contains' and pattern in lower:
            return node_type
    return 'Dummy'


def _read_section_names(dat_bytes):
    """Read section name strings from the DAT binary.

    Parses the archive header to find the section info table,
    then reads the name strings.
    """
    if len(dat_bytes) < 32:
        return []

    # Archive header: file_size(4) data_size(4) reloc_count(4) pub_count(4) ext_count(4) pad(12)
    file_size, data_size, reloc_count, pub_count, ext_count = read_many('uint', 5, dat_bytes, 0)

    total_sections = pub_count + ext_count
    if total_sections == 0:
        return []

    # Section info starts after: header(32) + data_section + relocation_table
    section_info_offset = 32 + data_size + reloc_count * 4

    # Section names string block starts after all section info entries (8 bytes each)
    names_block_offset = section_info_offset + total_sections * 8

    names = []
    for i in range(total_sections):
        entry_offset = section_info_offset + i * 8
        if entry_offset + 8 > len(dat_bytes):
            break

        # Each entry: root_offset(4) + name_string_offset(4)
        _, name_str_offset = read_many('uint', 2, dat_bytes, entry_offset)

        # Read null-terminated string
        abs_offset = names_block_offset + name_str_offset
        end = dat_bytes.index(0, abs_offset) if abs_offset < len(dat_bytes) else abs_offset
        name = dat_bytes[abs_offset:end].decode('ascii', errors='replace')
        names.append(name)

    return names
