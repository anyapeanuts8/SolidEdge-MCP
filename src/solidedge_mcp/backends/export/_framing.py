"""Frame the model in a captured image: centre it and zoom it to fill the frame.

``View.Fit`` alone leaves the model small and off-centre in what
``SaveAsImage`` writes. Verified on Solid Edge 2026 with a 42 x 41 x 28 mm
part: after Fit the camera target sat at the model's base (z = 0, not its
middle) and the part filled about a sixth of the image, whether the image was
the window's size or not, and whether the view came from ApplyNamedView or
the UI's own Iso and Fit commands (same eye, target and scale).

So the capture frames the shot itself:

1. move the camera target to the centre of the bodies' range, keeping the
   view direction (the model is then centred on screen);
2. render a BMP and find the pixels that are not background;
3. scale the orthographic camera so that region fills ``FILL`` of the frame,
   zooming about the image centre so nothing is pushed out of it.

Step 2 needs no knowledge of how Solid Edge's view scale maps to pixels, so
it also works where step 1 cannot (no body range, e.g. an assembly).
"""

from __future__ import annotations

import struct
from typing import Any

from ..comutil import com_get

#: Share of the frame the model should fill after framing.
FILL = 0.85
#: A pixel whose channels differ from the background by more than this is content.
CONTENT_THRESHOLD = 24
#: Sample every Nth pixel when looking for content; plenty for a bounding box.
SAMPLE_STEP = 2


def bmp_content_box(data: bytes) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) of non-background pixels in a 24/32-bit BMP.

    The background is the colour of the top-left pixel. Coordinates are in
    image pixels with the origin at the top left. None when the image holds
    nothing but background, or is not a BMP this can read.
    """
    if len(data) < 54 or data[:2] != b"BM":
        return None
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bpp = struct.unpack_from("<H", data, 28)[0]
    if bpp not in (24, 32) or width <= 0 or height == 0:
        return None
    bottom_up = height > 0
    height = abs(height)
    step = bpp // 8
    stride = (width * step + 3) & ~3

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        row = (height - 1 - y) if bottom_up else y
        i = offset + row * stride + x * step
        return data[i + 2], data[i + 1], data[i]

    bg = pixel(0, 0)
    left, top, right, bottom = width, height, -1, -1
    for y in range(0, height, SAMPLE_STEP):
        for x in range(0, width, SAMPLE_STEP):
            r, g, b = pixel(x, y)
            if (
                abs(r - bg[0]) > CONTENT_THRESHOLD
                or abs(g - bg[1]) > CONTENT_THRESHOLD
                or abs(b - bg[2]) > CONTENT_THRESHOLD
            ):
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
    if right < 0:
        return None
    return left, top, right, bottom


def zoom_factor(
    box: tuple[int, int, int, int], width: int, height: int, fill: float = FILL
) -> float:
    """How much to scale so ``box`` fills ``fill`` of the frame, zooming about its centre.

    Measured from the image centre, so a box that is off-centre is scaled only
    as far as its farthest edge allows and never leaves the frame.
    """
    left, top, right, bottom = box
    cx, cy = width / 2, height / 2
    half_w = max(cx - left, right - cx, 1)
    half_h = max(cy - top, bottom - cy, 1)
    return min(fill * cx / half_w, fill * cy / half_h)


def model_center(doc: Any) -> list[float] | None:
    """Centre of the range of every body in ``doc.Models``; None when there is none.

    ``Body.GetRange`` fills two [in,out] SAFEARRAY buffers and hands them back
    in the result tuple (plain lists in, values out; see query/_base.py).
    """
    models = com_get(doc, "Models")
    count = com_get(models, "Count", 0)
    if not isinstance(count, int) or count <= 0:
        return None
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for m in range(1, count + 1):
        body = com_get(models.Item(m), "Body")
        if body is None:
            continue
        try:
            mn, mx = body.GetRange([0.0] * 3, [0.0] * 3)[:2]
        except Exception:
            continue
        for k in range(3):
            lo[k] = min(lo[k], float(mn[k]))
            hi[k] = max(hi[k], float(mx[k]))
    if lo[0] == float("inf"):
        return None
    return [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
