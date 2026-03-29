"""Tests for vertex color extraction in describe phase."""
from types import SimpleNamespace

from importer.phases.describe.helpers.meshes import _extract_color_layers
from shared.IR.geometry import IRColorLayer


def _make_color(r, g, b, a):
    return SimpleNamespace(red=r, green=g, blue=b, alpha=a)


class TestExtractColorLayers:

    def test_basic_color_extraction(self):
        """Colors are normalized from u8 [0-255] to float [0-1]."""
        source = [_make_color(255, 128, 0, 200)]
        face_list = [[0]]
        faces = [[0]]
        color_layer, alpha_layer = _extract_color_layers(source, face_list, faces, '0')
        assert isinstance(color_layer, IRColorLayer)
        assert color_layer.name == 'color_0'
        assert alpha_layer.name == 'alpha_0'
        assert abs(color_layer.colors[0][0] - 1.0) < 1e-5
        assert abs(color_layer.colors[0][1] - 128 / 255) < 1e-5
        assert abs(color_layer.colors[0][2] - 0.0) < 1e-5
        assert abs(color_layer.colors[0][3] - 200 / 255) < 1e-5

    def test_colors_are_not_linearized(self):
        """Vertex colors should be sRGB [0-1], NOT linearized.

        A mid-grey value of 128 should map to ~0.502, not to the linearized
        value ~0.216 that sRGB→linear would produce.
        """
        source = [_make_color(128, 128, 128, 255)]
        face_list = [[0]]
        faces = [[0]]
        color_layer, _ = _extract_color_layers(source, face_list, faces, '0')
        expected = 128 / 255  # ~0.502
        assert abs(color_layer.colors[0][0] - expected) < 1e-5
        # Should NOT be ~0.216 (which is srgb_to_linear(128/255))
        assert color_layer.colors[0][0] > 0.4

    def test_alpha_layer_splat(self):
        """Alpha layer should replicate alpha value across RGB channels."""
        source = [_make_color(100, 200, 50, 180)]
        face_list = [[0]]
        faces = [[0]]
        _, alpha_layer = _extract_color_layers(source, face_list, faces, '0')
        a = 180 / 255
        assert abs(alpha_layer.colors[0][0] - a) < 1e-5
        assert abs(alpha_layer.colors[0][1] - a) < 1e-5
        assert abs(alpha_layer.colors[0][2] - a) < 1e-5
        assert abs(alpha_layer.colors[0][3] - 1.0) < 1e-5

    def test_black(self):
        source = [_make_color(0, 0, 0, 0)]
        face_list = [[0]]
        faces = [[0]]
        color_layer, alpha_layer = _extract_color_layers(source, face_list, faces, '0')
        assert color_layer.colors[0] == (0.0, 0.0, 0.0, 0.0)
        assert alpha_layer.colors[0] == (0.0, 0.0, 0.0, 1.0)

    def test_white(self):
        source = [_make_color(255, 255, 255, 255)]
        face_list = [[0]]
        faces = [[0]]
        color_layer, _ = _extract_color_layers(source, face_list, faces, '0')
        assert color_layer.colors[0] == (1.0, 1.0, 1.0, 1.0)

    def test_color_1_naming(self):
        source = [_make_color(128, 128, 128, 255)]
        face_list = [[0]]
        faces = [[0]]
        color_layer, alpha_layer = _extract_color_layers(source, face_list, faces, '1')
        assert color_layer.name == 'color_1'
        assert alpha_layer.name == 'alpha_1'

    def test_multiple_faces(self):
        source = [
            _make_color(255, 0, 0, 255),
            _make_color(0, 255, 0, 255),
            _make_color(0, 0, 255, 255),
            _make_color(255, 255, 0, 255),
        ]
        face_list = [[0, 1, 2], [1, 3, 2]]
        faces = [[0, 1, 2], [1, 3, 2]]
        color_layer, _ = _extract_color_layers(source, face_list, faces, '0')
        assert len(color_layer.colors) == 6  # 2 faces * 3 verts

        # First face: red, green, blue
        assert abs(color_layer.colors[0][0] - 1.0) < 1e-5  # red
        assert abs(color_layer.colors[1][1] - 1.0) < 1e-5  # green
        assert abs(color_layer.colors[2][2] - 1.0) < 1e-5  # blue

    def test_indirect_face_list(self):
        """face_list indices may differ from face vertex indices."""
        source = [
            _make_color(100, 0, 0, 255),  # index 0
            _make_color(0, 100, 0, 255),  # index 1
        ]
        # face_list remaps: face vertex 0 → source 1, face vertex 1 → source 0
        face_list = [[1, 0]]
        faces = [[0, 1]]
        color_layer, _ = _extract_color_layers(source, face_list, faces, '0')
        # First loop should come from source[1] (green)
        assert abs(color_layer.colors[0][1] - 100 / 255) < 1e-5
        # Second loop should come from source[0] (red)
        assert abs(color_layer.colors[1][0] - 100 / 255) < 1e-5
