from collections import Counter

import pytest

from conftest import box, codes, model
from diyplan.model import errors_of, load, load_dict, plan_screws, validate


# ---------- примеры из репозитория — «золотые» ----------

@pytest.mark.parametrize("name, screws, parts", [
    ("birdhouse.json", 24, 6),
    ("titmouse-house.json", 30, 7),
])
def test_examples_are_clean(example_path, name, screws, parts):
    prj = load(example_path(name))
    issues = validate(prj)
    assert issues == [], [i.code for i in issues]
    assert len(prj.parts) == parts
    total = sum(len(v) for v in plan_screws(prj).values())
    assert total == screws


def test_mirrored_parts_share_letter(example_path):
    prj = load(example_path("titmouse-house.json"))
    assert prj.part("side_l").letter == prj.part("side_r").letter
    assert prj.part("front").letter != prj.part("back").letter  # у переднего — леток


def test_roof_snaps_onto_walls(example_path):
    prj = load(example_path("birdhouse.json"))
    roof = prj.part("roof")
    # крыша касается всех четырёх стенок, а не висит и не врезается
    from diyplan.model import find_contact
    for wall in ("front", "back", "side_l", "side_r"):
        assert find_contact(roof, prj.part(wall)) is not None, wall


def test_short_roof_slides_to_ridge(example_path):
    prj = load(example_path("titmouse-house.json"))
    from diyplan.model import find_contact
    c = find_contact(prj.part("roof_l"), prj.part("roof_r"))
    assert c is not None and c.area == pytest.approx(20 * 200, rel=1e-3)


# ---------- ошибки ----------

def test_overlap_is_error():
    prj = load_dict(model([box("a", (0, 0, 0), (100, 20, 300)), box("b", (90, 0, 0), (100, 20, 300))]))
    assert "overlap" in codes(validate(prj), "error")


def test_disconnected_is_error():
    prj = load_dict(model([box("a", (0, 0, 0), (100, 20, 300)), box("b", (500, 0, 0), (100, 20, 300))]))
    assert "disconnected" in codes(validate(prj), "error")


def test_small_gap_is_warning():
    prj = load_dict(model([
        box("a", (0, 0, 0), (100, 20, 300)),
        box("b", (0, 20, 0), (20, 100, 300)),
        box("c", (102, 0, 0), (100, 20, 300)),   # зазор 2 мм от a
        box("d", (100, 20, 0), (102, 100, 20)),
    ]))
    issues = validate(prj)
    assert "gap" in codes(issues, "warning")


def test_part_too_long_for_board():
    prj = load_dict(model([box("a", (0, 0, 0), (2500, 20, 100))]))
    assert "too_long" in codes(validate(prj), "error")


def test_thickness_mismatch():
    prj = load_dict(model([box("a", (0, 0, 0), (100, 18, 300))]))
    assert "thickness_mismatch" in codes(validate(prj), "error")


def test_hole_outside_and_near_edge():
    prj = load_dict(model([box("a", (0, 0, 0), (100, 20, 300), holes=[{"d": 50, "at": [10, 150]}])]))
    assert "hole_outside" in codes(validate(prj), "error")
    prj = load_dict(model([box("a", (0, 0, 0), (100, 20, 300), holes=[{"d": 50, "at": [32, 150]}])]))
    assert codes(validate(prj)) == ["hole_near_edge"]


def test_steps_must_install_each_part_once():
    parts = [box("a", (0, 0, 0), (100, 20, 300)), box("b", (0, 20, 0), (20, 100, 300))]
    prj = load_dict(model(parts, steps=[{"title": "1", "add": ["a", "a"]}]))
    got = codes(validate(prj), "error")
    assert "part_installed_twice" in got and "part_not_installed" in got


def test_snap_to_later_part_is_error():
    parts = [
        box("roof", (0, 0, 500), (100, 100, 20), snap={"to": ["lid"], "dir": [0, 0, -1]}),
        box("lid", (0, 0, 300), (100, 100, 20), snap={"to": ["base"]}),
        box("base", (0, 0, 0), (100, 100, 20)),
    ]
    prj = load_dict(model(parts))
    assert "snap_target_not_ready" in codes(validate(prj), "error")


def test_snap_miss_is_error():
    parts = [box("base", (0, 0, 0), (100, 100, 20)),
             box("top", (500, 0, 300), (100, 100, 20), snap={"to": ["base"]})]
    assert "snap_miss" in codes(validate(load_dict(model(parts))), "error")


def test_end_to_end_joint_is_glue_only():
    parts = [box("a", (0, 0, 0), (300, 100, 20)), box("b", (300, 0, 0), (300, 100, 20))]
    issues = validate(load_dict(model(parts)))
    assert "joint_glue_only" in codes(issues, "warning")


def test_missing_fields_reported_not_crash():
    prj = load_dict({"title": "x", "stock": [], "parts": [{"id": "a"}], "steps": []})
    got = codes(validate(prj), "error")
    assert got.count("missing_field") >= 3


def test_unknown_stock():
    p = box("a", (0, 0, 0), (100, 20, 300))
    p["stock"] = "nope"
    assert "unknown_stock" in codes(validate(load_dict(model([p]))), "error")


# ---------- единицы ----------

def test_inch_model_is_converted():
    m = model([box("a", (0, 0, 0), (4, 0.75, 12))], units="in")
    m["stock"][0].update(thickness=0.75, width=8, length=96)
    prj = load_dict(m)
    assert errors_of(validate(prj)) == []
    assert prj.part("a").thickness == pytest.approx(19.05)


# ---------- крепёж ----------

def test_screws_go_through_face_into_end():
    # боковина стоит на торце дна: саморез через боковину в торец дна
    parts = [box("floor", (20, 0, 0), (140, 140, 20)), box("side", (0, 0, 0), (20, 140, 300))]
    prj = load_dict(model(parts, steps=[{"title": "1", "add": ["floor", "side"]}]))
    screws = plan_screws(prj)[0]
    assert screws and all(s.through == "side" and s.into == "floor" for s in screws)
    assert Counter(s.spec for s in screws) == Counter({"3.5×50": len(screws)})


# ---------- правила крепежа ----------

from diyplan import geom as G  # noqa: E402
from diyplan.model import CLEAR, _shaft  # noqa: E402


def _all(prj, issues=None):
    return [s for v in plan_screws(prj, issues).values() for s in v]


def test_corner_screws_do_not_collide():
    # дно, к нему боковина (саморезы по x) и фасад (саморезы по y) — в углу ряды пересекаются
    parts = [box("floor", (20, 20, 0), (140, 140, 20)),
             box("side", (0, 20, 0), (20, 140, 300)),
             box("front", (0, 0, 0), (160, 20, 300))]
    prj = load_dict(model(parts, steps=[{"title": "1", "add": ["floor", "side"]}, {"title": "2", "add": ["front"]}]))
    screws = _all(prj)
    assert len(screws) >= 6
    for i, a in enumerate(screws):
        for b in screws[i + 1:]:
            assert G.seg_seg_distance(*_shaft(a), *_shaft(b)) >= (a.d + b.d) / 2 + CLEAR - 1e-6


def test_screw_avoids_hole():
    # отверстие в боковине прямо на линии ряда саморезов в торец полки
    parts = [box("shelf", (20, 0, 100), (300, 200, 20)),
             box("side", (0, 0, 0), (20, 200, 400), holes=[{"d": 12, "at": [100, 110]}])]
    prj = load_dict(model(parts, steps=[{"title": "1", "add": ["shelf", "side"]}]))
    side = prj.part("side")
    hole_c = side.to_world((0.0, 100.0, 110.0))
    hole_e = side.to_world((20.0, 100.0, 110.0))
    for s in _all(prj):
        assert G.seg_seg_distance(*_shaft(s), hole_c, hole_e) >= 6 + s.d / 2


def test_screw_would_poke_through_thin_panel():
    # доска 20 мм прикручивается пластью к пласти фанеры 10 мм: заглубиться некуда
    m = model([box("thick", (0, 0, 10), (300, 200, 20)), box("thin", (0, 0, 0), (300, 200, 10), stock="ply")],
              steps=[{"title": "1", "add": ["thin"]}, {"title": "2", "add": ["thick"]}])
    m["stock"].append({"id": "ply", "kind": "sheet", "name": "Ply", "thickness": 10, "width": 1220, "length": 2440})
    issues = []
    screws = _all(load_dict(m), issues)
    assert not [s for s in screws if s.through == "thick"]
    assert "screw_too_long" in codes(issues)


def test_narrow_edge_is_skipped():
    # 6-мм ДВП торцом к доске: в такую кромку саморез не ставим
    m = model([box("board", (0, 0, 0), (300, 200, 20)), box("hb", (0, 0, 20), (300, 6, 200), stock="hb")])
    m["stock"].append({"id": "hb", "kind": "sheet", "name": "HB", "thickness": 6, "width": 1220, "length": 2440})
    issues = []
    screws = _all(load_dict(m), issues)
    assert screws == [] and "screw_short_joint" in codes(issues)


def test_screws_not_closer_than_edge_min():
    from diyplan.model import EDGE_MIN
    parts = [box("floor", (20, 0, 0), (140, 140, 20)), box("side", (0, 0, 0), (20, 140, 300))]
    prj = load_dict(model(parts, steps=[{"title": "1", "add": ["floor", "side"]}]))
    for s in _all(prj):
        y = s.point[1]
        assert EDGE_MIN - 1e-6 <= y <= 140 - EDGE_MIN + 1e-6
