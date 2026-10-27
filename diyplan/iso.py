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
    def __init__(self, ref_parts, box, k=0, pad=0.06, extra=60, ref_points=None):
        self.k = k
        self.Rv = view_rot(k)
        x, y, w, h = box
        world = ref_points if ref_points is not None else [v for p in ref_parts for v in p.poly.verts]
        pts = [proj(G.mat_vec(self.Rv, v)) for v in world]
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
    for du, dv in hole.outline(n):
        p = [0.0, 0.0, 0.0]
        p[t] = part.size[t] if side > 0 else 0.0
        p[a] = hole.at[0] + du
        p[b] = hole.at[1] + dv
        pts.append(part.to_world(tuple(p)))
    return pts


def _face_point(part: Part, at, side: str):
    t = part.thick_axis
    a, b = part.face_axes
    p = [0.0, 0.0, 0.0]
    p[t] = part.size[t] if side == "+t" else 0.0
    p[a], p[b] = at
    e = [0.0, 0.0, 0.0]
    e[t] = 1.0 if side == "+t" else -1.0
    return part.to_world(tuple(p)), part.dir_to_world(tuple(e))


def draw_hardware(c, v: "View", part: Part):
    for hw in part.hardware:
        p, n = _face_point(part, hw.at, hw.side)
        x, y = v.pt(p)
        if not visible(v.n(n)):  # на невидимой стороне — пустой кружок в том же месте
            c.setStrokeColor(HexColor("#1E1E1E")); c.setLineWidth(0.8)
            c.circle(x, y, 3.0, fill=0, stroke=1)
            continue
        c.setFillColor(HexColor("#1E1E1E")); c.setStrokeColor(HexColor("#FFFFFF")); c.setLineWidth(0.8)
        c.circle(x, y, 3.4, fill=1, stroke=1)
        c.setFillColor(HexColor("#FFC93C"))
        c.circle(x, y, 1.3, fill=1, stroke=0)


def draw_part(c, v: View, part: Part, rpoly: G.Poly, style: str, ghost: bool = False):
    w = 1.3 if style in ("new", "focus") else 0.8
    if ghost:  # деталь загораживает новую — рисуем полупрозрачной, с пунктирным контуром
        c.saveState()
        c.setFillAlpha(0.28)
        c.setDash(2, 2)
    for f in rpoly.faces:
        if visible(f.n):
            _poly(c, [v.rpt(p) for p in f.pts], _shade(style, f.n), width=0.6 if ghost else w)
    if ghost:
        c.restoreState()
    for h in part.holes:
        for side in (1, -1):
            e = [0.0, 0.0, 0.0]
            e[part.thick_axis] = side
            if visible(v.n(part.dir_to_world(tuple(e)))):
                _poly(c, [v.pt(p) for p in _hole_points(part, h, side)], HOLE, width=0.8)


def draw_screw_mark(c, v: View, s: Screw, current: bool, hidden: bool = False):
    x, y = v.pt(s.point)
    if hidden:  # вход с невидимой стороны — пустой кружок в том же месте
        c.setStrokeColor(ACCENT)
        c.setLineWidth(0.9)
        c.circle(x, y, 2.4, fill=0, stroke=1)
        return
    r = 2.6 if current else 1.8
    c.setFillColor(ACCENT if current else HexColor("#8A8A8A"))
    c.setStrokeColor(HexColor("#FFFFFF"))
    c.setLineWidth(0.5)
    c.circle(x, y, r, fill=1, stroke=1)


DIM = HexColor("#1F5FBF")


def draw_dim(c, v: View, a3, b3, off3, label_text, font="DejaVu-Bold"):
    """Размерная линия между точками a3 и b3 (мир), вынесенная на off3."""
    a, b = v.pt(a3), v.pt(b3)
    a2, b2 = v.pt(G.add(a3, off3)), v.pt(G.add(b3, off3))
    c.setStrokeColor(DIM); c.setLineWidth(0.5); c.setDash(1.5, 1.5)
    c.line(*a, *a2); c.line(*b, *b2)
    c.setDash()
    c.setLineWidth(0.9)
    c.line(*a2, *b2)
    ang = math.atan2(b2[1] - a2[1], b2[0] - a2[0])
    for (px, py), sgn in ((a2, 1), (b2, -1)):
        hx, hy = px + sgn * 5 * math.cos(ang), py + sgn * 5 * math.sin(ang)
        p = c.beginPath()
        p.moveTo(px, py)
        p.lineTo(hx + 2 * math.sin(ang), hy - 2 * math.cos(ang))
        p.lineTo(hx - 2 * math.sin(ang), hy + 2 * math.cos(ang))
        p.close()
        c.setFillColor(DIM); c.drawPath(p, fill=1, stroke=0)
    mx, my = (a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2
    c.setFont(font, 8)
    w = c.stringWidth(label_text, font, 8) + 6
    c.setFillColor(HexColor("#FFFFFF")); c.setStrokeColor(DIM); c.setLineWidth(0.6)
    c.roundRect(mx - w / 2, my - 6, w, 12, 3, fill=1, stroke=1)
    c.setFillColor(DIM)
    c.drawCentredString(mx, my - 3, label_text)


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


def _bbox2d(pts):
    return min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)


def _overlap_frac(a, b):
    """Доля площади a, накрытая b (по габаритам)."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    return w * h / max((a[2] - a[0]) * (a[3] - a[1]), 1e-9)


def draw_scene(c, prj: Project, box, styles: dict[str, str], screws_cur=(), screws_old=(),
               ref_parts=None, arrows=True, labels=True, extra=70, view="front-right", dims=(),
               ref_points=None, ghosting=True):
    """Рисует сцену; возвращает (число видимых саморезов текущего шага, View).
    dims — размеры положения: (a3, b3, off3, текст)."""
    k = VIEWS.get(view, 0)
    parts = [prj.part(pid) for pid in styles]
    v = View(ref_parts or prj.parts, box, k=k, extra=extra, ref_points=ref_points)
    rpolys = [p.poly.transformed(v.Rv) for p in parts]
    order = draw_order(rpolys)

    # какие старые детали стоят перед новыми и прячут их — их делаем полупрозрачными
    boxes = [_bbox2d([proj(q) for q in rp.verts]) for rp in rpolys]
    pos = {i: n for n, i in enumerate(order)}
    ghosts = set()
    for i, p in enumerate(parts):
        if styles[p.id] != "new" or not ghosting:
            continue
        for j, q in enumerate(parts):
            if styles[q.id] == "old" and pos[j] > pos[i] and _overlap_frac(boxes[i], boxes[j]) > 0.25:
                ghosts.add(j)

    by_part: dict[str, list] = {}
    for s in screws_old:
        by_part.setdefault(s.through, []).append((s, False))
    for s in screws_cur:
        by_part.setdefault(s.through, []).append((s, True))
    shown = 0
    hidden_cur = []
    for i in order:
        p = parts[i]
        draw_part(c, v, p, rpolys[i], styles[p.id], ghost=i in ghosts)
        draw_hardware(c, v, p)
        for s, cur in by_part.get(p.id, []):
            if visible(v.n(s.normal)):
                draw_screw_mark(c, v, s, cur)
                shown += cur
            elif cur:
                hidden_cur.append(s)
    for s in hidden_cur:  # поверх всего: где саморез входит с обратной стороны
        draw_screw_mark(c, v, s, True, hidden=True)

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
    for a3, b3, off3, txt in dims:
        draw_dim(c, v, a3, b3, off3, txt)
    if labels:
        for p, rp in zip(parts, rpolys):
            if styles[p.id] not in ("new", "focus"):
                continue
            pts = [v.rpt(q) for f in rp.faces if visible(f.n) for q in f.pts]
            label(c, sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts), p.letter)
    return shown, v


def draw_zoom(c, prj: Project, main_view: View, center, R, styles, screws, edge_label: str, spec_label: str):
    """Выноска-лупа: крупно один узел — где входят саморезы и отступ от края.
    center/R — место под лупу, заранее зарезервированное в рамке картинки."""
    if not screws:
        return
    s0 = screws[0]
    group = [s for s in screws if s.through == s0.through and s.into == s0.into]
    pts = []
    for p in [s.point for s in group[:2]]:
        for dx in (-45, 45):
            for dy in (-45, 45):
                for dz in (-45, 45):
                    pts.append(G.add(p, (dx, dy, dz)))
    cx, cy = center
    anchor = main_view.pt(s0.point)
    c.setStrokeColor(ACCENT); c.setLineWidth(0.8)
    c.circle(anchor[0], anchor[1], 8, fill=0, stroke=1)
    ang = math.atan2(cy - anchor[1], cx - anchor[0])
    dist = math.hypot(cx - anchor[0], cy - anchor[1])
    if dist > R + 8:
        c.line(anchor[0] + 8 * math.cos(ang), anchor[1] + 8 * math.sin(ang),
               cx - R * math.cos(ang), cy - R * math.sin(ang))
    c.saveState()
    c.setFillColor(HexColor("#FFFFFF")); c.circle(cx, cy, R, fill=1, stroke=0)
    path = c.beginPath(); path.circle(cx, cy, R)
    c.clipPath(path, stroke=0, fill=0)
    draw_scene(c, prj, (cx - R, cy - R, 2 * R, 2 * R), dict(styles), group, (), arrows=False, labels=False,
               ref_points=pts, extra=0, view=_view_name(main_view.k), ghosting=False)
    c.restoreState()
    c.setStrokeColor(ACCENT); c.setLineWidth(1.2)
    c.circle(cx, cy, R, fill=0, stroke=1)
    c.setFillColor(ACCENT)
    c.setFont("DejaVu-Bold", 7)
    c.drawCentredString(cx, cy - R - 9, spec_label)
    c.setFont("DejaVu", 7)
    c.drawCentredString(cx, cy - R - 18, edge_label)


def _view_name(k):
    return next(n for n, i in VIEWS.items() if i == k)
