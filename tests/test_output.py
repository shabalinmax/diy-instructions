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
