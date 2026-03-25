"""Tests for Phase 2 — Section Routing."""
import struct
from importer.phases.route.route import route_sections, _resolve_type


class TestResolveType:

    def test_scene_data(self):
        assert _resolve_type('scene_data') == 'SceneData'

    def test_bound_box(self):
        assert _resolve_type('bound_box') == 'BoundBox'

    def test_scene_camera(self):
        assert _resolve_type('scene_camera') == 'CameraSet'

    def test_joint(self):
        assert _resolve_type('nukenin_joint') == 'Joint'

    def test_matanim_joint(self):
        assert _resolve_type('nukenin_matanim_joint') == 'MaterialAnimationJoint'

    def test_shapeanim_joint(self):
        assert _resolve_type('some_shapeanim_joint') == 'ShapeAnimationJoint'

    def test_joint_priority_over_partial(self):
        """'_joint' should not match 'shapeanim_joint' (checked first)."""
        assert _resolve_type('foo_shapeanim_joint') == 'ShapeAnimationJoint'

    def test_unknown_section(self):
        assert _resolve_type('unknown_thing') == 'Dummy'

    def test_case_insensitive(self):
        assert _resolve_type('Scene_Data') == 'SceneData'  # exact match uses .lower()
        assert _resolve_type('FOO_JOINT') == 'Joint'       # contains match is case-insensitive


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
