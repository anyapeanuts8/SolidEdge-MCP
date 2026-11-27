"""Unit tests for capture framing: BMP content box, zoom factor, model centre."""

import struct
from unittest.mock import MagicMock

import pytest

from solidedge_mcp.backends.export._framing import bmp_content_box, model_center, zoom_factor

BG = (248, 250, 250)


def _bmp(width, height, boxes=(), bpp=24, top_down=False):
    """A BMP of background with each (l, t, r, b, colour) box filled (top-left origin)."""
    step = bpp // 8
    stride = (width * step + 3) & ~3
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            colour = BG
            for left, t, r, b, c in boxes:
                if left <= x <= r and t <= y <= b:
                    colour = c
            row += bytes((colour[2], colour[1], colour[0])) + (b"\0" if step == 4 else b"")
        row += b"\0" * (stride - len(row))
        rows.append(bytes(row))
    pixels = b"".join(rows if top_down else reversed(rows))
    header = b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54)
    info = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        -height if top_down else height,
        1,
        bpp,
        0,
        len(pixels),
        2835,
        2835,
        0,
        0,
    )
    return header + info + pixels


class TestBmpContentBox:
    @pytest.mark.parametrize("bpp", [24, 32])
    @pytest.mark.parametrize("top_down", [False, True])
    def test_finds_the_box(self, bpp, top_down):
        data = _bmp(40, 30, [(10, 6, 20, 14, (90, 90, 90))], bpp=bpp, top_down=top_down)
        left, t, r, b = bmp_content_box(data)
        # Sampled every 2nd pixel, so edges land within one pixel.
        assert 10 <= left <= 11 and 20 >= r >= 19
        assert 6 <= t <= 7 and 14 >= b >= 13

    def test_empty_image(self):
        assert bmp_content_box(_bmp(20, 10)) is None

    def test_faint_noise_is_background(self):
        data = _bmp(20, 10, [(4, 4, 8, 8, (240, 244, 246))])
        assert bmp_content_box(data) is None

    def test_not_a_bmp(self):
        assert bmp_content_box(b"\x89PNG\r\n\x1a\n" + b"\0" * 60) is None


class TestZoomFactor:
    def test_centred_box_fills(self):
        # A 100 x 50 box centred in 400 x 200: width-limited -> 0.85 * 400 / 100.
        assert zoom_factor((150, 75, 250, 125), 400, 200) == pytest.approx(3.4)

    def test_off_centre_box_limited_by_far_edge(self):
        # Box spans x 200-300 in a 400-wide frame: far edge 100 px from centre.
        assert zoom_factor((200, 90, 300, 110), 400, 200) == pytest.approx(1.7)

    def test_box_larger_than_frame_shrinks(self):
        assert zoom_factor((0, 0, 399, 199), 400, 200) < 1.0


class TestModelCenter:
    def _doc(self, *ranges):
        doc = MagicMock()
        models = []
        for mn, mx in ranges:
            model = MagicMock()
            model.Body.GetRange.return_value = (mn, mx)
            models.append(model)
        doc.Models.Count = len(models)
        doc.Models.Item.side_effect = lambda i: models[i - 1]
        return doc

    def test_one_body(self):
        doc = self._doc(((0, 0, 0), (0.1, 0.06, 0.03)))
        assert model_center(doc) == pytest.approx([0.05, 0.03, 0.015])
        doc.Models.Item(1).Body.GetRange.assert_called_once_with([0.0] * 3, [0.0] * 3)

    def test_union_of_bodies(self):
        doc = self._doc(((0, 0, 0), (1, 1, 1)), ((2, -1, 0), (3, 0, 2)))
        assert model_center(doc) == pytest.approx([1.5, 0.0, 1.0])

    def test_no_models(self):
        doc = MagicMock()
        doc.Models.Count = 0
        assert model_center(doc) is None

    def test_unreadable_count(self):
        assert model_center(MagicMock()) is None
