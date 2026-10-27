"""Раскрой: доски — 1D (First Fit Decreasing по длине), листы — 2D полками (guillotine shelf)."""
from __future__ import annotations

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
    placed: list[Placed] = field(default_factory=list)


def _pieces(prj: Project, stock_id: str) -> list[Piece]:
    res = []
    for p in prj.parts:
        if p.stock != stock_id:
            continue
        w, l = sorted(p.face_dims)
        res.append(Piece(p.letter, p.name, l, w))
    return res


def plan(prj: Project) -> list[StockUse]:
    uses: list[StockUse] = []
    k = prj.kerf
    for sid, st in prj.stock.items():
        pieces = _pieces(prj, sid)
        if not pieces:
            continue
        if st.kind == "board":
            bins: list[tuple[float, StockUse]] = []
            for pc in sorted(pieces, key=lambda p: -p.length):
                for i, (used, su) in enumerate(bins):
                    if used + pc.length <= st.length + 1e-6:
                        su.placed.append(Placed(pc, used, 0, pc.length, pc.width))
                        bins[i] = (used + pc.length + k, su)
                        break
                else:
                    su = StockUse(sid, len(bins) + 1)
                    su.placed.append(Placed(pc, 0, 0, pc.length, pc.width))
                    bins.append((pc.length + k, su))
            uses += [su for _, su in bins]
        else:
            sheets: list[dict] = []
            for pc in sorted(pieces, key=lambda p: -p.width):
                w, h = pc.length, pc.width
                if w > st.length:  # повернуть
                    w, h = h, w
                done = False
                for sh in sheets:
                    for shelf in sh["shelves"]:
                        if h <= shelf["h"] + 1e-6 and shelf["x"] + w <= st.length + 1e-6:
                            sh["use"].placed.append(Placed(pc, shelf["x"], shelf["y"], w, h))
                            shelf["x"] += w + k
                            done = True
                            break
                    if done:
                        break
                    if sh["y"] + h <= st.width + 1e-6:
                        sh["shelves"].append({"y": sh["y"], "h": h, "x": w + k})
                        sh["use"].placed.append(Placed(pc, 0, sh["y"], w, h))
                        sh["y"] += h + k
                        done = True
                        break
                if not done:
                    su = StockUse(sid, len(sheets) + 1)
                    su.placed.append(Placed(pc, 0, 0, w, h))
                    sheets.append({"use": su, "y": h + k, "shelves": [{"y": 0, "h": h, "x": w + k}]})
            uses += [s["use"] for s in sheets]
    return uses


def shopping(prj: Project, uses: list[StockUse], fmt=None) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for u in uses:
        counts[u.stock_id] = counts.get(u.stock_id, 0) + 1
    out = []
    for sid, n in counts.items():
        st = prj.stock[sid]
        dims = fmt.dims(st.thickness, st.width, st.length) if fmt else f"{st.thickness:g}×{st.width:g}×{st.length:g} мм"
        out.append((f"{st.name}, {dims}", n))
    return out
