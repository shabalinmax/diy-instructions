import math

import pytest

from diyplan import geom as G
from diyplan.model import _box


def cube(o, s):
    return _box(s, 0).translated(o)


def test_box_topology():
    P = _box((100, 20, 300), 1)
    assert len(P.faces) == 6
    assert len(P.verts) == 8
    assert {f.tag for f in P.faces} == {"+t", "-t", "edge"}


def test_corner_cuts_make_pentagon():
    P = _box((140, 20, 290), 1)
    P = P.with_plane(G.plane_through((0, 0, 220), (70, 0, 290), (0, 1, 220), (70, 10, 100), "cut"))
    P = P.with_plane(G.plane_through((70, 0, 290), (140, 0, 220), (70, 1, 290), (70, 10, 100), "cut"))
    face = P.face("-t")
    assert len(face.pts) == 5
    # площадь пятиугольника: прямоугольник 140×220 + треугольник 140×70/2
    assert abs(G.poly_area(face.pts, face.n)) == pytest.approx(140 * 220 + 140 * 70 / 2, rel=1e-6)


@pytest.mark.parametrize("dx, expected", [(105, 5), (100, 0), (97, -3)])
def test_separation(dx, expected):
    A = cube((0, 0, 0), (100, 100, 100))
    B = cube((dx, 0, 0), (100, 100, 100))
    assert G.separation(A, B) == pytest.approx(expected, abs=1e-6)


def test_sweep_hits_at_gap():
    A = cube((0, 0, 150), (100, 100, 20))
    B = cube((0, 0, 0), (100, 100, 100))
    t_in, t_out = G.sweep(A, B, (0, 0, -1))
    assert t_in == pytest.approx(50)
    assert t_out > t_in


def test_sweep_misses():
    A = cube((300, 0, 150), (100, 100, 20))
    B = cube((0, 0, 0), (100, 100, 100))
    assert G.sweep(A, B, (0, 0, -1)) is None


def test_face_contact_area():
    A = cube((0, 0, 0), (100, 100, 100))
    B = cube((100, 50, 0), (20, 100, 100))
    found = [G.face_contact(fa, fb) for fa in A.faces for fb in B.faces]
    pts = [p for p in found if p]
    assert len(pts) == 1
    n = (1.0, 0.0, 0.0)
    assert abs(G.poly_area(pts[0], n)) == pytest.approx(50 * 100)


@pytest.mark.parametrize("axis, end, comp", [("x", (0, 1, 0), 2), ("y", (1, 0, 0), 2)])
def test_rotation_raises_positive_end(axis, end, comp):
    R = G.rotation(axis, 30)
    v = G.mat_vec(R, end)
    assert v[comp] == pytest.approx(math.sin(math.radians(30)))


def test_rotated_box_is_still_a_box():
    R = G.rotation("y", 37)
    P = _box((100, 50, 20), 2).transformed(R, (10, 20, 30))
    assert len(P.faces) == 6
    lo, hi = P.extent(G.mat_vec(R, (0, 0, 1)))
    assert hi - lo == pytest.approx(20)


def test_separating_axis_order():
    view = G.unit((1, -1, 1))
    back = cube((0, 100, 0), (100, 20, 100))
    front = cube((0, 0, 0), (100, 20, 100))
    assert G.separating_axis(back, front, view) == 1    # front ближе
    assert G.separating_axis(front, back, view) == -1
