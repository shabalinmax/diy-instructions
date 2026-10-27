"""CLI: python -m diyplan check model.json | python -m diyplan build model.json -o out.pdf"""
import argparse
import sys
from collections import Counter

from . import cutlist
from .model import load, plan_screws, validate


def main(argv=None):
    ap = argparse.ArgumentParser(prog="diyplan", description="JSON-модель изделия → PDF-инструкция по сборке")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ck = sub.add_parser("check", help="проверить модель и показать сводку")
    ck.add_argument("model")
    bd = sub.add_parser("build", help="собрать PDF")
    bd.add_argument("model")
    bd.add_argument("-o", "--out", default="instruction.pdf")
    bd.add_argument("--force", action="store_true", help="собрать даже с ошибками")
    a = ap.parse_args(argv)

    prj = load(a.model)
    errors, warnings = validate(prj)
    for e in errors:
        print(f"ОШИБКА: {e}")
    for w in warnings:
        print(f"Внимание: {w}")

    if not errors:
        screws = Counter(s.spec for v in plan_screws(prj).values() for s in v)
        uses = cutlist.plan(prj)
        print(f"OK: {len(prj.parts)} деталей, {len(prj.steps)} шагов")
        for name, n in cutlist.shopping(prj, uses):
            print(f"  {name} — {n} шт")
        for spec, n in sorted(screws.items()):
            print(f"  саморез {spec} — {n} шт")

    if a.cmd == "build":
        if errors and not a.force:
            print("PDF не собран: сначала исправьте ошибки.")
            return 1
        from .pdf import build
        build(prj, a.out)
        print(f"PDF: {a.out}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
