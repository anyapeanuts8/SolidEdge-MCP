"""Distance and angle between model elements: faces, edges, vertices, ref planes.

Verified on Solid Edge 2026 against a 100 x 60 x 30 mm box:

* ``PartDocument.MeasureDistance`` measures face, edge and vertex pairs. Its
  ``Distance``/``DX``/``DY``/``DZ`` out-parameters sit between the inputs and
  the point buffers, so ``DistanceType`` and the buffers go **by keyword**;
  positional lists land in the ``Distance`` slot and raise.
* A ``RefPlane`` handed to it raises E_FAIL, so a reference plane is measured
  here from ``RefPlane.GetRootPoint``/``GetNormal`` instead, which is exact for
  a vertex or a parallel planar face and refused otherwise.
* ``Plane.GetPlaneData`` gives the surface normal, which is not the face's
  outward side (a box's bottom face reads +Z). ``Face.GetNormal`` at the
  middle of ``GetParamRange`` is outward, so angles use that.
"""

from __future__ import annotations

import math
from typing import Any

from solidedge_mcp.backends.errors import error_result

from ..constants import MeasureDistanceTypeConstants
from ._base import QueryManagerBase, all_faces, body_of, r8_array

_DISTANCE_TYPES = {
    "minimum": MeasureDistanceTypeConstants.MeasureDistanceTypeConstants_MinimumDistance,
    "maximum": MeasureDistanceTypeConstants.MeasureDistanceTypeConstants_MaximumDistance,
}

ELEMENT_FORMS = "'face:N', 'face:N/edge:M', 'vertex:N' (0-based) or 'plane:N' (1-based)"

# |cross product| below this and two unit vectors count as parallel.
PARALLEL_TOLERANCE = 1e-6


class ElementSpecError(ValueError):
    """An element that cannot be measured the way it was asked for."""


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(_dot(v, v))
    if n == 0:
        raise ElementSpecError("zero-length direction")
    return [x / n for x in v]


def _parallel(a: list[float], b: list[float]) -> bool:
    cross = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    return math.sqrt(_dot(cross, cross)) < PARALLEL_TOLERANCE


def parse_element(spec: str) -> tuple[str, int, int | None]:
    """'face:3' -> ('face', 3, None); 'face:3/edge:1' -> ('edge', 3, 1)."""
    parts = [p.strip() for p in spec.strip().lower().split("/")]
    try:
        kind, _, num = parts[0].partition(":")
        index = int(num)
        if len(parts) == 1 and kind in ("face", "vertex", "plane"):
            return kind, index, None
        if len(parts) == 2 and kind == "face":
            sub, _, sub_num = parts[1].partition(":")
            if sub == "edge":
                return "edge", index, int(sub_num)
    except ValueError:
        pass
    raise ElementSpecError(f"Cannot read element {spec!r}. Use {ELEMENT_FORMS}.")


class MeasureMixin(QueryManagerBase):
    """measure(type='element_distance' | 'element_angle')."""

    def _resolve_element(self, spec: str) -> tuple[str, Any, Any]:
        """Return (kind, com_object, document) for an element string."""
        kind, index, sub = parse_element(spec)
        doc, model = self._get_first_model()
        if kind == "plane":
            planes = doc.RefPlanes
            if not 1 <= index <= planes.Count:
                raise ElementSpecError(
                    f"plane:{index} is out of range; the part has {planes.Count} reference "
                    "planes (1=Top/XY, 2=Right/YZ, 3=Front/XZ)."
                )
            return kind, planes.Item(index), doc
        body = body_of(model)
        if kind == "vertex":
            vertices = body.Vertices
            if not 0 <= index < vertices.Count:
                raise ElementSpecError(
                    f"vertex:{index} is out of range; the body has {vertices.Count} vertices."
                )
            return kind, vertices.Item(index + 1), doc
        faces = all_faces(body, model)
        if not 0 <= index < faces.Count:
            raise ElementSpecError(
                f"face:{index} is out of range; the body has {faces.Count} faces."
            )
        face = faces.Item(index + 1)
        if kind == "face":
            return kind, face, doc
        edges = face.Edges
        if sub is None or not 0 <= sub < edges.Count:
            raise ElementSpecError(
                f"face:{index}/edge:{sub} is out of range; that face has {edges.Count} edges."
            )
        return kind, edges.Item(sub + 1), doc

    # -- geometry helpers ------------------------------------------------------

    @staticmethod
    def _outward_normal(face: Any) -> list[float] | None:
        """Outward unit normal of a planar face, None when the face is not planar."""
        try:
            face.Geometry.GetPlaneData(r8_array(3), r8_array(3))
        except Exception:
            return None
        lo, hi = face.GetParamRange(r8_array(2), r8_array(2))
        mid = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2]
        result = face.GetNormal(1, mid, r8_array(3))
        return _unit(list(result[-1])[:3])

    @staticmethod
    def _line_direction(edge: Any) -> list[float] | None:
        """Unit start-to-end direction of a straight edge, None when it is curved."""
        try:
            edge.Geometry.GetLineData(r8_array(3), r8_array(3))
        except Exception:
            return None
        start, end = edge.GetEndPoints(r8_array(3), r8_array(3))
        return _unit([e - s for s, e in zip(start, end, strict=True)])

    @staticmethod
    def _plane_frame(plane: Any) -> tuple[list[float], list[float]]:
        """(root point, unit normal) of a RefPlane."""
        root = list(plane.GetRootPoint(r8_array(3)))[:3]
        normal = _unit(list(plane.GetNormal(r8_array(3)))[:3])
        return root, normal

    # -- distance --------------------------------------------------------------

    def measure_element_distance(
        self, first: str, second: str, extent: str = "minimum"
    ) -> dict[str, Any]:
        """Minimum or maximum distance between two elements, with its end points."""
        try:
            distance_type = _DISTANCE_TYPES.get(extent)
            if distance_type is None:
                return {"error": f"Unknown extent: {extent}. Use minimum or maximum."}
            kind1, obj1, doc = self._resolve_element(first)
            kind2, obj2, _ = self._resolve_element(second)

            if "plane" in (kind1, kind2):
                if extent != "minimum":
                    return {
                        "error": "A reference plane is unbounded; only extent='minimum' applies.",
                        "unsupported": True,
                    }
                if kind1 == "plane":
                    return self._plane_distance(first, obj1, second, kind2, obj2)
                return self._plane_distance(second, obj2, first, kind1, obj1)

            out = doc.MeasureDistance(
                Element1=obj1,
                Element2=obj2,
                DistanceType=distance_type,
                Point1=r8_array(3),
                Point2=r8_array(3),
            )
            distance, dx, dy, dz, point1, point2 = out[:6]
            return {
                "status": "measured",
                "first": first,
                "second": second,
                "extent": extent,
                "distance": distance,
                "delta": {"x": dx, "y": dy, "z": dz},
                "point1": list(point1)[:3],
                "point2": list(point2)[:3],
                "units": "meters",
            }
        except ElementSpecError as e:
            return {"error": str(e)}
        except Exception as e:
            return error_result(e)

    def _plane_distance(
        self, plane_spec: str, plane: Any, other_spec: str, kind: str, other: Any
    ) -> dict[str, Any]:
        """Distance from a reference plane, computed from its root point and normal."""
        root, normal = self._plane_frame(plane)

        if kind == "vertex":
            point = list(other.GetPointData(r8_array(3)))[:3]
        elif kind == "plane":
            root2, normal2 = self._plane_frame(other)
            if not _parallel(normal, normal2):
                return self._not_parallel(plane_spec, other_spec)
            point = root2
        elif kind == "face":
            face_normal = self._outward_normal(other)
            if face_normal is None or not _parallel(normal, face_normal):
                return self._not_parallel(plane_spec, other_spec)
            data = other.Geometry.GetPlaneData(r8_array(3), r8_array(3))
            point = list(data[0])[:3]
        else:
            return {
                "error": (
                    "Distance from a reference plane works for a vertex, a parallel planar "
                    "face or a parallel plane. For an edge, measure to one of its vertices."
                ),
                "unsupported": True,
            }

        signed = _dot([p - r for p, r in zip(point, root, strict=True)], normal)
        foot = [p - signed * n for p, n in zip(point, normal, strict=True)]
        return {
            "status": "measured",
            "first": plane_spec,
            "second": other_spec,
            "extent": "minimum",
            "distance": abs(signed),
            "signed_distance": signed,
            "plane_normal": normal,
            "delta": {"x": point[0] - foot[0], "y": point[1] - foot[1], "z": point[2] - foot[2]},
            "point1": foot,
            "point2": point,
            "units": "meters",
        }

    @staticmethod
    def _not_parallel(plane_spec: str, other_spec: str) -> dict[str, Any]:
        return {
            "error": (
                f"{other_spec} is not a planar face or plane parallel to {plane_spec}; the "
                "distance from an unbounded plane is only defined for parallel planes or a "
                "vertex."
            ),
            "unsupported": True,
        }

    # -- angle -----------------------------------------------------------------

    def _direction_of(self, spec: str, kind: str, obj: Any) -> tuple[str, list[float]]:
        """('normal' | 'direction', unit vector) for a planar face, plane or straight edge."""
        if kind == "plane":
            return "normal", self._plane_frame(obj)[1]
        if kind == "face":
            normal = self._outward_normal(obj)
            if normal is None:
                raise ElementSpecError(f"{spec} is not planar; an angle needs a planar face.")
            return "normal", normal
        if kind == "edge":
            direction = self._line_direction(obj)
            if direction is None:
                raise ElementSpecError(f"{spec} is curved; an angle needs a straight edge.")
            return "direction", direction
        raise ElementSpecError(f"{spec} is a vertex; an angle needs a face, edge or plane.")

    def measure_element_angle(self, first: str, second: str) -> dict[str, Any]:
        """Angle between two planar faces / planes / straight edges, in degrees."""
        try:
            kind1, obj1, _ = self._resolve_element(first)
            kind2, obj2, _ = self._resolve_element(second)
            role1, v1 = self._direction_of(first, kind1, obj1)
            role2, v2 = self._direction_of(second, kind2, obj2)
            cos = max(-1.0, min(1.0, _dot(v1, v2)))
            result: dict[str, Any] = {
                "status": "measured",
                "first": first,
                "second": second,
                f"first_{role1}": v1,
                f"second_{role2}": v2,
                "units": "degrees",
            }
            if role1 == role2:
                angle = math.degrees(math.acos(cos))
                result["angle"] = angle
                result["acute_angle"] = min(angle, 180.0 - angle)
                if role1 == "normal":
                    result["note"] = (
                        "angle is between the outward normals (0-180; 0 = facing the same "
                        "way, 180 = opposite); acute_angle is between the planes (0-90)."
                    )
                else:
                    result["note"] = (
                        "angle is between the start-to-end directions (0-180); acute_angle "
                        "is between the lines (0-90)."
                    )
            else:
                result["angle"] = math.degrees(math.asin(abs(cos)))
                result["note"] = "angle between the edge and the plane (0-90; 0 = parallel)."
            return result
        except ElementSpecError as e:
            return {"error": str(e)}
        except Exception as e:
            return error_result(e)
