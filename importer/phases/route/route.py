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

# Game-of-origin ids accepted by route_sections. Keep these strings aligned
# with the EnumProperty in BlenderPlugin.ImportHSD.game.
GAME_COLO_XD = 'COLO_XD'
GAME_KIRBY_AIR_RIDE = 'KIRBY_AIR_RIDE'
GAME_SMASH_BROS = 'SMASH_BROS'
GAME_OTHER = 'OTHER'

# Colosseum / XD — the only public sections the runtime ever routes are
# scene_data and bound_box. Anything else in a Colo/XD container is either
# a sibling root (joints, animations) reached through scene_data, or a
# dummy/string section. Restrict accordingly so misnamed sections do not
# silently route to Joint via the permissive _joint contains-rule.
_RULES_COLO_XD = [
    ('exact', 'scene_data', 'SceneData'),
    ('exact', 'bound_box', 'BoundBox'),
]

# "Other" — generic name-pattern routing used when the file is a raw DAT
# from an unsupported or unknown game. This is the historical permissive
# ruleset that previously served Colo/XD as well.
_RULES_OTHER = [
    ('exact', 'scene_data', 'SceneData'),
    ('exact', 'bound_box', 'BoundBox'),
    ('exact', 'scene_camera', 'CameraSet'),
    ('contains', 'shapeanim_joint', 'ShapeAnimationJoint'),
    ('contains', 'matanim_joint', 'MaterialAnimationJoint'),
    ('contains', '_joint', 'Joint'),
]

# Kirby Air Ride — suffix-based convention derived from a full scan of the
# retail dump's public symbol tables. See the section-name analysis in
# documentation/implementation_notes.md and the DataGroup decode in
# memory/reference_kar_disassembly.md.
_RULES_KIRBY_AIR_RIDE = [
    ('exact', 'scene_data', 'SceneData'),
    ('exact', 'bound_box', 'BoundBox'),
    ('exact', 'scene_camera', 'CameraSet'),
    # Smash uses `<NameSpace>_scene_data` and `<NameSpace>_scene_models` for
    # the same SceneData root that Colo/XD names exactly `scene_data`.
    ('endswith', '_scene_data', 'SceneData'),
    ('endswith', '_scene_models', 'SceneData'),
    ('endswith', '_shapeanim_joint', 'ShapeAnimationJoint'),
    ('endswith', '_matanim_joint', 'MaterialAnimationJoint'),
    ('endswith', '_animjoint', 'AnimationJoint'),
    ('endswith', '_cmpatree', 'AnimationJoint'),
    ('endswith', '_figatree', 'AnimationJoint'),
    ('endswith', '_camanim', 'CameraAnimation'),
    ('endswith', '_joint', 'Joint'),
    ('endswith', '_camera', 'Camera'),
    # `_lights` (plural) must come before `_light` (singular) — both end in
    # the same characters but have different lengths and meanings (LightSet
    # vs Light). endswith matches by full suffix length, so they don't
    # overlap, but the rule order is documented for clarity.
    ('endswith', '_lights', 'LightSet'),
    ('endswith', '_light', 'Light'),
    ('endswith', '_fog', 'Fog'),
    ('endswith', '_image', 'Image'),
    ('endswith', '_tlut', 'Palette'),
    # Kirby enemy bundle struct — every Em*Data.dat exports a public symbol
    # named em<Species>DataGroup that is a KirbyDataGroup wrapping 1-3 model
    # variants. The JObj root is reached via DataGroup → variant[0] → +0x08
    # (KirbyModelRef) → +0x00.
    ('endswith', 'datagroup', 'KirbyDataGroup'),
]

# Smash Bros (Melee) — kept identical to the permissive ruleset until proper
# analysis lands.
_RULES_SMASH_BROS = list(_RULES_OTHER)

_RULES_BY_GAME = {
    GAME_COLO_XD: _RULES_COLO_XD,
    GAME_KIRBY_AIR_RIDE: _RULES_KIRBY_AIR_RIDE,
    GAME_SMASH_BROS: _RULES_SMASH_BROS,
    GAME_OTHER: _RULES_OTHER,
}


def route_sections(dat_bytes, user_overrides=None, game=None, logger=StubLogger()):
    """Map each DAT section name to a node type name using per-game rules + overrides.

    In: dat_bytes (bytes, raw DAT, no container header); user_overrides (dict[str,str]|None, exact name→type overrides); game (str|None, one of GAME_COLO_XD / GAME_KIRBY_AIR_RIDE / GAME_SMASH_BROS; defaults to Colo/XD); logger (Logger, defaults to StubLogger).
    Out: dict[str, str], section_name → node_type_name (e.g. 'Joint', 'SceneData', 'Dummy' fallback).
    """
    rules = _RULES_BY_GAME.get(game or GAME_COLO_XD, _RULES_COLO_XD)

    section_names = _read_section_names(dat_bytes)

    section_map = {}
    for name in section_names:
        if user_overrides and name in user_overrides:
            section_map[name] = user_overrides[name]
            continue

        section_map[name] = _resolve_type(name, rules)

    logger.info("Routed %d section(s) [game=%s]: %s",
                len(section_map), game or GAME_COLO_XD, section_map)
    return section_map


def _resolve_type(section_name, rules):
    """Resolve a section name to a node type using the given rules table.

    In: section_name (str, any); rules (list[tuple], (match_mode, pattern, node_type)).
    Out: str, node type name (falls back to 'Dummy' if no rule matches).
    """
    lower = section_name.lower()
    for mode, pattern, node_type in rules:
        if mode == 'exact' and lower == pattern:
            return node_type
        if mode == 'contains' and pattern in lower:
            return node_type
        if mode == 'endswith' and lower.endswith(pattern):
            return node_type
    return 'Dummy'


def _read_section_names(dat_bytes):
    """Read section name strings from the DAT archive header + section info table.

    In: dat_bytes (bytes, raw DAT; <32 bytes returns empty).
    Out: list[str], one name per public+external section, in archive order.
    """
    if len(dat_bytes) < 32:
        return []

    # Archive header: file_size(4) data_size(4) reloc_count(4) pub_count(4) ext_count(4) pad(12)
    file_size, data_size, reloc_count, pub_count, ext_count = read_many('uint', 5, dat_bytes, 0)

    # Guard against malformed headers: if the declared section/reloc region
    # overflows the file, bail out so Phase 3 doesn't deref a wild pointer.
    # (Kirby Air Ride 'A2' containers are filtered out upstream in the
    # extract phase — see _sniff_a2_container.)
    expected_end = 32 + data_size + reloc_count * 4 + (pub_count + ext_count) * 8
    if expected_end > len(dat_bytes):
        raise ValueError(
            "DAT header describes section/reloc regions that run past the end of the file "
            "(header says data=0x%X + reloc*4=0x%X + section_info=0x%X; file is 0x%X bytes)." % (
                data_size, reloc_count * 4, (pub_count + ext_count) * 8, len(dat_bytes),
            )
        )

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
