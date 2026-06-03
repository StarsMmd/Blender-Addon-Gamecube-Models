"""Tests for Phase 2 — Section Routing."""
import struct
from importer.phases.route.route import (
    route_sections, _resolve_type, _RULES_COLO_XD, _RULES_OTHER, _RULES_KIRBY_AIR_RIDE,
)


def _resolve_type_default(name):
    """The historical permissive ruleset, now exposed as the OTHER game."""
    return _resolve_type(name, _RULES_OTHER)


def _resolve_type_colo_xd(name):
    return _resolve_type(name, _RULES_COLO_XD)


def _resolve_type_kirby(name):
    return _resolve_type(name, _RULES_KIRBY_AIR_RIDE)


class TestResolveType:

    def test_scene_data(self):
        assert _resolve_type_default('scene_data') == 'SceneData'

    def test_bound_box(self):
        assert _resolve_type_default('bound_box') == 'BoundBox'

    def test_scene_camera(self):
        assert _resolve_type_default('scene_camera') == 'CameraSet'

    def test_joint(self):
        assert _resolve_type_default('model_joint') == 'Joint'

    def test_matanim_joint(self):
        assert _resolve_type_default('model_matanim_joint') == 'MaterialAnimationJoint'

    def test_shapeanim_joint(self):
        assert _resolve_type_default('some_shapeanim_joint') == 'ShapeAnimationJoint'

    def test_joint_priority_over_partial(self):
        """'_joint' should not match 'shapeanim_joint' (checked first)."""
        assert _resolve_type_default('foo_shapeanim_joint') == 'ShapeAnimationJoint'

    def test_unknown_section(self):
        assert _resolve_type_default('unknown_thing') == 'Dummy'

    def test_case_insensitive(self):
        assert _resolve_type_default('Scene_Data') == 'SceneData'  # exact match uses .lower()
        assert _resolve_type_default('FOO_JOINT') == 'Joint'       # contains match is case-insensitive


class TestResolveTypeColoXD:
    """Colosseum / XD only routes scene_data and bound_box; everything else
    falls back to Dummy, mirroring how the runtime actually consumes those
    containers (joint roots are reached through scene_data, not by name)."""

    def test_scene_data(self):
        assert _resolve_type_colo_xd('scene_data') == 'SceneData'

    def test_bound_box(self):
        assert _resolve_type_colo_xd('bound_box') == 'BoundBox'

    def test_joint_falls_back_to_dummy(self):
        assert _resolve_type_colo_xd('model_joint') == 'Dummy'

    def test_scene_camera_falls_back_to_dummy(self):
        assert _resolve_type_colo_xd('scene_camera') == 'Dummy'


class TestRouteWithOverrides:

    def test_user_override(self):
        """Build a minimal DAT with one section to test routing with overrides."""
        # Build a minimal DAT binary with one section named "test_section"
        section_name = b'test_section\x00'
        # Header: file_size, data_size=0, reloc_count=0, pub_count=1, ext_count=0, pad(12)
        data_size = 0
        reloc_count = 0
        pub_count = 1
        ext_count = 0
        section_info = struct.pack('>II', 0, 0)  # root_offset=0, name_str_offset=0
        total = 32 + data_size + reloc_count * 4 + len(section_info) + len(section_name)
        header = struct.pack('>5I', total, data_size, reloc_count, pub_count, ext_count)
        header += b'\x00' * 12
        dat_bytes = header + section_info + section_name

        result = route_sections(dat_bytes, user_overrides={'test_section': 'MyCustomType'})
        assert result['test_section'] == 'MyCustomType'


class TestResolveTypeKirby:
    """Kirby Air Ride uses suffix-based rules. These cases come from a scan
    of the retail dump's public symbol tables."""

    def test_animjoint_suffix(self):
        assert _resolve_type_kirby('body_eff_animjoint') == 'AnimationJoint'

    def test_cmpatree_suffix(self):
        assert _resolve_type_kirby('rdMotionKirby_Jump_cmpatree') == 'AnimationJoint'

    def test_figatree_suffix_still_routes(self):
        assert _resolve_type_kirby('something_figatree') == 'AnimationJoint'

    def test_joint_suffix(self):
        assert _resolve_type_kirby('Ending_0_joint') == 'Joint'

    def test_camanim_suffix(self):
        assert _resolve_type_kirby('EndingCt_camanim') == 'CameraAnimation'

    def test_lights_suffix_routes_to_light_set(self):
        """Smash exposes light-set roots as `<namespace>_lights` (plural) —
        must route to LightSet, NOT Light."""
        assert _resolve_type_kirby('GrSt_TopN_lights') == 'LightSet'
        assert _resolve_type_kirby('PlMr_lights') == 'LightSet'

    def test_lights_does_not_match_light_singular_rule(self):
        """`_lights` rule comes before `_light`; both end in different suffixes
        and shouldn't overlap due to length differences. Verify ordering."""
        assert _resolve_type_kirby('foo_light') == 'Light'
        assert _resolve_type_kirby('foo_lights') == 'LightSet'

    def test_smash_namespaced_scene_data(self):
        """Smash files use `<NameSpace>_scene_data` and `_scene_models` for
        what Colo/XD calls plain `scene_data`."""
        assert _resolve_type_kirby('ScNtcApproach_scene_data') == 'SceneData'
        assert _resolve_type_kirby('ScItrAllstar_scene_data') == 'SceneData'
        assert _resolve_type_kirby('ScInfCnt_scene_models') == 'SceneData'

    def test_scene_data_still_works(self):
        assert _resolve_type_kirby('scene_data') == 'SceneData'

    def test_animjoint_not_swallowed_by_joint(self):
        """'_animjoint' must win over '_joint' — suffix rule ordering matters."""
        assert _resolve_type_kirby('x_animjoint') == 'AnimationJoint'

    def test_matanim_suffix(self):
        assert _resolve_type_kirby('mat_matanim_joint') == 'MaterialAnimationJoint'

    def test_em_data_group_routed(self):
        """Kirby enemy 'em<Species>DataGroup' symbols decode via KirbyDataGroup
        (DataGroup → variant → ModelRef → Joint, layout reverse-engineered from
        KAR's main.dol — see memory/reference_kar_disassembly.md)."""
        assert _resolve_type_kirby('emScarfyDataGroup') == 'KirbyDataGroup'
        assert _resolve_type_kirby('emCappyDataGroup') == 'KirbyDataGroup'
        assert _resolve_type_kirby('emBombboneDataGroup') == 'KirbyDataGroup'

    def test_other_kirby_top_level_falls_through(self):
        """Kirby's other engine top-level structs (grData/rdData/vsData)
        are not yet decoded and should fall through to Dummy."""
        assert _resolve_type_kirby('grDataCity1') == 'Dummy'
        assert _resolve_type_kirby('rdDataKirby') == 'Dummy'
        assert _resolve_type_kirby('vsDataHydra') == 'Dummy'


class TestGameParameter:
    """route_sections selects a rule set from the game parameter."""

    @staticmethod
    def _make_dat(section_name):
        name_bytes = section_name.encode('ascii') + b'\x00'
        section_info = struct.pack('>II', 0, 0)
        total = 32 + len(section_info) + len(name_bytes)
        header = struct.pack('>5I', total, 0, 0, 1, 0) + b'\x00' * 12
        return header + section_info + name_bytes

    def test_colo_xd_does_not_apply_kirby_suffix(self):
        """'_animjoint' has no Colo/XD rule — falls through to Dummy."""
        dat = self._make_dat('foo_animjoint')
        assert route_sections(dat, game='COLO_XD')['foo_animjoint'] == 'Dummy'

    def test_kirby_applies_kirby_suffix(self):
        dat = self._make_dat('foo_animjoint')
        assert route_sections(dat, game='KIRBY_AIR_RIDE')['foo_animjoint'] == 'AnimationJoint'

    def test_smash_matches_colo_xd(self):
        """Smash rules mirror Colo/XD for now."""
        dat = self._make_dat('model_joint')
        assert route_sections(dat, game='SMASH_BROS')['model_joint'] == 'Joint'

    def test_default_is_colo_xd(self):
        dat = self._make_dat('foo_animjoint')
        assert route_sections(dat)['foo_animjoint'] == 'Dummy'
