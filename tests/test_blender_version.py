import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from shared.BlenderVersion import BlenderVersion


class TestBlenderVersion:
    def test_equal_tuple(self):
        assert BlenderVersion(4, 5, 0) == (4, 5, 0)

    def test_not_equal_tuple(self):
        assert not (BlenderVersion(4, 5, 0) == (4, 4, 0))

    def test_ge_tuple(self):
        assert (4, 5, 0) >= BlenderVersion(4, 5, 0)
        assert (4, 6, 0) >= BlenderVersion(4, 5, 0)
        assert not ((4, 4, 0) >= BlenderVersion(4, 5, 0))

    def test_lt_tuple(self):
        assert (4, 4, 0) < BlenderVersion(4, 5, 0)
        assert not ((4, 5, 0) < BlenderVersion(4, 5, 0))

    def test_gt_tuple(self):
        assert (4, 6, 0) > BlenderVersion(4, 5, 0)
        assert not ((4, 5, 0) > BlenderVersion(4, 5, 0))

    def test_le_tuple(self):
        assert (4, 5, 0) <= BlenderVersion(4, 5, 0)
        assert (4, 4, 0) <= BlenderVersion(4, 5, 0)

    def test_blenderversion_vs_blenderversion(self):
        assert BlenderVersion(4, 5, 0) >= BlenderVersion(4, 4, 0)
        assert BlenderVersion(4, 4, 0) < BlenderVersion(4, 5, 0)

    def test_repr(self):
        assert repr(BlenderVersion(4, 5, 0)) == "BlenderVersion(4, 5, 0)"

    def test_patch_comparison(self):
        assert (4, 5, 1) > BlenderVersion(4, 5, 0)
        assert (4, 5, 0) < BlenderVersion(4, 5, 1)
