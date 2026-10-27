"""Изометрический рендер сборки на reportlab-канвас.

Камера смотрит сверху под 30°. Ракурс — поворот модели вокруг вертикали
("front-right" по умолчанию, "front-left", "back-left", "back-right").
Детали — выпуклые многогранники: у каждой рисуем только грани, смотрящие на зрителя,
а порядок деталей определяем разделяющими плоскостями (SAT) и топологической сортировкой.
"""
from __future__ import annotations

import math

from reportlab.lib.colors import Color, HexColor

from . import geom as G
from .model import Part, Project, Screw, find_contact

C30 = math.cos(math.radians(30))
S30 = 0.5
VIEW_DIR = G.unit((1.0, -1.0, 1.0))  # к зрителю, в отрендеренных координатах

VIEWS = {"front-right": 0, "front-left": 1, "back-left": 2, "back-right": 3}

PALETTE = {
    "old": ("#F4E6CB", "#E3CDA2", "#CFB283"),   # верх, фасад, бок
    "new": ("#FFE08A", "#FFC93C", "#F0A920"),
    "focus": ("#FFE08A", "#FFC93C", "#F0A920"),
}
INK = HexColor("#1E1E1E")
HOLE = HexColor("#3B2A1C")
ACCENT = HexColor("#D9381E")


def view_rot(k):
    return G.rotation("z", 90 * k)


def proj(p):
    x, y, z = p
    return ((x + y) * C30, z + (y - x) * S30)


def visible(n) -> bool:
    return G.dot(n, VIEW_DIR) > 0.02


def _shade(style, n):
    top, front, side = (HexColor(c) for c in PALETTE[style])
    w = (max(n[2], 0), max(-n[1], 0), max(n[0], 0))
    s = sum(w) or 1
    r = sum(c.red * k for c, k in zip((top, front, side), w)) / s
    g = sum(c.green * k for c, k in zip((top, front, side), w)) / s
    b = sum(c.blue * k for c, k in zip((top, front, side), w)) / s
    return Color(r, g, b)


def draw_order(polys: list[G.Poly]) -> list[int]:
    n = len(polys)
    bbs = []
    for P in polys:
        pts = [proj(v) for v in P.verts]
        bbs.append((min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)))
    edges = {i: set() for i in range(n)}
    indeg = [0] * n
    for i in range(n):
        for j in range(i + 1, n):
            A, B = bbs[i], bbs[j]
            if A[2] <= B[0] + 1e-6 or B[2] <= A[0] + 1e-6 or A[3] <= B[1] + 1e-6 or B[3] <= A[1] + 1e-6:
                continue
            s = G.separating_axis(polys[i], polys[j], VIEW_DIR)
            if s == 1:      # j ближе — рисуем i раньше
                edges[i].add(j); indeg[j] += 1
            elif s == -1:
                edges[j].add(i); indeg[i] += 1
    depth = lambda i: G.dot(polys[i].centroid, VIEW_DIR)
    ready = sorted([i for i in range(n) if indeg[i] == 0], key=depth)
    out = []
    while ready:
        i = ready.pop(0)
        out.append(i)
        for j in edges[i]:
            indeg[j] -= 1
            if indeg[j] == 0:
                ready.append(j)
        ready.sort(key=depth)
    if len(out) < n:
        out += sorted([i for i in range(n) if i not in out], key=depth)
    return out


class View:
    def __init__(self, ref_parts, box, k=0, pad=0.06, extra=60):
        self.k = k
        self.Rv = view_rot(k)
        x, y, w, h = box
        pts = [proj(G.mat_vec(self.Rv, v)) for p in ref_parts for v in p.poly.verts]
        bx0, by0 = min(p[0] for p in pts) - extra, min(p[1] for p in pts) - extra
        bx1, by1 = max(p[0] for p in pts) + extra, max(p[1] for p in pts) + extra
        self.s = min(w * (1 - pad) / (bx1 - bx0), h * (1 - pad) / (by1 - by0))
        self.ox = x + (w - (bx1 - bx0) * self.s) / 2 - bx0 * self.s
        self.oy = y + (h - (by1 - by0) * self.s) / 2 - by0 * self.s

    def rpt(self, p_rendered):
        X, Y = proj(p_rendered)
        return self.ox + X * self.s, self.oy + Y * self.s

    def pt(self, p_world):
        return self.rpt(G.mat_vec(self.Rv, p_world))

    def n(self, n_world):
        return G.mat_vec(self.Rv, n_world)


def _poly(c, pts, fill, stroke=INK, width=0.8):
    path = c.beginPath()
    path.moveTo(*pts[0])
    for p in pts[1:]:
        path.lineTo(*p)
    path.close()
    c.setFillColor(HexColor(fill) if isinstance(fill, str) else fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(width)
    c.setLineJoin(1)
    c.drawPath(path, fill=1, stroke=1)


def _hole_points(part: Part, hole, side: int, n=40):
    t = part.thick_axis
    a, b = part.face_axes
    pts = []
    for i in range(n):
        ang = 2 * math.pi * i / n
        p = [0.0, 0.0, 0.0]
        p[t] = part.size[t] if side > 0 else 0.0
        p[a] = hole.at[0] + hole.d / 2 * math.cos(ang)
        p[b] = hole.at[1] + hole.d / 2 * math.sin(ang)
        pts.append(part.to_world(tuple(p)))
    return pts


def draw_part(c, v: View, part: Part, rpoly: G.Poly, style: str):
    w = 1.3 if style in ("new", "focus") else 0.8
    for f in rpoly.faces:
        if visible(f.n):
            _poly(c, [v.rpt(p) for p in f.pts], _shade(style, f.n), width=w)
    for h in part.holes:
        for side in (1, -1):
            e = [0.0, 0.0, 0.0]
            e[part.thick_axis] = side
            if visible(v.n(part.dir_to_world(tuple(e)))):
                _poly(c, [v.pt(p) for p in _hole_points(part, h, side)], HOLE, width=0.8)


def draw_screw_mark(c, v: View, s: Screw, current: bool):
    x, y = v.pt(s.point)
    r = 2.6 if current else 1.8
    c.setFillColor(ACCENT if current else HexColor("#8A8A8A"))
    c.setStrokeColor(HexColor("#FFFFFF"))
    c.setLineWidth(0.5)
    c.circle(x, y, r, fill=1, stroke=1)


def arrow(c, p0, p1, color=INK, width=1.6, head=7):
    c.setStrokeColor(color)
    c.setFillColor(color)
    c.setLineWidth(width)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    bx, by = p1[0] - head * math.cos(ang), p1[1] - head * math.sin(ang)
    c.line(p0[0], p0[1], bx, by)
    path = c.beginPath()
    path.moveTo(*p1)
    path.lineTo(bx + head * 0.45 * math.sin(ang), by - head * 0.45 * math.cos(ang))
    path.lineTo(bx - head * 0.45 * math.sin(ang), by + head * 0.45 * math.cos(ang))
    path.close()
    c.drawPath(path, fill=1, stroke=0)


def approach_dir(part: Part, placed: list[Part]):
    """Откуда подводить деталь: направление, по которому её можно унести, ни во что не врезавшись.
    Сначала пробуем нормали площадок контакта (от большей к меньшей), потом оси."""
    contacts = [ct for q in placed if (ct := find_contact(part, q))]
    if not contacts:
        return None
    contacts.sort(key=lambda ct: -ct.area)
    cands = [G.mul(ct.n, -1) for ct in contacts]
    cands += [(0, 0, -1), (0, 0, 1), (0, -1, 0), (1, 0, 0), (-1, 0, 0), (0, 1, 0)]
    P = part.poly
    others = [q.poly for q in placed]
    for d in cands:
        free = True
        for Q in others:
            iv = G.sweep(P, Q, d)
            if iv and iv[1] > 1e-3:
                free = False
                break
        if free:
            return d
    return cands[0]


def label(c, x, y, text, r=9, fill="#1E1E1E", fg="#FFFFFF", font="DejaVu-Bold", size=10):
    c.setFillColor(HexColor(fill))
    c.setStrokeColor(HexColor("#FFFFFF"))
    c.setLineWidth(1.2)
    c.circle(x, y, r, fill=1, stroke=1)
    c.setFillColor(HexColor(fg))
    c.setFont(font, size)
    c.drawCentredString(x, y - size * 0.36, text)


def draw_scene(c, prj: Project, box, styles: dict[str, str], screws_cur=(), screws_old=(),
               ref_parts=None, arrows=True, labels=True, extra=70, view="front-right") -> int:
    """Рисует сцену; возвращает число видимых саморезов текущего шага."""
    k = VIEWS.get(view, 0)
    parts = [prj.part(pid) for pid in styles]
    v = View(ref_parts or prj.parts, box, k=k, extra=extra)
    rpolys = [p.poly.transformed(v.Rv) for p in parts]

    by_part: dict[str, list] = {}
    for s in screws_old:
        by_part.setdefault(s.through, []).append((s, False))
    for s in screws_cur:
        by_part.setdefault(s.through, []).append((s, True))
    shown = 0
    for i in draw_order(rpolys):
        p = parts[i]
        draw_part(c, v, p, rpolys[i], styles[p.id])
        for s, cur in by_part.get(p.id, []):
            if visible(v.n(s.normal)):
                draw_screw_mark(c, v, s, cur)
                shown += cur

    placed = [prj.part(pid) for pid, st in styles.items() if st == "old"]
    new = [prj.part(pid) for pid, st in styles.items() if st in ("new", "focus")]
    if arrows:
        for p in new:
            d = approach_dir(p, placed)
            if not d:
                continue
            lo, hi = p.poly.extent(d)
            ctr = p.center
            half = (hi - lo) / 2
            arrow(c, v.pt(G.add(ctr, G.mul(d, half + 140))), v.pt(G.add(ctr, G.mul(d, half + 20))), color=ACCENT)
    if labels:
        for p, rp in zip(parts, rpolys):
            if styles[p.id] not in ("new", "focus"):
                continue
            pts = [v.rpt(q) for f in rp.faces if visible(f.n) for q in f.pts]
            label(c, sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts), p.letter)
    return shown
