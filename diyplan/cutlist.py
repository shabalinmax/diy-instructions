"""Раскрой и закупка.

Доски — 1D: First Fit Decreasing по длине с пропилом, перебор доступных длин (stock.options)
и замена каждой доски на самую дешёвую подходящую. Листы — 2D MaxRects (лучшее совпадение
короткой стороны) с поворотом деталей, если у материала не задано направление волокон (grain).

Подсказки: «укоротите детали на N мм — хватит на одну доску меньше» и «листа почти не нужно —
хватит обрезка W×H».
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .model import Project


@dataclass
class Piece:
    letter: str
    name: str
    length: float  # вдоль доски / по X листа
    width: float


@dataclass
class Placed:
    piece: Piece
    x: float
    y: float
    w: float  # по длине стока
    h: float  # по ширине стока


@dataclass
class StockUse:
    stock_id: str
    index: int
    width: float
    length: float
    price: float | None = None
    placed: list[Placed] = field(default_factory=list)

    @property
    def used_area(self):
        return sum(p.w * p.h for p in self.placed)


@dataclass
class Hint:
    code: str
    params: dict


def _pieces(prj: Project, stock_id: str) -> list[Piece]:
    res = []
    for p in prj.parts:
        if p.stock != stock_id:
            continue
        w, l = sorted(p.face_dims)
        res.append(Piece(p.letter, p.name, l, w))
    return res


def _options(st):
    return st.options or [{"width": st.width, "length": st.length, "price": st.price}]


# ---------- доски ----------

def _ffd(pieces, L, kerf):
    bins: list[list] = []   # [used, [Placed]]
    for pc in sorted(pieces, key=lambda p: -p.length):
        for b in bins:
            if b[0] + pc.length <= L + 1e-6:
                b[1].append(Placed(pc, b[0], 0, pc.length, pc.width))
                b[0] += pc.length + kerf
                break
        else:
            bins.append([pc.length + kerf, [Placed(pc, 0, 0, pc.length, pc.width)]])
    return [b[1] for b in bins]


def _cost(opt):
    return opt["price"] if opt.get("price") is not None else opt["length"] * opt.get("width", 1) / 1e6


def _plan_boards(sid, st, pieces, kerf):
    opts = sorted(_options(st), key=lambda o: o["length"])
    best = None
    for o in opts:
        if any(pc.length > o["length"] + 1e-6 for pc in pieces):
            continue
        bins = _ffd(pieces, o["length"], kerf)
        chosen = []
        for b in bins:  # каждую доску — самой дешёвой длины, в которую влезает её содержимое
            need = max(p.x + p.w for p in b)
            fit = [x for x in opts if x["length"] + 1e-6 >= need]
            chosen.append((min(fit, key=_cost), b))
        total = sum(_cost(x) for x, _ in chosen)
        if best is None or total < best[0] - 1e-9:
            best = (total, chosen)
    if best is None:
        return []
    return [StockUse(sid, i + 1, st.width, o["length"], o.get("price"), b) for i, (o, b) in enumerate(best[1])]


def _tight_hint(sid, st, pieces, kerf, used):
    """Если укоротить каждую деталь на пару миллиметров, хватит на одну доску меньше?"""
    L = max(o["length"] for o in _options(st))
    n = len(_ffd(pieces, L, kerf))
    for s in (1, 2, 3, 5, 8, 10):
        short = [Piece(p.letter, p.name, p.length - s, p.width) for p in pieces]
        if len(_ffd(short, L, kerf)) < n:
            return Hint("cut_tight", {"stock": st.name, "mm": s, "n": n - 1})
    return None


# ---------- листы ----------

def _maxrects(pieces, W, H, kerf, rotate=True):
    """MaxRects-BSSF. Пропил учитываем, раздувая детали и лист на kerf."""
    sheets = []
    for pc in sorted(pieces, key=lambda p: -p.length * p.width):
        placed = False
        for sh in sheets:
            if _place(sh, pc, kerf, rotate):
                placed = True
                break
        if not placed:
            sh = {"free": [(0.0, 0.0, W + kerf, H + kerf)], "placed": []}
            if not _place(sh, pc, kerf, rotate):
                return None
            sheets.append(sh)
    return [sh["placed"] for sh in sheets]


def _place(sh, pc, kerf, rotate):
    best = None
    for fx, fy, fw, fh in sh["free"]:
        for w, h in ((pc.length, pc.width), (pc.width, pc.length)) if rotate else ((pc.length, pc.width),):
            ww, hh = w + kerf, h + kerf
            if ww <= fw + 1e-6 and hh <= fh + 1e-6:
                score = (min(fw - ww, fh - hh), max(fw - ww, fh - hh))
                if best is None or score < best[0]:
                    best = (score, fx, fy, w, h)
    if best is None:
        return False
    _, x, y, w, h = best
    sh["placed"].append(Placed(pc, x, y, w, h))
    rx, ry, rw, rh = x, y, w + kerf, h + kerf
    free = []
    for fx, fy, fw, fh in sh["free"]:
        if rx >= fx + fw or rx + rw <= fx or ry >= fy + fh or ry + rh <= fy:
            free.append((fx, fy, fw, fh))
            continue
        if rx > fx:
            free.append((fx, fy, rx - fx, fh))
        if rx + rw < fx + fw - 1e-9:
            free.append((rx + rw, fy, fx + fw - rx - rw, fh))
        if ry > fy:
            free.append((fx, fy, fw, ry - fy))
        if ry + rh < fy + fh:
            free.append((fx, ry + rh, fw, fy + fh - ry - rh))
    free = [a for a in free if a[2] > 1e-6 and a[3] > 1e-6]
    sh["free"] = [a for i, a in enumerate(free)
                  if not any(j != i and a[0] >= b[0] and a[1] >= b[1] and a[0] + a[2] <= b[0] + b[2]
                             and a[1] + a[3] <= b[1] + b[3] and (a != b or j < i) for j, b in enumerate(free))]
    return True


def _plan_sheets(sid, st, pieces, kerf):
    opts = _options(st)
    rotate = not st.grain
    best = None
    for o in opts:
        sheets = _maxrects(pieces, o["length"], o["width"], kerf, rotate)
        if sheets is None:
            continue
        chosen = []
        for content in sheets:  # последний лист часто полупустой — может, влезет в меньший формат
            alt = []
            for x in opts:
                again = _maxrects([p.piece for p in content], x["length"], x["width"], kerf, rotate)
                if again is not None and len(again) == 1:
                    alt.append((x, again[0]))
            chosen.append(min(alt, key=lambda a: _cost(a[0])) if alt else (o, content))
        total = (sum(_cost(x) for x, _ in chosen), len(chosen))   # при равной цене — меньше листов
        if best is None or total < best[0]:
            best = (total, chosen)
    if best is None:
        return []
    return [StockUse(sid, i + 1, o["width"], o["length"], o.get("price"), c) for i, (o, c) in enumerate(best[1])]


def _offcut_hint(st, u: StockUse, kerf):
    """Лист заполнен меньше чем на треть — хватит куска."""
    if u.used_area / (u.width * u.length) > 0.33:
        return None
    w = math.ceil((max(p.x + p.w for p in u.placed) + kerf) / 50) * 50
    h = math.ceil((max(p.y + p.h for p in u.placed) + kerf) / 50) * 50
    return Hint("cut_offcut", {"stock": st.name, "n": u.index, "w": min(w, u.length), "h": min(h, u.width),
                               "pct": round(100 * u.used_area / (u.width * u.length))})


# ---------- вход ----------

def plan(prj: Project) -> list[StockUse]:
    return plan_with_hints(prj)[0]


def plan_with_hints(prj: Project):
    uses: list[StockUse] = []
    hints: list[Hint] = []
    k = prj.kerf
    for sid, st in prj.stock.items():
        pieces = _pieces(prj, sid)
        if not pieces:
            continue
        if st.kind == "board":
            got = _plan_boards(sid, st, pieces, k)
            h = _tight_hint(sid, st, pieces, k, got)
            if h:
                hints.append(h)
        else:
            got = _plan_sheets(sid, st, pieces, k)
            for u in got:
                h = _offcut_hint(st, u, k)
                if h:
                    hints.append(h)
        uses += got
    return uses, hints


def shopping(prj: Project, uses: list[StockUse], fmt=None) -> list[tuple[str, int]]:
    counts: dict[tuple, int] = {}
    for u in uses:
        key = (u.stock_id, u.width, u.length)
        counts[key] = counts.get(key, 0) + 1
    out = []
    for (sid, w, L), n in counts.items():
        st = prj.stock[sid]
        dims = fmt.dims(st.thickness, w, L) if fmt else f"{st.thickness:g}×{w:g}×{L:g} мм"
        out.append((f"{st.name}, {dims}", n))
    return out


def cost(uses: list[StockUse]):
    """Стоимость материала, если у всех использованных форматов есть цена."""
    if not uses or any(u.price is None for u in uses):
        return None
    return sum(u.price for u in uses)
