from collections import Counter

import pytest

from conftest import box, codes, model
from diyplan.model import errors_of, load, load_dict, plan_screws, validate


# ---------- примеры из репозитория — «золотые» ----------

@pytest.mark.parametrize("name, screws, parts", [
    ("wall-shelf.json", 15, 4),
    ("workbench-in.json", None, 15),
    ("shoe-rack.json", None, 8),
    ("stool.json", 24, 6),
    ("birdhouse.json", 24, 6),
    ("titmouse-house.json", 30, 7),
])
def test_examples_are_clean(example_path, name, screws, parts):
    prj = load(example_path(name))
    issues = validate(prj)
    assert issues == [], [i.code for i in issues]
    assert len(prj.parts) == parts
    total = sum(len(v) for v in plan_screws(prj).values())
    assert screws is None or total == screws


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


# ---------- правки по прогону ----------

def test_boards_side_by_side_are_a_seam_not_a_problem():
    # сиденье из двух досок на двух ножках: доски касаются длинными кромками
    parts = [box("leg_l", (0, 0, 0), (20, 300, 400)), box("leg_r", (780, 0, 0), (20, 300, 400)),
             box("seat_a", (0, 0, 400), (800, 150, 20)), box("seat_b", (0, 150, 400), (800, 150, 20))]
    issues = validate(load_dict(model(parts)))
    assert "joint_glue_only" not in codes(issues)


def test_thick_stock_gets_longer_screws():
    m = model([box("floor", (40, 0, 0), (200, 140, 40)), box("side", (0, 0, 0), (40, 140, 300))],
              steps=[{"title": "1", "add": ["floor", "side"]}])
    m["stock"][0]["thickness"] = 40
    screws = [s for v in plan_screws(load_dict(m)).values() for s in v]
    assert screws and all(s.length >= 90 for s in screws)   # ≈ 2,5 × 40


def test_chipboard_edge_gets_confirmat():
    m = model([box("bottom", (16, 0, 0), (568, 300, 16)), box("side", (0, 0, 0), (16, 300, 500))],
              steps=[{"title": "1", "add": ["bottom", "side"]}])
    m["stock"] = [{"id": "b20", "kind": "sheet", "name": "ЛДСП белая", "thickness": 16, "width": 1830, "length": 2750}]
    screws = [s for v in plan_screws(load_dict(m)).values() for s in v]
    assert screws and {s.kind for s in screws} == {"confirmat"} and screws[0].d == 7


def test_hole_shapes_and_repeat():
    p = box("floor", (0, 0, 0), (600, 200, 20), holes=[
        {"d": 10, "at": [100, 100], "repeat": {"n": 5, "step": [100, 0]}, "name": "Дренаж"},
    ])
    prj = load_dict(model([p]))
    assert len(prj.part("floor").holes) == 5
    door = box("front", (0, 0, 0), (400, 20, 400), holes=[{"shape": "arch", "w": 200, "h": 250, "at": [200, 140]}])
    assert "hole_outside" not in codes(validate(load_dict(model([door]))))
    bad = box("front", (0, 0, 0), (400, 20, 400), holes=[{"shape": "rect", "w": 200, "h": 380, "at": [200, 150]}])
    assert "hole_outside" in codes(validate(load_dict(model([bad]))), "error")


def test_hole_overlap_warns():
    p = box("a", (0, 0, 0), (400, 20, 300), holes=[{"d": 50, "at": [100, 150]}, {"d": 50, "at": [140, 150]}])
    assert "hole_overlap" in codes(validate(load_dict(model([p]))))


def test_hole_blocked_by_neighbour():
    floor = box("floor", (0, 0, 40), (600, 200, 20), holes=[{"d": 10, "at": [60, 100], "name": "Дренаж"}])
    feet = [box("foot_a", (40, 0, 20), (40, 200, 20)), box("foot_b", (520, 0, 20), (40, 200, 20))]
    issues = validate(load_dict(model([floor] + feet)))
    assert "hole_blocked" in codes(issues)


def test_gaps_ok_suppresses_gap_warning():
    parts = [box("a", (0, 0, 0), (100, 20, 300)), box("b", (0, 20, 0), (20, 100, 300)),
             box("c", (102, 0, 0), (100, 20, 300)), box("d", (100, 20, 0), (102, 100, 20))]
    assert "gap" not in codes(validate(load_dict(model(parts, gaps_ok=[["a", "c"]]))))


def test_hardware_markers_load():
    p = box("board", (0, 0, 0), (600, 20, 140),
            hardware=[{"name": "Крючок", "at": [100, 70], "repeat": {"n": 4, "step": [130, 0]}}])
    prj = load_dict(model([p]))
    assert [h.name for h in prj.part("board").hardware] == ["Крючок"] * 4


# ---------- прочность ----------

def test_sag_matches_beam_formula():
    from diyplan.structure import MATERIALS, shelf_sag
    from diyplan.model import all_contacts
    parts = [box("l", (0, 0, 0), (20, 200, 300)), box("r", (820, 0, 0), (20, 200, 300)),
             box("shelf", (20, 0, 280), (800, 200, 20), load_kg=20)]
    prj = load_dict(model(parts, safety=["load_bearing"]))
    x = shelf_sag(prj, prj.part("shelf"), all_contacts(prj))
    E, rho, creep = MATERIALS["pine"]
    I = 200 * 20 ** 3 / 12
    w = 20 * 9.81 / x.span
    expect_load = 5 * w * x.span ** 4 / (384 * E * 1000 * I) * creep
    assert x.span == pytest.approx(800, abs=1)        # между площадками опоры
    assert x.sag > expect_load                        # плюс собственный вес
    assert x.sag == pytest.approx(expect_load, rel=0.1)


def test_explicit_heavy_load_is_error():
    parts = [box("l", (0, 0, 0), (20, 200, 300)), box("r", (1220, 0, 0), (20, 200, 300)),
             box("shelf", (20, 0, 280), (1200, 200, 20), load_kg=60)]
    issues = validate(load_dict(model(parts, safety=["load_bearing"])))
    assert "sag_bad" in codes(issues, "error")


def test_load_unspecified_warns():
    parts = [box("l", (0, 0, 0), (20, 200, 300)), box("r", (420, 0, 0), (20, 200, 300)),
             box("seat", (20, 0, 280), (400, 200, 20))]
    assert "load_unspecified" in codes(validate(load_dict(model(parts, safety=["load_bearing"]))))


def test_tall_narrow_tips_over():
    # стойка 1800×200: центр масс высоко, основание узкое
    parts = [box("l", (0, 0, 0), (20, 150, 1800)), box("r", (580, 0, 0), (20, 150, 1800)),
             box("top", (20, 0, 1780), (560, 150, 20)), box("bottom", (20, 0, 0), (560, 150, 20))]
    issues = validate(load_dict(model(parts)))
    assert "tip_over" in codes(issues)
    issues = validate(load_dict(model(parts, safety=["wall_mount"])))
    assert "tip_over" not in codes(issues)


# ---------- узлы и повторы ----------

def _cat_like(steps):
    parts = [box("floor", (20, 20, 0), (300, 300, 20)),
             box("side_l", (0, 20, 0), (20, 300, 300)), box("side_r", (320, 20, 0), (20, 300, 300)),
             box("front", (0, 0, 0), (340, 20, 300)), box("back", (0, 320, 0), (340, 20, 300)),
             box("lid", (0, 0, 300), (340, 340, 20)),
             box("rim_l", (0, 0, 320), (20, 340, 60)), box("rim_r", (320, 0, 320), (20, 340, 60))]
    m = model(parts, steps=steps)
    m["stock"][0]["width"] = 400
    return load_dict(m)


def test_subassembly_screws_split_between_group_and_attach():
    from diyplan.model import step_scenes
    steps = [{"title": "box", "add": ["floor", "side_l", "side_r", "front", "back"]},
             {"title": "bed", "group": "bed", "add": ["lid", "rim_l", "rim_r"]},
             {"title": "attach", "attach": "bed"}]
    prj = _cat_like(steps)
    assert errors_of(validate(prj)) == []
    sc = step_scenes(prj)
    assert sc[1] == ([], ["lid", "rim_l", "rim_r"], "group")
    assert sc[2][2] == "attach" and set(sc[2][1]) == {"lid", "rim_l", "rim_r"}
    per = plan_screws(prj)
    bed_ids = {"lid", "rim_l", "rim_r"}
    assert all({s.through, s.into} <= bed_ids for s in per[1])           # в узле — только внутри узла
    assert per[2] and all(len({s.through, s.into} & bed_ids) == 1 for s in per[2])  # при установке — узел к коробу


def test_attach_unknown_group_is_error():
    steps = [{"title": "all", "add": ["floor", "side_l", "side_r", "front", "back", "lid", "rim_l", "rim_r"]},
             {"title": "attach", "attach": "nope"}]
    assert "attach_unknown" in codes(validate(_cat_like(steps)), "error")


def test_group_not_attached_warns():
    steps = [{"title": "box", "add": ["floor", "side_l", "side_r", "front", "back"]},
             {"title": "bed", "group": "bed", "add": ["lid", "rim_l", "rim_r"]}]
    assert "group_not_attached" in codes(validate(_cat_like(steps)))


# ---------- прогон 2 ----------

def test_seat_on_two_aprons_spans_across():
    from diyplan.structure import shelf_sag
    from diyplan.model import all_contacts
    parts = [box("leg_l", (0, 0, 0), (20, 300, 400)), box("leg_r", (580, 0, 0), (20, 300, 400)),
             box("apron_f", (20, 0, 300), (560, 20, 100)), box("apron_b", (20, 280, 300), (560, 20, 100)),
             box("seat", (0, 0, 400), (600, 300, 20), load_kg=120, load_type="point")]
    prj = load_dict(model(parts, safety=["load_bearing"]))
    x = shelf_sag(prj, prj.part("seat"), all_contacts(prj))
    assert x is not None and x.span == pytest.approx(280, abs=1)   # между царгами, поперёк


def test_middle_support_splits_span():
    from diyplan.structure import shelf_sag
    from diyplan.model import all_contacts
    parts = [box("l", (0, 0, 0), (20, 300, 400)), box("r", (1180, 0, 0), (20, 300, 400)),
             box("mid", (590, 0, 0), (20, 300, 400)),
             box("top", (0, 0, 400), (1200, 300, 20), load_kg=30)]
    prj = load_dict(model(parts, safety=["load_bearing"]))
    x = shelf_sag(prj, prj.part("top"), all_contacts(prj))
    assert x is not None and x.span == pytest.approx(590, abs=2)


def test_floating_part_is_reported_with_gap():
    parts = [box("a", (20, 0, 0), (300, 200, 20)), box("b", (0, 0, 0), (20, 200, 300)),
             box("c", (325, 0, 0), (20, 200, 300)), box("d", (0, 0, 300), (345, 200, 20))]
    issues = validate(load_dict(model(parts)))
    assert "step_not_touching" in codes(issues)


def test_attach_several_groups_with_loose_parts():
    parts = [box("leg_a", (0, 0, 0), (20, 100, 400)), box("rail_a", (0, 100, 380), (20, 400, 20)),
             box("leg_b", (0, 500, 0), (20, 100, 400)),
             box("leg_c", (580, 0, 0), (20, 100, 400)), box("rail_c", (580, 100, 380), (20, 400, 20)),
             box("leg_d", (580, 500, 0), (20, 100, 400)),
             box("apron", (20, 0, 300), (560, 20, 100))]
    steps = [{"title": "l", "group": "L", "add": ["leg_a", "rail_a", "leg_b"]},
             {"title": "r", "group": "R", "add": ["leg_c", "rail_c", "leg_d"], "same_as": 1, "mirror": True},
             {"title": "join", "attach": ["L", "R"], "add": ["apron"]}]
    m = model(parts, steps=steps)
    m["stock"][0]["width"] = 400
    prj = load_dict(m)
    assert errors_of(validate(prj)) == []
    per = plan_screws(prj)
    assert per[2] and all("apron" in (s.through, s.into) for s in per[2])
