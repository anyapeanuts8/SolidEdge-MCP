"""measure(element_distance / element_angle) on a 100 x 60 x 30 mm box.

Every expected value follows from the box's dimensions, so a wrong answer
from Solid Edge or a wrong reading of its out-parameters shows up as a number.
Faces are located by their outward normal, not by index, so the test does not
depend on the order Solid Edge enumerates them in.
"""

from __future__ import annotations

import math

import pytest

pytestmark = pytest.mark.integration

X, Y, Z = 0.1, 0.06, 0.03


@pytest.fixture
def query(stack):
    return stack.query


@pytest.fixture
def box(managers, new_part):
    _, sketch_mgr, feature_mgr = managers
    sketch_mgr.create_sketch("Top")
    sketch_mgr.draw_rectangle(0, 0, X, Y)
    sketch_mgr.close_sketch()
    result = feature_mgr.create_extrude(Z)
    assert result["status"] == "created", f"Extrude failed: {result}"
    return new_part


@pytest.fixture
def faces(query, box):
    """Map an outward normal like '+x' to 'face:N'."""
    doc, model = query._get_first_model()
    all_ = model.Body.Faces(1)
    found = {}
    for i in range(all_.Count):
        n = query._outward_normal(all_.Item(i + 1))
        axis = max(range(3), key=lambda k: abs(n[k]))
        found[("+" if n[axis] > 0 else "-") + "xyz"[axis]] = f"face:{i}"
    assert len(found) == 6, found
    return found


@pytest.mark.parametrize(
    ("a", "b", "expected"), [("-x", "+x", X), ("-y", "+y", Y), ("-z", "+z", Z)]
)
def test_opposite_faces_minimum(query, faces, a, b, expected):
    r = query.measure_element_distance(faces[a], faces[b])
    assert r["status"] == "measured", r
    assert r["distance"] == pytest.approx(expected, abs=1e-9)


def test_adjacent_faces_touch(query, faces):
    r = query.measure_element_distance(faces["+x"], faces["+z"])
    assert r["distance"] == pytest.approx(0.0, abs=1e-9)


def test_maximum_is_the_diagonal(query, faces):
    r = query.measure_element_distance(faces["-x"], faces["+x"], extent="maximum")
    assert r["distance"] == pytest.approx(math.sqrt(X * X + Y * Y + Z * Z), abs=1e-9)


def test_top_face_from_top_plane(query, faces):
    r = query.measure_element_distance("plane:1", faces["+z"])
    assert r["status"] == "measured", r
    assert r["distance"] == pytest.approx(Z, abs=1e-9)


def test_vertex_from_right_plane(query, faces):
    # Every vertex sits at x=0 or x=X, so its distance from YZ is one of those.
    r = query.measure_element_distance("plane:2", "vertex:0")
    assert r["status"] == "measured", r
    assert min(abs(r["distance"]), abs(r["distance"] - X)) < 1e-9


def test_plane_to_perpendicular_face_is_refused(query, faces):
    r = query.measure_element_distance("plane:1", faces["+x"])
    assert r.get("unsupported") is True


def test_edge_to_opposite_face(query, faces):
    r = query.measure_element_distance(f"{faces['-x']}/edge:0", faces["+x"])
    assert r["distance"] == pytest.approx(X, abs=1e-9)


@pytest.mark.parametrize(
    ("a", "b", "angle", "acute"),
    [("+x", "+z", 90.0, 90.0), ("-x", "+x", 180.0, 0.0), ("+z", "+z", 0.0, 0.0)],
)
def test_face_angles(query, faces, a, b, angle, acute):
    r = query.measure_element_angle(faces[a], faces[b])
    assert r["status"] == "measured", r
    assert r["angle"] == pytest.approx(angle, abs=1e-6)
    assert r["acute_angle"] == pytest.approx(acute, abs=1e-6)


def test_top_face_against_top_plane(query, faces):
    r = query.measure_element_angle(faces["+z"], "plane:1")
    assert r["acute_angle"] == pytest.approx(0.0, abs=1e-6)


def test_edge_against_its_own_face_is_parallel(query, faces):
    r = query.measure_element_angle(f"{faces['+z']}/edge:0", faces["+z"])
    assert r["angle"] == pytest.approx(0.0, abs=1e-6)


def test_vertical_edge_against_top_face_is_perpendicular(query, faces):
    # The -x face's edges are two along y and two along z; one of the first two
    # is vertical, so both 0 and 90 must appear among its edges.
    angles = sorted(
        round(query.measure_element_angle(f"{faces['-x']}/edge:{i}", faces["+z"])["angle"], 6)
        for i in range(4)
    )
    assert angles == [0.0, 0.0, 90.0, 90.0]


def test_bad_spec(query, faces):
    assert "Cannot read element" in query.measure_element_distance("side:1", faces["+z"])["error"]
    assert "out of range" in query.measure_element_distance("face:99", faces["+z"])["error"]
