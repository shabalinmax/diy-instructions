"""Геометрия без внешних зависимостей: выпуклые многогранники в H-представлении.

Деталь = пересечение полупространств n·x <= d (коробка заготовки + резы).
Грани строятся клиппингом большого квадрата в каждой плоскости остальными плоскостями.
Пересечения, касания, зазоры и «сдвиг до касания» — через теорему о разделяющей оси (SAT).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

TOL = 1e-6
BIG = 1e5


# ---------- векторы ----------

def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def mul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a): return math.sqrt(dot(a, a))


def unit(a):
    n = norm(a)
    return mul(a, 1 / n) if n > 1e-12 else (0.0, 0.0, 0.0)


def mat_vec(R, v):
    return tuple(R[i][0] * v[0] + R[i][1] * v[1] + R[i][2] * v[2] for i in range(3))


def mat_mul(A, B):
    return tuple(tuple(sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def transpose(R):
    return tuple(tuple(R[j][i] for j in range(3)) for i in range(3))


IDENT = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def rotation(axis: str, deg: float):
    """Поворот так, что при deg > 0 поднимается конец детали со стороны +ось:
    axis='x' — поднимается дальний (+y) конец, axis='y' — правый (+x) конец,
    axis='z' — поворот в плане против часовой стрелки (если смотреть сверху)."""
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    if axis == "x":
        return ((1, 0, 0), (0, c, -s), (0, s, c))
    if axis == "y":
        return ((c, 0, -s), (0, 1, 0), (s, 0, c))
    if axis == "z":
        return ((c, -s, 0), (s, c, 0), (0, 0, 1))
    raise ValueError(f"неизвестная ось поворота {axis}")


# ---------- плоскости и многогранник ----------

@dataclass
class Plane:
    n: tuple
    d: float
    tag: str = "edge"  # "+t"/"-t" — пласти детали, "edge" — кромки/торцы, "cut"/"trim" — резы

    def transformed(self, R, o):
        n2 = mat_vec(R, self.n)
        return Plane(n2, self.d + dot(n2, o), self.tag)


@dataclass
class Face:
    plane: Plane
    pts: list  # вершины по часовой стрелке... нет: против часовой, если смотреть снаружи

    @property
    def n(self): return self.plane.n

    @property
    def tag(self): return self.plane.tag


def _basis(n):
    a = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = unit(cross(a, n))
    v = cross(n, u)
    return u, v


def clip_polygon(pts, n, d):
    """Оставить часть многоугольника с n·x <= d (Sutherland–Hodgman)."""
    out = []
    if not pts:
        return out
    prev = pts[-1]
    pd = dot(n, prev) - d
    for cur in pts:
        cd = dot(n, cur) - d
        if cd <= 1e-9:
            if pd > 1e-9:
                out.append(add(prev, mul(sub(cur, prev), pd / (pd - cd))))
            out.append(cur)
        elif pd <= 1e-9:
            out.append(add(prev, mul(sub(cur, prev), pd / (pd - cd))))
        prev, pd = cur, cd
    return out


def poly_area(pts, n):
    s = (0.0, 0.0, 0.0)
    for i in range(len(pts)):
        s = add(s, cross(pts[i], pts[(i + 1) % len(pts)]))
    return dot(s, n) / 2


def _dedupe(pts, eps=1e-7):
    out = []
    for p in pts:
        if not out or norm(sub(p, out[-1])) > eps:
            out.append(p)
    if len(out) > 1 and norm(sub(out[0], out[-1])) <= eps:
        out.pop()
    return out


@dataclass
class Poly:
    planes: list
    faces: list = field(default_factory=list)
    verts: list = field(default_factory=list)

    def __post_init__(self):
        self.rebuild()

    def rebuild(self):
        faces = []
        for i, pl in enumerate(self.planes):
            u, v = _basis(pl.n)
            c = mul(pl.n, pl.d)
            pts = [add(c, add(mul(u, su * BIG), mul(v, sv * BIG))) for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            for j, other in enumerate(self.planes):
                if j != i:
                    pts = clip_polygon(pts, other.n, other.d)
                    if not pts:
                        break
            pts = _dedupe(pts)
            if len(pts) >= 3 and poly_area(pts, pl.n) > 1e-4:
                faces.append(Face(pl, pts))
        self.faces = faces
        vs = []
        for f in faces:
            for p in f.pts:
                if all(norm(sub(p, q)) > 1e-6 for q in vs):
                    vs.append(p)
        self.verts = vs

    @property
    def empty(self):
        return len(self.faces) < 4

    def transformed(self, R=IDENT, o=(0.0, 0.0, 0.0)):
        return Poly([p.transformed(R, o) for p in self.planes])

    def translated(self, o):
        return self.transformed(IDENT, o)

    def with_plane(self, pl: Plane):
        for q in self.planes:  # не добавлять дубликаты
            if dot(q.n, pl.n) > 1 - 1e-9 and abs(q.d - pl.d) < 1e-6:
                return Poly(list(self.planes))
        return Poly(self.planes + [pl])

    @property
    def centroid(self):
        vs = self.verts
        return tuple(sum(v[i] for v in vs) / len(vs) for i in range(3))

    def face(self, tag):
        for f in self.faces:
            if f.tag == tag:
                return f
        return None

    def extent(self, n):
        ps = [dot(n, v) for v in self.verts]
        return min(ps), max(ps)

    def edges(self):
        out = []
        for f in self.faces:
            for i in range(len(f.pts)):
                out.append(unit(sub(f.pts[(i + 1) % len(f.pts)], f.pts[i])))
        return out


def plane_through(p0, p1, p2, keep, tag="trim"):
    """Плоскость по трём точкам; сохраняется полупространство, где лежит точка keep."""
    n = unit(cross(sub(p1, p0), sub(p2, p0)))
    if norm(n) < 0.5:
        raise ValueError("точки плоскости лежат на одной прямой")
    d = dot(n, p0)
    if dot(n, keep) > d:
        n, d = mul(n, -1), -d
    return Plane(n, d, tag)


# ---------- SAT ----------

def _axes(A: Poly, B: Poly):
    cand = [f.n for f in A.faces] + [f.n for f in B.faces]
    ea, eb = A.edges(), B.edges()
    for e1 in _uniq(ea):
        for e2 in _uniq(eb):
            c = cross(e1, e2)
            if norm(c) > 1e-6:
                cand.append(unit(c))
    return _uniq(cand)


def _uniq(vs):
    out = []
    for v in vs:
        if all(abs(dot(v, q)) < 1 - 1e-9 for q in out):
            out.append(v)
    return out


def separation(A: Poly, B: Poly):
    """>0 — зазор (по лучшей разделяющей оси), <=0 — глубина взаимного проникновения со знаком минус."""
    best = -math.inf
    for n in _axes(A, B):
        a0, a1 = A.extent(n)
        b0, b1 = B.extent(n)
        gap = max(b0 - a1, a0 - b1)
        best = max(best, gap)
    return best


def separating_axis(A: Poly, B: Poly, view):
    """Ось, разделяющая A и B и не перпендикулярная направлению взгляда.
    Возвращает +1, если B ближе к зрителю, -1 если A ближе, 0 если порядок не важен."""
    seen = False
    for n in _axes(A, B):
        a0, a1 = A.extent(n)
        b0, b1 = B.extent(n)
        s = dot(n, view)
        if a1 <= b0 + 1e-6:
            side = 1  # B со стороны +n
        elif b1 <= a0 + 1e-6:
            side = -1
        else:
            continue
        seen = True
        if abs(s) > 1e-6:
            return side if s > 0 else -side
    return 0 if seen else None


def sweep(A: Poly, B: Poly, u):
    """Интервал t, при котором A, сдвинутая на t·u, пересекается с B. None — не встретятся."""
    t_in, t_out = -math.inf, math.inf
    for n in _axes(A, B):
        a0, a1 = A.extent(n)
        b0, b1 = B.extent(n)
        s = dot(n, u)
        if abs(s) < 1e-12:
            if a1 <= b0 + 1e-9 or b1 <= a0 + 1e-9:
                return None
            continue
        t1, t2 = (b0 - a1) / s, (b1 - a0) / s
        lo, hi = min(t1, t2), max(t1, t2)
        t_in, t_out = max(t_in, lo), min(t_out, hi)
        if t_in >= t_out:
            return None
    return t_in, t_out


# ---------- контакт граней ----------

def _to2d(pts, origin, u, v):
    return [(dot(sub(p, origin), u), dot(sub(p, origin), v)) for p in pts]


def _clip2d(subj, clip):
    out = subj
    for i in range(len(clip)):
        a, b = clip[i], clip[(i + 1) % len(clip)]
        inp, out = out, []
        if not inp:
            break
        def inside(p):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= -1e-9
        def inter(p, q):
            x1, y1, x2, y2 = p[0], p[1], q[0], q[1]
            x3, y3, x4, y4 = a[0], a[1], b[0], b[1]
            den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
            t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
            return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
        prev = inp[-1]
        for cur in inp:
            if inside(cur):
                if not inside(prev):
                    out.append(inter(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(inter(prev, cur))
            prev = cur
    return out


def area2d(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts))) / 2


def face_contact(fa: Face, fb: Face, tol=0.05):
    """Общая площадка двух граней, лежащих в одной плоскости навстречу друг другу."""
    if dot(fa.n, fb.n) > -1 + 1e-6 or abs(fa.plane.d + fb.plane.d) > tol:
        return None
    u, v = _basis(fa.n)
    o = fa.pts[0]
    pa = _to2d(fa.pts, o, u, v)
    pb = _to2d(list(reversed(fb.pts)), o, u, v)
    inter = _clip2d(pa, pb)
    if len(inter) < 3 or area2d(inter) < 1.0:
        return None
    return [add(o, add(mul(u, x), mul(v, y))) for x, y in inter]


def principal_axis(pts3, n):
    """Длинная ось площадки (для строки саморезов)."""
    u, v = _basis(n)
    c = tuple(sum(p[i] for p in pts3) / len(pts3) for i in range(3))
    q = _to2d(pts3, c, u, v)
    # стороны многоугольника взвешиваем по длине — для прямоугольника даёт его оси
    sxx = syy = sxy = 0.0
    for i in range(len(q)):
        a, b = q[i], q[(i + 1) % len(q)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        if L < 1e-9:
            continue
        sxx += dx * dx / L; syy += dy * dy / L; sxy += dx * dy / L
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    e1 = add(mul(u, math.cos(ang)), mul(v, math.sin(ang)))
    e2 = cross(n, e1)
    return c, e1, e2


def point_in_convex(pts3, p, n):
    for i in range(len(pts3)):
        a, b = pts3[i], pts3[(i + 1) % len(pts3)]
        if dot(cross(sub(b, a), sub(p, a)), n) < -1e-6:
            return False
    return True
