"""query_face / query_edge evaluate at normalised 0-1 parameters, on a cylinder.

A cylinder's side runs 0-2*pi in u and its circular edges 0-2*pi, so a raw
0.5 lands 0.5 rad round instead of halfway. Radius 20 mm gives curvature 50.
"""

from __future__ import annotations

import math

import pytest

pytestmark = pytest.mark.integration

R, H = 0.02, 0.03


@pytest.fixture
def query(stack):
    return stack.query


@pytest.fixture
def cylinder(managers, new_part, query):
    _, sketch_mgr, feature_mgr = managers
    sketch_mgr.create_sketch("Top")
    sketch_mgr.draw_circle(0, 0, R)
    sketch_mgr.close_sketch()
    result = feature_mgr.create_extrude(H)
    assert result["status"] == "created", f"Extrude failed: {result}"
    faces = query._get_first_model()[1].Body.Faces(1)
    side = next(i for i in range(faces.Count) if "Cylinder" in str(query.get_face_geometry(i)))
    return side


def test_side_normal_is_radial_and_horizontal(query, cylinder):
    for u in (0.0, 0.25, 0.5, 0.75):
        r = query.get_face_normal(cylinder, u, 0.5)
        n = r["normal"]
        assert n[2] == pytest.approx(0.0, abs=1e-9)
        assert math.hypot(n[0], n[1]) == pytest.approx(1.0)
        assert r["native_params"][0] == pytest.approx(u * 2 * math.pi)
        assert r["native_params"][1] == pytest.approx(H / 2)


def test_quarter_turn_apart(query, cylinder):
    a = query.get_face_normal(cylinder, 0.0, 0.5)["normal"]
    b = query.get_face_normal(cylinder, 0.25, 0.5)["normal"]
    assert sum(x * y for x, y in zip(a, b, strict=True)) == pytest.approx(0.0, abs=1e-9)


def test_side_curvature(query, cylinder):
    r = query.get_face_curvature(cylinder, 0.5, 0.5)
    assert r["max_curvature"] == pytest.approx(1 / R)
    assert r["min_curvature"] == pytest.approx(0.0, abs=1e-9)
    assert len(r["max_tangent"]) == 3


def test_circular_edge_curvature_and_tangent(query, cylinder):
    r = query.get_edge_curvature(cylinder, 0, 0.5)
    assert r["curvature"] == pytest.approx(1 / R)
    assert r["native_param"] == pytest.approx(math.pi)
    t = query.get_edge_tangent(cylinder, 0, 0.5)
    assert t["tangent"][2] == pytest.approx(0.0, abs=1e-9)
    assert math.hypot(*t["tangent"]) == pytest.approx(1.0)


def test_out_of_range_is_refused(query, cylinder):
    assert "0.0-1.0" in query.get_face_normal(cylinder, 3.14, 0.5)["error"]
    assert "0.0-1.0" in query.get_edge_tangent(cylinder, 0, 2.0)["error"]
