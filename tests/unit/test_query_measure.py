"""Unit tests for MeasureMixin: element strings, COM call shapes, and the maths."""

import math
from unittest.mock import MagicMock

import pytest

from solidedge_mcp.backends.constants import MeasureDistanceTypeConstants
from solidedge_mcp.backends.query import QueryManager
from solidedge_mcp.backends.query._measure import ElementSpecError, parse_element


def _plane_face(outward):
    face = MagicMock()
    face.Geometry.GetPlaneData.return_value = ((0.0, 0.0, 0.03), (0.0, 0.0, 1.0))
    face.GetParamRange.return_value = ((0.0, 0.0), (0.1, 0.06))
    face.GetNormal.return_value = ((0.05, 0.03), tuple(outward))
    return face


def _line_edge(start, end):
    edge = MagicMock()
    edge.Geometry.GetLineData.return_value = (tuple(start), (0.0, 0.0, 1.0))
    edge.GetEndPoints.return_value = (tuple(start), tuple(end))
    return edge


def _curved_edge():
    edge = MagicMock()
    edge.Geometry.GetLineData.side_effect = Exception("not a line")
    return edge


def _ref_plane(root, normal):
    plane = MagicMock()
    plane.GetRootPoint.return_value = tuple(root)
    plane.GetNormal.return_value = tuple(normal)
    return plane


def _collection(items):
    coll = MagicMock()
    coll.Count = len(items)
    coll.Item.side_effect = lambda i: items[i - 1]
    return coll


@pytest.fixture
def setup():
    """A part with faces [top(+z), side(+x)], two vertices, and three ref planes."""
    top = _plane_face((0.0, 0.0, 1.0))
    side = _plane_face((1.0, 0.0, 0.0))
    side.Geometry.GetPlaneData.return_value = ((0.1, 0.0, 0.0), (1.0, 0.0, 0.0))
    top.Edges = _collection([_line_edge((0, 0, 0.03), (0.1, 0, 0.03)), _curved_edge()])
    vertex = MagicMock()
    vertex.GetPointData.return_value = (0.1, 0.06, 0.03)

    body = MagicMock()
    body.Faces.return_value = _collection([top, side])
    body.Vertices = _collection([vertex])
    model = MagicMock()
    model.Body = body
    doc = MagicMock()
    doc.Models = _collection([model])
    doc.RefPlanes = _collection(
        [
            _ref_plane((0, 0, 0), (0, 0, 1)),
            _ref_plane((0, 0, 0), (1, 0, 0)),
            _ref_plane((0, 0, 0), (0, -1, 0)),
        ]
    )
    dm = MagicMock()
    dm.get_active_document.return_value = doc
    return QueryManager(dm), doc, top, side


class TestParseElement:
    @pytest.mark.parametrize(
        ("spec", "parsed"),
        [
            ("face:3", ("face", 3, None)),
            (" Face:3 / Edge:1 ", ("edge", 3, 1)),
            ("vertex:0", ("vertex", 0, None)),
            ("plane:2", ("plane", 2, None)),
        ],
    )
    def test_good(self, spec, parsed):
        assert parse_element(spec) == parsed

    @pytest.mark.parametrize("spec", ["", "face", "face:x", "edge:1", "vertex:1/edge:2", "body:0"])
    def test_bad(self, spec):
        with pytest.raises(ElementSpecError):
            parse_element(spec)


class TestElementDistance:
    def test_calls_measure_distance_by_keyword(self, setup):
        qm, doc, top, side = setup
        doc.MeasureDistance.return_value = (0.1, 0.1, 0.0, 0.0, (0, 0, 0), (0.1, 0, 0))
        r = qm.measure_element_distance("face:0", "face:1", "maximum")
        doc.MeasureDistance.assert_called_once_with(
            Element1=top,
            Element2=side,
            DistanceType=MeasureDistanceTypeConstants.MeasureDistanceTypeConstants_MaximumDistance,
            Point1=[0.0, 0.0, 0.0],
            Point2=[0.0, 0.0, 0.0],
        )
        assert r["distance"] == 0.1
        assert r["delta"] == {"x": 0.1, "y": 0.0, "z": 0.0}
        assert r["point2"] == [0.1, 0, 0]

    def test_edge_is_taken_from_its_face(self, setup):
        qm, doc, top, side = setup
        doc.MeasureDistance.return_value = (0.0, 0, 0, 0, (0, 0, 0), (0, 0, 0))
        qm.measure_element_distance("face:0/edge:0", "face:1")
        assert doc.MeasureDistance.call_args.kwargs["Element1"] is top.Edges.Item(1)

    def test_plane_to_parallel_face(self, setup):
        qm, doc, top, side = setup
        r = qm.measure_element_distance("plane:1", "face:0")
        doc.MeasureDistance.assert_not_called()
        assert r["distance"] == pytest.approx(0.03)
        assert r["signed_distance"] == pytest.approx(0.03)
        assert r["point1"] == pytest.approx([0.0, 0.0, 0.0])

    def test_face_then_plane_reports_plane_first(self, setup):
        qm, doc, top, side = setup
        r = qm.measure_element_distance("face:0", "plane:1")
        assert (r["first"], r["second"]) == ("plane:1", "face:0")

    def test_plane_to_vertex(self, setup):
        qm, doc, top, side = setup
        r = qm.measure_element_distance("plane:3", "vertex:0")
        # Front's normal is -Y, so a vertex at y=0.06 is on its negative side.
        assert r["distance"] == pytest.approx(0.06)
        assert r["signed_distance"] == pytest.approx(-0.06)

    def test_plane_to_plane(self, setup):
        qm, doc, top, side = setup
        assert qm.measure_element_distance("plane:1", "plane:2")["unsupported"] is True

    def test_plane_to_perpendicular_face_refused(self, setup):
        qm, doc, top, side = setup
        assert qm.measure_element_distance("plane:1", "face:1")["unsupported"] is True

    def test_plane_to_edge_refused(self, setup):
        qm, doc, top, side = setup
        assert qm.measure_element_distance("plane:1", "face:0/edge:0")["unsupported"] is True

    def test_plane_maximum_refused(self, setup):
        qm, doc, top, side = setup
        r = qm.measure_element_distance("plane:1", "face:0", "maximum")
        assert r["unsupported"] is True

    def test_bad_extent(self, setup):
        qm, *_ = setup
        assert "Unknown extent" in qm.measure_element_distance("face:0", "face:1", "smart")["error"]

    @pytest.mark.parametrize(
        "spec", ["face:2", "face:0/edge:5", "vertex:1", "plane:0", "plane:4", "face:-1"]
    )
    def test_out_of_range(self, setup, spec):
        qm, doc, *_ = setup
        assert "out of range" in qm.measure_element_distance(spec, "face:0")["error"]
        doc.MeasureDistance.assert_not_called()


class TestElementAngle:
    def test_perpendicular_faces(self, setup):
        qm, *_ = setup
        r = qm.measure_element_angle("face:0", "face:1")
        assert r["angle"] == pytest.approx(90.0)
        assert r["acute_angle"] == pytest.approx(90.0)
        assert r["first_normal"] == [0.0, 0.0, 1.0]

    def test_outward_normal_read_at_param_middle(self, setup):
        qm, doc, top, side = setup
        qm.measure_element_angle("face:0", "face:1")
        assert top.GetNormal.call_args.args[:2] == (1, [0.05, 0.03])

    def test_face_against_opposite_plane(self, setup):
        qm, doc, top, side = setup
        top.GetNormal.return_value = ((0, 0), (0.0, 0.0, -1.0))
        r = qm.measure_element_angle("face:0", "plane:1")
        assert r["angle"] == pytest.approx(180.0)
        assert r["acute_angle"] == pytest.approx(0.0)

    def test_edge_and_face(self, setup):
        qm, *_ = setup
        r = qm.measure_element_angle("face:0/edge:0", "face:1")
        # The edge runs along +x and side's normal is +x: perpendicular to that plane.
        assert r["angle"] == pytest.approx(90.0)
        assert "acute_angle" not in r

    def test_edge_and_edge(self, setup):
        qm, doc, top, side = setup
        top.Edges = _collection(
            [_line_edge((0, 0, 0), (1, 0, 0)), _line_edge((0, 0, 0), (1, 1, 0))]
        )
        r = qm.measure_element_angle("face:0/edge:0", "face:0/edge:1")
        assert r["angle"] == pytest.approx(45.0)
        assert r["first_direction"] == [1.0, 0.0, 0.0]

    def test_curved_edge_refused(self, setup):
        qm, *_ = setup
        assert "curved" in qm.measure_element_angle("face:0/edge:1", "face:1")["error"]

    def test_vertex_refused(self, setup):
        qm, *_ = setup
        assert "vertex" in qm.measure_element_angle("vertex:0", "face:1")["error"]

    def test_non_planar_face_refused(self, setup):
        qm, doc, top, side = setup
        side.Geometry.GetPlaneData.side_effect = Exception("cylinder")
        assert "not planar" in qm.measure_element_angle("face:0", "face:1")["error"]

    def test_unnormalised_vectors(self, setup):
        qm, doc, top, side = setup
        side.GetNormal.return_value = ((0, 0), (0.0, 3.0, 3.0))
        r = qm.measure_element_angle("face:0", "face:1")
        assert r["angle"] == pytest.approx(45.0)
        assert math.isclose(sum(x * x for x in r["second_normal"]), 1.0)
