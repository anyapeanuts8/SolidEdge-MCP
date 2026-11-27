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


def test_fit_frames_the_model(stack, view_mgr, box):
    """Fit alone left the part small and off-centre; framing centres and zooms it."""
    from solidedge_mcp.backends.export._framing import bmp_content_box

    result = view_mgr.capture_view_images(["Iso"], 640, 480)
    img = result["images"][0]
    assert img["centered"] is True
    assert img["zoom"] >= 1.0

    # Render the framed view once more as a BMP and check how much it fills.
    import os
    import tempfile

    doc = stack.doc.get_active_document()
    view = doc.Windows.Item(1).View
    saved = tuple(view.GetCamera())
    try:
        view.ApplyNamedView("Iso")
        view.Fit()
        with tempfile.TemporaryDirectory() as tmp:
            view_mgr._frame(view, doc, os.path.join(tmp, "probe.bmp"), 640, 480)
            path = os.path.join(tmp, "framed.bmp")
            view.SaveAsImage(path, 640, 480)
            with open(path, "rb") as f:
                left, top, right, bottom = bmp_content_box(f.read())
    finally:
        view.SetCamera(*saved[:11])
    fill = max((right - left) / 640, (bottom - top) / 480)
    assert 0.7 <= fill <= 0.95, (left, top, right, bottom)
    centre_x, centre_y = (left + right) / 2, (top + bottom) / 2
    assert abs(centre_x - 320) < 64 and abs(centre_y - 240) < 48
