"""capture_view_images against a live Solid Edge: a box seen from four sides.

Set SOLIDEDGE_MCP_CAPTURE_DIR to keep the PNGs for a look by eye.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def view_mgr(stack):
    from solidedge_mcp.backends.export import ViewModel

    return ViewModel(stack.doc)


@pytest.fixture
def box(managers, new_part):
    _, sketch_mgr, feature_mgr = managers
    sketch_mgr.create_sketch("Top")
    sketch_mgr.draw_rectangle(0, 0, 0.1, 0.06)
    sketch_mgr.close_sketch()
    result = feature_mgr.create_extrude(0.03)
    assert result["status"] == "created", f"Extrude failed: {result}"
    return new_part


def _camera(stack):
    doc = stack.doc.get_active_document()
    return tuple(doc.Windows.Item(1).View.GetCamera())[:11]


def test_four_views_are_png_and_differ(stack, view_mgr, box):
    before = _camera(stack)
    result = view_mgr.capture_view_images(["Iso", "Top", "Front", "Right"], 640, 480)
    assert result["status"] == "captured", result
    images = result["images"]
    assert [img["view"] for img in images] == ["Iso", "Top", "Front", "Right"]
    for img in images:
        assert img["png"].startswith(PNG_MAGIC)
    assert len({img["png"] for img in images}) == 4, "two views rendered identically"

    assert result["view_restored"] is True
    after = _camera(stack)
    assert after == pytest.approx(before)

    out = os.environ.get("SOLIDEDGE_MCP_CAPTURE_DIR")
    if out:
        os.makedirs(out, exist_ok=True)
        for img in images:
            with open(os.path.join(out, f"box_{img['view']}.png"), "wb") as f:
                f.write(img["png"])


def test_current_without_fit_leaves_camera_alone(stack, view_mgr, box):
    before = _camera(stack)
    result = view_mgr.capture_view_images(["Current"], 320, 240, fit=False)
    assert result["status"] == "captured", result
    assert result["view_restored"] is False
    assert _camera(stack) == pytest.approx(before)
