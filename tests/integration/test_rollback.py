"""A failed creator leaves no feature behind; a successful one is kept.

Solid Edge records an extruded cutout that misses the body as
ExtrudedCutout_1 and builds nothing. verifies_geometry reports that as an
error, and the rollback deletes the node so the tree is as it was.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _tree(doc):
    eb = doc.DesignEdgebarFeatures
    return [eb.Item(i).Name for i in range(1, eb.Count + 1)]


@pytest.fixture
def box(managers, new_part):
    doc_mgr, sketch_mgr, feature_mgr = managers
    sketch_mgr.create_sketch("Top")
    sketch_mgr.draw_rectangle(0, 0, 0.1, 0.06)
    sketch_mgr.close_sketch()
    result = feature_mgr.create_extrude(0.03)
    assert result["status"] == "created", f"Extrude failed: {result}"
    return doc_mgr.get_active_document()


def _faces(doc):
    return doc.Models.Item(1).Body.Faces(1).Count


def test_cutout_that_misses_is_rolled_back(managers, box):
    _, sketch_mgr, feature_mgr = managers
    before = _tree(box)
    sketch_mgr.create_sketch("Top")
    sketch_mgr.draw_circle(0.5, 0.5, 0.01)
    sketch_mgr.close_sketch()
    result = feature_mgr.create_extruded_cutout(0.01, "Symmetric")
    assert "created no geometry" in result["error"]
    assert result["rolled_back"] == ["ExtrudedCutout_1"]
    assert "rollback_failed" not in result
    assert _tree(box) == before
    assert _faces(box) == 6


def test_cutout_that_cuts_is_kept(managers, box):
    _, sketch_mgr, feature_mgr = managers
    before = _tree(box)
    sketch_mgr.create_sketch("Top")
    sketch_mgr.draw_circle(0.05, 0.03, 0.01)
    sketch_mgr.close_sketch()
    result = feature_mgr.create_extruded_cutout(0.1, "Symmetric")
    assert result.get("status") == "created", result
    assert "rolled_back" not in result
    assert len(_tree(box)) == len(before) + 1
    assert _faces(box) == 7
