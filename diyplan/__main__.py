"""CLI.

    diyplan check model.json [--json]
    diyplan build model.json -o out.pdf [--force]
    diyplan preview model.json -o pages/      # PNG страниц для самопроверки (нужен pdftoppm)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter

from . import __version__, cutlist
from .i18n import Fmt
from .model import errors_of, load, plan_screws, structure_report, validate


def _summary(prj, fmt: Fmt) -> dict:
    screws = Counter(s.key for v in plan_screws(prj).values() for s in v)
    uses, hints = cutlist.plan_with_hints(prj)
    sags, stab = structure_report(prj)
    from .pdf import hint_text
    return {
        "cut_hints": [hint_text(fmt, h) for h in hints],
        "materials_cost": cutlist.cost(uses),
        "loads": [{"part": x.part, "load_kg": round(x.load_kg, 1), "type": "point" if x.point else "uniform",
                   "span_mm": round(x.span), "sag_mm": round(x.sag, 1), "sag_limit_mm": round(x.limit_warn, 1),
                   "level": x.level} for x in sags],
        "stability": None if not stab else {"height_mm": round(stab.height), "tip_angle_deg": round(stab.tip_deg, 1),
                                            "com_mm": [round(v) for v in stab.com]},
        "parts": len(prj.parts),
        "steps": len(prj.steps),
        "stock": [{"name": name, "count": n} for name, n in cutlist.shopping(prj, uses, fmt)],
        "sheets_used_pct": [round(100 * u.used_area / (u.width * u.length)) for u in uses
                            if prj.stock[u.stock_id].kind == "sheet"],
        "screws": [{"kind": k[0], "spec": fmt.screw(*k), "diameter_mm": k[1], "length_mm": k[2], "count": n}
                   for k, n in sorted(screws.items())],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="diyplan", description="JSON model → validated assembly-instruction PDF")
    ap.add_argument("--version", action="version", version=f"diyplan {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "build", "preview"):
        sp = sub.add_parser(name)
        sp.add_argument("model")
        sp.add_argument("--lang", choices=["ru", "en"], help="переопределить язык модели")
        sp.add_argument("--units", choices=["mm", "in"], help="единицы вывода")
        sp.add_argument("--json", action="store_true", help="машиночитаемый вывод")
        if name != "check":
            sp.add_argument("-o", "--out", default="instruction.pdf" if name == "build" else "preview")
            sp.add_argument("--force", action="store_true", help="собрать даже с ошибками")
    a = ap.parse_args(argv)

    prj = load(a.model)
    if a.lang:
        prj.lang = a.lang
    if a.units:
        prj.units = a.units
    fmt = Fmt(prj.lang, prj.units)
    issues = validate(prj)
    if not errors_of(issues):
        from .pdf import layout_issues
        issues += layout_issues(prj)
    errors = errors_of(issues)
    summary = _summary(prj, fmt) if not errors else None

    if a.json:
        report = {"ok": not errors, "issues": [i.as_dict(fmt) for i in issues], "summary": summary}
    else:
        for i in issues:
            print(f"{fmt.t('error' if i.level == 'error' else 'warning')}: {i.message(fmt)}")
        if summary:
            print(fmt.t("summary_ok", parts=summary["parts"], steps=summary["steps"]))
            for s in summary["stock"]:
                print(f"  {s['name']} — {s['count']} {fmt.t('pcs')}")
            for s in summary["screws"]:
                print(f"  {fmt.t(s['kind'])} {s['spec']} — {s['count']} {fmt.t('pcs')}")

    if a.cmd in ("build", "preview"):
        if errors and not a.force:
            if a.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print(fmt.t("not_built"))
            return 1
        from .pdf import build
        pdf_path = a.out if a.cmd == "build" else os.path.join(a.out, "instruction.pdf")
        if a.cmd == "preview":
            os.makedirs(a.out, exist_ok=True)
        build(prj, pdf_path)
        pages = []
        if a.cmd == "preview":
            if not shutil.which("pdftoppm"):
                print("pdftoppm not found (poppler-utils) — PNG preview skipped", file=sys.stderr)
            else:
                subprocess.run(["pdftoppm", "-r", "60", "-png", pdf_path, os.path.join(a.out, "page")], check=True)
                pages = sorted(f for f in os.listdir(a.out) if f.endswith(".png"))
        if a.json:
            report["pdf"] = pdf_path
            report["pages"] = [os.path.join(a.out, p) for p in pages]
        else:
            print(f"PDF: {pdf_path}")
            for p in pages:
                print(f"  {os.path.join(a.out, p)}")
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
