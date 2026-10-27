import json
import re

import pytest

from conftest import box, model
from diyplan import cutlist
from diyplan.__main__ import main
from diyplan.i18n import MESSAGES, Fmt, inches_str
from diyplan.model import load, load_dict
from diyplan.pdf import build


def test_ffd_respects_kerf():
    parts = [box(f"p{i}", (i * 1000, 0, 0), (20, 100, 990)) for i in range(3)]
    prj = load_dict(model(parts))
    uses = cutlist.plan(prj)
    # 990 + 3 + 990 = 1983 ≤ 2000 → две детали на доску, третья на вторую
    assert len(uses) == 2
    for u in uses:
        end = max(p.x + p.w for p in u.placed)
        assert end <= 2000


def test_sheet_packing_fits():
    m = model([box(f"p{i}", (i * 700, 0, 0), (600, 18, 400)) for i in range(4)])
    m["stock"] = [{"id": "b20", "kind": "sheet", "name": "Ply", "thickness": 18, "width": 1220, "length": 2440}]
    for p in m["parts"]:
        p["stock"] = "b20"
    uses = cutlist.plan(load_dict(m))
    assert len(uses) == 1
    for pl in uses[0].placed:
        assert pl.x + pl.w <= 2440 and pl.y + pl.h <= 1220


@pytest.mark.parametrize("x, s", [(12.875, "12 7/8"), (0.75, "3/4"), (3.0, "3"), (1.999, "2")])
def test_inches_str(x, s):
    assert inches_str(x) == s


def test_fmt_units():
    assert Fmt("ru", "mm").len(326.4) == "326 мм"
    assert Fmt("en", "in").len(25.4 * 12.875) == "12 7/8″"


def test_message_catalogs_match():
    assert set(MESSAGES["ru"]) == set(MESSAGES["en"])


def _pages(path):
    with open(path, "rb") as f:
        return len(re.findall(rb"/Type\s*/Page[^s]", f.read()))


@pytest.mark.parametrize("lang, units", [("ru", "mm"), ("en", "in")])
def test_pdf_builds(example_path, tmp_path, lang, units):
    prj = load(example_path("titmouse-house.json"))
    prj.lang, prj.units = lang, units
    out = tmp_path / "x.pdf"
    build(prj, str(out))
    assert out.read_bytes()[:4] == b"%PDF"
    assert _pages(out) >= 5


def test_cli_json(example_path, capsys):
    rc = main(["check", example_path("birdhouse.json"), "--json"])
    rep = json.loads(capsys.readouterr().out)
    assert rc == 0 and rep["ok"] and rep["summary"]["parts"] == 6


def test_cli_refuses_to_build_broken(tmp_path, capsys):
    p = tmp_path / "m.json"
    p.write_text(json.dumps(model([box("a", (0, 0, 0), (100, 20, 300)), box("b", (50, 0, 0), (100, 20, 300))])))
    rc = main(["build", str(p), "-o", str(tmp_path / "o.pdf")])
    assert rc == 1 and not (tmp_path / "o.pdf").exists()


def test_pdf_paginates_large_model(tmp_path):
    parts = [box("base", (0, 0, 0), (2000, 200, 20))]
    for i in range(30):
        parts.append(box(f"p{i}", (i * 60, 0, 20), (20, 150 + i, 300), name=f"Стойка {i}"))
    steps = [{"title": "base", "add": ["base"]}]
    steps += [{"title": f"Стойка {i}", "add": [f"p{i}"], "text": "Длинный текст. " * (80 if i % 5 == 0 else 3)}
              for i in range(30)]
    m = model(parts, steps=steps, tips=["Совет. " * 60] * 12, tools=[f"Инструмент {i}" for i in range(40)])
    m["stock"][0]["length"] = 2500
    prj = load_dict(m)
    out = tmp_path / "big.pdf"
    build(prj, str(out))
    assert _pages(out) >= 18   # всё разошлось по страницам, а не наехало


FIXTURES = sorted((__import__("pathlib").Path(__file__).parent / "fixtures").glob("*.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_eval_fixtures_still_valid_and_render(path, tmp_path):
    """Модели, которые Claude написал по реальным запросам, не должны ломаться от правок движка."""
    from diyplan.model import errors_of, validate
    prj = load(str(path))
    assert errors_of(validate(prj)) == []
    build(prj, str(tmp_path / "x.pdf"))


def test_board_options_pick_cheapest_mix():
    # 3 детали по 900: на 2 м влезает две; дешевле взять 2 м + 1 м, чем две по 2 м
    parts = [box(f"p{i}", (i * 1000, 0, 0), (20, 100, 900)) for i in range(3)]
    m = model(parts)
    m["stock"][0].update(length=2000, price=400, options=[{"length": 1000, "price": 220}, {"length": 3000, "price": 700}])
    uses = cutlist.plan(load_dict(m))
    assert sorted(u.length for u in uses) == [1000, 2000]
    assert cutlist.cost(uses) == 620


def test_tight_cut_hint():
    parts = [box(f"p{i}", (i * 1300, 0, 0), (20, 100, 1000)) for i in range(2)]
    m = model(parts)
    m["stock"][0]["length"] = 2000          # 1000 + 3 + 1000 > 2000 — не хватает пропила
    uses, hints = cutlist.plan_with_hints(load_dict(m))
    assert len(uses) == 2 and [h.code for h in hints] == ["cut_tight"] and hints[0].params["mm"] == 2


def test_maxrects_rotates_and_respects_grain():
    pieces = [cutlist.Piece("A", "a", 1200, 300) for _ in range(4)] + [cutlist.Piece("B", "b", 900, 400)]
    sheets = cutlist._maxrects(pieces, 1525, 1525, 3, rotate=True)
    assert len(sheets) == 1
    for pl in sheets[0]:
        assert pl.x + pl.w <= 1525 + 1e-6 and pl.y + pl.h <= 1525 + 1e-6
    placed = sheets[0]
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            assert a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y


def test_offcut_hint_for_mostly_empty_sheet():
    m = model([box("a", (0, 0, 0), (400, 18, 300))])
    m["stock"] = [{"id": "b20", "kind": "sheet", "name": "Ply", "thickness": 18, "width": 1525, "length": 1525}]
    uses, hints = cutlist.plan_with_hints(load_dict(m))
    assert hints and hints[0].code == "cut_offcut"


def test_templates_only_where_useful(example_path):
    from diyplan.pdf import template_parts
    prj = load(example_path("birdhouse.json"))
    ids = {p.id for p, _ in template_parts(prj)}
    assert "front" in ids                      # леток ⌀50
    assert "floor" not in ids and "roof" not in ids
    m = model([box("f", (0, 0, 0), (600, 200, 20), holes=[{"d": 10, "at": [100, 100]}])])
    assert template_parts(load_dict(m)) == []   # мелкое отверстие сверлят по разметке
    m["templates"] = False
    m["parts"][0]["holes"][0]["d"] = 60
    assert template_parts(load_dict(m)) == []
