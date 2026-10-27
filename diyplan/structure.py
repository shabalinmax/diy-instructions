"""Прикидка прочности: прогиб горизонтальных деталей и устойчивость на опрокидывание.

Это инженерная оценка «на салфетке», а не расчёт по нормам: однопролётная балка на двух опорах,
модуль упругости по типу материала, коэффициент ползучести для длительной нагрузки.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import geom as G

G_ACC = 9.81

# E (ГПа, вдоль пролёта), плотность (кг/м³), коэффициент ползучести для длительной нагрузки
MATERIALS = {
    "pine": (9.0, 500, 1.5),
    "spruce": (9.0, 450, 1.5),
    "oak": (11.0, 700, 1.5),
    "birch": (12.0, 650, 1.5),
    "beech": (12.0, 700, 1.5),
    "plywood": (6.5, 650, 1.6),
    "osb": (4.0, 620, 2.0),
    "mdf": (3.0, 750, 2.0),
    "chipboard": (2.5, 680, 2.5),
}
KEYWORDS = [
    (("фанер", "plywood", "ply"), "plywood"),
    (("осп", "osb"), "osb"),
    (("мдф", "mdf"), "mdf"),
    (("лдсп", "дсп", "chipboard", "particle", "melamine"), "chipboard"),
    (("дуб", "oak"), "oak"),
    (("берёз", "берез", "birch"), "birch"),
    (("бук", "beech"), "beech"),
    (("ель", "ели", "spruce"), "spruce"),
    (("сосн", "pine", "хвоя", "лиственн", "2x", "2×", "lumber", "доска", "board"), "pine"),
]

SAG_WARN = 360   # прогиб больше L/360 — заметно на глаз
SAG_BAD = 180    # больше L/180 — полка «улыбается», надо усиливать
DEFAULT_SHELF_KG_PER_M = 30.0   # книги на полке глубиной ~200–300 мм
TIP_WARN_DEG = 12.0             # опрокидывается от лёгкого толчка
ANCHOR_HEIGHT = 600.0           # выше — рекомендуем крепить к стене


def material_of(stock) -> str:
    m = getattr(stock, "material", "") or ""
    if m in MATERIALS:
        return m
    name = (stock.name or "").lower()
    for keys, mat in KEYWORDS:
        if any(k in name for k in keys):
            return mat
    return "pine"


@dataclass
class Sag:
    part: str
    span: float        # мм
    load_kg: float
    point: bool
    sag: float         # мм, с учётом ползучести
    limit_warn: float
    limit_bad: float

    @property
    def level(self):
        return "bad" if self.sag > self.limit_bad else "warn" if self.sag > self.limit_warn else "ok"


def _horizontal(part):
    e = [0.0, 0.0, 0.0]
    e[part.thick_axis] = 1.0
    n = part.dir_to_world(tuple(e))
    return abs(n[2]) > 0.95


def shelf_sag(prj, part, contacts) -> Sag | None:
    """Прогиб горизонтальной детали между опорами. None — если опор меньше двух по длине."""
    if not _horizontal(part) or (part.load_kg is None and "load_bearing" not in prj.safety):
        return None
    a, b = part.face_axes
    dims = {a: part.size[a], b: part.size[b]}
    long_ax = max(dims, key=dims.get)
    short_ax = min(dims, key=dims.get)
    ev = [0.0, 0.0, 0.0]
    ev[long_ax] = 1.0
    e = part.dir_to_world(tuple(ev))
    # опоры: детали снизу и детали, в которые деталь упирается торцами
    proj = []
    for c in contacts:
        if part.id not in (c.a, c.b):
            continue
        n = c.n if c.a == part.id else G.mul(c.n, -1)   # от детали к опоре
        below = n[2] < -0.95
        side = abs(n[2]) < 0.05
        if not (below or side):
            continue
        along = [G.dot(q, e) for q in c.pts]
        if below and max(along) - min(along) >= 0.5 * dims[long_ax]:
            return None   # лежит на бруске/царге по всей длине — пролёта поперёк почти нет
        cen = tuple(sum(p[i] for p in c.pts) / len(c.pts) for i in range(3))
        proj.append(G.dot(cen, e))
    if len(proj) < 2:
        return None
    span = max(proj) - min(proj)
    if span < 0.3 * dims[long_ax]:
        return None
    E_gpa, rho, creep = MATERIALS[material_of(prj.stock[part.stock])]
    E = E_gpa * 1000.0                      # Н/мм²
    bw, h = dims[short_ax], part.thickness
    I = bw * h ** 3 / 12.0                  # мм⁴
    point = part.load_type == "point"
    if part.load_kg is not None:
        load = part.load_kg
    else:
        load = DEFAULT_SHELF_KG_PER_M * span / 1000.0
    self_kg = rho * part.size[0] * part.size[1] * part.size[2] * 1e-9
    w_self = self_kg * G_ACC / span          # Н/мм
    sag_self = 5 * w_self * span ** 4 / (384 * E * I)
    if point:
        P = load * G_ACC
        sag_load = P * span ** 3 / (48 * E * I)
        k = 1.0                               # кратковременная нагрузка (сели и встали)
    else:
        w = load * G_ACC / span
        sag_load = 5 * w * span ** 4 / (384 * E * I)
        k = creep                             # книги стоят годами
    total = (sag_self + sag_load) * k
    return Sag(part.id, span, load, point, total, span / SAG_WARN, span / SAG_BAD)


@dataclass
class Stability:
    height: float
    com: tuple
    margin: float        # мм от проекции центра масс до края опоры (<0 — снаружи)
    tip_deg: float       # угол наклона, при котором опрокинется


def _hull(pts):
    pts = sorted(set((round(x, 3), round(y, 3)) for x, y in pts))
    if len(pts) < 3:
        return pts
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def stability(prj, sags: list[Sag]) -> Stability | None:
    if not prj.parts:
        return None
    zs = [v[2] for p in prj.parts for v in p.poly.verts]
    z0, z1 = min(zs), max(zs)
    foot = [(v[0], v[1]) for p in prj.parts for v in p.poly.verts if v[2] < z0 + 1.0]
    hull = _hull(foot)
    if len(hull) < 3:
        return None
    # центр масс: детали по объёму × плотность + полезная нагрузка в центрах полок
    tot, mx, my, mz = 0.0, 0.0, 0.0, 0.0
    for p in prj.parts:
        _, rho, _ = MATERIALS[material_of(prj.stock[p.stock])]
        m = rho * p.size[0] * p.size[1] * p.size[2] * 1e-9
        cx, cy, cz = p.center
        tot += m; mx += m * cx; my += m * cy; mz += m * cz
    by_id = {s.part: s for s in sags}
    for pid, s in by_id.items():
        if s.point:
            continue  # человек на табурете — отдельная история, не «живёт» на мебели
        cx, cy, cz = prj.part(pid).center
        tot += s.load_kg; mx += s.load_kg * cx; my += s.load_kg * cy; mz += s.load_kg * cz
    com = (mx / tot, my / tot, mz / tot)
    margin = math.inf
    inside = True
    for i in range(len(hull)):
        (x0, y0), (x1, y1) = hull[i], hull[(i + 1) % len(hull)]
        L = math.hypot(x1 - x0, y1 - y0)
        dist = ((x1 - x0) * (com[1] - y0) - (y1 - y0) * (com[0] - x0)) / L  # >0 — внутри (CCW)
        inside &= dist >= 0
        margin = min(margin, dist)
    h = com[2] - z0
    tip = math.degrees(math.atan2(max(margin, 0.0), h)) if h > 0 else 90.0
    return Stability(z1 - z0, com, margin, tip if inside else 0.0)
