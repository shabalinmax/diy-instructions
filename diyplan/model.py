"""Модель изделия: детали, контакты, проверки, автокрепёж.

Все размеры в мм. Оси: x — ширина (слева направо), y — глубина (от фасада назад),
z — высота.

Деталь — заготовка-брусок (`size`) из доски или листа, к которой можно применить:
  cuts    — прямые резы поперёк пласти (срезать углы: фронтон, трапеция);
  rotate  — наклон детали (скат крыши);
  trim    — рез плоскостью в мировых координатах (скос торца/кромки под крышу);
  snap    — сдвинуть деталь вдоль направления до касания с другими деталями.
Результат — выпуклый многогранник (geom.Poly).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from . import geom as G

SCREW_LENGTHS = [16, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100]
CONTACT_TOL = 0.05   # мм: грани считаются касающимися
GAP_WARN = 10.0      # мм: меньший зазор — подозрительно похоже на ошибку


class Mm(float):
    """Длина в мм внутри параметров сообщения — при выводе форматируется в нужные единицы."""


@dataclass
class Issue:
    level: str          # "error" | "warning"
    code: str
    parts: list = field(default_factory=list)
    params: dict = field(default_factory=dict)

    def message(self, fmt) -> str:
        kw = {}
        for k, v in self.params.items():
            if isinstance(v, Mm):
                kw[k] = fmt.len(v)
            elif isinstance(v, (list, tuple, set)):
                kw[k] = ", ".join(map(str, v))
            else:
                kw[k] = v
        return fmt.t(self.code, **kw)

    def as_dict(self, fmt) -> dict:
        return {"level": self.level, "code": self.code, "parts": list(self.parts),
                "message": self.message(fmt)}


def err(code, ids=(), **params):
    return Issue("error", code, list(ids), params)


def warn(code, ids=(), **params):
    return Issue("warning", code, list(ids), params)


@dataclass
class Hole:
    d: float
    at: tuple[float, float]  # центр в осях пласти заготовки, от её минимального угла
    name: str = "Отверстие"


@dataclass
class Part:
    id: str
    name: str
    stock: str
    size: tuple[float, float, float]
    origin: tuple = (0.0, 0.0, 0.0)
    R: tuple = G.IDENT
    holes: list[Hole] = field(default_factory=list)
    removable: bool = False
    fasten_to: list[str] = field(default_factory=list)
    note: str = ""
    letter: str = ""
    local: G.Poly | None = None  # форма в координатах заготовки
    raw_snaps: list = field(default_factory=list)

    # --- заготовка ---
    @property
    def thick_axis(self) -> int:
        return min(range(3), key=lambda i: self.size[i])

    @property
    def thickness(self) -> float:
        return self.size[self.thick_axis]

    @property
    def face_axes(self) -> tuple[int, int]:
        a = [i for i in range(3) if i != self.thick_axis]
        return a[0], a[1]

    @property
    def face_dims(self) -> tuple[float, float]:
        """Габарит детали на пласти — его и выпиливаем из доски/листа."""
        a, b = self.face_axes
        vs = self.local.verts
        return (max(v[a] for v in vs) - min(v[a] for v in vs),
                max(v[b] for v in vs) - min(v[b] for v in vs))

    def profile(self, tag="-t"):
        """Контур пласти в 2D-осях заготовки."""
        f = self.local.face(tag)
        a, b = self.face_axes
        return [(p[a], p[b]) for p in f.pts] if f else []

    def bevels(self) -> list[float]:
        """Скосы торцов/кромок (угол от прямого реза), градусы."""
        e = [0, 0, 0]
        e[self.thick_axis] = 1
        out = []
        for f in self.local.faces:
            if f.tag in ("cut", "trim"):
                ang = math.degrees(math.asin(min(1, abs(G.dot(f.n, e)))))
                if ang > 0.5:
                    out.append(round(ang, 1))
        return sorted(out)

    # --- мир ---
    @property
    def poly(self) -> G.Poly:
        return self.local.transformed(self.R, self.origin)

    @property
    def center(self):
        return self.poly.centroid

    def to_world(self, p):
        return G.add(G.mat_vec(self.R, p), self.origin)

    def dir_to_world(self, v):
        return G.mat_vec(self.R, v)

    def signature(self):
        """Одинаковые детали получают одну букву. Деталь можно перевернуть, поэтому
        сравниваем обе пласти с точностью до зеркальных отражений."""
        W, H = self.size[self.face_axes[0]], self.size[self.face_axes[1]]
        variants = []
        for mu in (False, True):
            for mv in (False, True):
                f = lambda u, v: (round(W - u if mu else u), round(H - v if mv else v))
                profs = tuple(sorted(tuple(sorted(f(u, v) for u, v in self.profile(tag))) for tag in ("-t", "+t")))
                holes = tuple(sorted((h.d,) + f(*h.at) for h in self.holes))
                variants.append((profs, holes))
        return (self.stock, tuple(sorted(self.size)), min(variants), tuple(self.bevels()), self.name)


@dataclass
class Stock:
    id: str
    kind: str  # "board" | "sheet"
    name: str
    thickness: float
    width: float
    length: float


@dataclass
class Screw:
    through: str
    into: str
    point: tuple   # точка входа на наружной пласти
    normal: tuple  # наружная нормаль этой пласти
    d: float
    length: int

    @property
    def spec(self):
        return f"{self.d:g}×{self.length}"

    @property
    def key(self):
        return (self.d, self.length)


@dataclass
class Contact:
    a: str
    b: str
    n: tuple        # нормаль от a к b
    pts: list       # площадка контакта
    tag_a: str
    tag_b: str

    @property
    def area(self):
        return G.poly_area(self.pts, self.n)


@dataclass
class Step:
    title: str
    add: list[str] = field(default_factory=list)
    focus: list[str] = field(default_factory=list)
    text: str = ""
    glue: bool = False
    view: str = "front-right"


@dataclass
class Project:
    title: str
    subtitle: str
    difficulty: str
    time: str
    kerf: float
    stock: dict[str, Stock]
    parts: list[Part]
    steps: list[Step]
    tools: list[str]
    tips: list[str]
    extra_materials: list[str]
    build_errors: list = field(default_factory=list)
    lang: str = "ru"
    units: str = "mm"
    disclaimer: str = ""
    load_bearing: bool = False

    def part(self, pid: str) -> Part:
        for p in self.parts:
            if p.id == pid:
                return p
        raise KeyError(pid)


# ---------- построение деталей ----------

def _box(size, thick_axis):
    planes = []
    for i in range(3):
        n = [0.0, 0.0, 0.0]
        n[i] = 1.0
        tag_p = "+t" if i == thick_axis else "edge"
        tag_m = "-t" if i == thick_axis else "edge"
        planes.append(G.Plane(tuple(n), size[i], tag_p))
        planes.append(G.Plane(tuple(-x for x in n), 0.0, tag_m))
    return G.Poly(planes)


def _rotation(spec):
    if not spec:
        return G.IDENT
    specs = spec if isinstance(spec, list) else [spec]
    R = G.IDENT
    for s in specs:
        deg = s.get("deg")
        if deg is None:
            deg = math.degrees(math.atan2(s["rise"], s["run"]))
        R = G.mat_mul(G.rotation(s["axis"], deg), R)
    return R


def _build_part(p: dict, errors: list) -> Part:
    size = tuple(map(float, p["size"]))
    part = Part(
        id=p["id"], name=p["name"], stock=p["stock"], size=size,
        holes=[Hole(h["d"], tuple(h["at"]), h.get("name", "Отверстие")) for h in p.get("holes", [])],
        removable=p.get("removable", False), fasten_to=p.get("fasten_to", []), note=p.get("note", ""),
    )
    local = _box(size, part.thick_axis)
    a, b = part.face_axes
    t = part.thick_axis
    for c in p.get("cuts", []):
        (u0, v0), (u1, v1) = c["from"], c["to"]
        keep2 = c.get("keep", [size[a] / 2, size[b] / 2])
        def P(u, v, w=0.0):
            q = [0.0, 0.0, 0.0]
            q[a], q[b], q[t] = u, v, w
            return tuple(q)
        try:
            pl = G.plane_through(P(u0, v0), P(u1, v1), P(u0, v0, 1.0), P(*keep2, size[t] / 2), tag="cut")
        except ValueError:
            errors.append(err("cut_degenerate", [part.id], part=part.id))
            continue
        local = local.with_plane(pl)

    part.R = _rotation(p.get("rotate"))
    part.origin = tuple(map(float, p.get("origin", (0, 0, 0))))

    for tr in p.get("trim", []):
        pts = [tuple(map(float, q)) for q in tr["through"]]
        world_center = part.to_world(local.centroid)
        keep = tuple(map(float, tr["keep"])) if "keep" in tr else world_center
        try:
            wpl = G.plane_through(pts[0], pts[1], pts[2], keep, tag="trim")
        except ValueError:
            errors.append(err("trim_degenerate", [part.id], part=part.id))
            continue
        # в локальные координаты: n_l = Rᵀn, d_l = d - n·o
        Rt = G.transpose(part.R)
        lpl = G.Plane(G.mat_vec(Rt, wpl.n), wpl.d - G.dot(wpl.n, part.origin), "trim")
        local = local.with_plane(lpl)

    part.local = local
    part.raw_snaps = p.get("snap", [])
    if isinstance(part.raw_snaps, dict):
        part.raw_snaps = [part.raw_snaps]
    if local.empty:
        errors.append(err("part_empty", [part.id], part=part.id))
    return part


def _apply_snaps(prj: Project):
    done: set[str] = set()
    for p in prj.parts:
        for sn in p.raw_snaps:
            u = G.unit(tuple(map(float, sn.get("dir", (0, 0, -1)))))
            best = None
            for tid in sn["to"]:
                try:
                    tgt = prj.part(tid)
                except KeyError:
                    prj.build_errors.append(err("snap_unknown_target", [p.id], part=p.id, target=tid))
                    continue
                if tgt.raw_snaps and tid not in done:
                    prj.build_errors.append(err("snap_target_not_ready", [p.id, tid], part=p.id, target=tid))
                iv = G.sweep(p.poly, tgt.poly, u)
                if iv and iv[1] > 1e-6:
                    best = iv[0] if best is None else min(best, iv[0])
            if best is None:
                prj.build_errors.append(err("snap_miss", [p.id], part=p.id, targets=sn["to"]))
                continue
            p.origin = G.add(p.origin, G.mul(u, best))
        done.add(p.id)


LENGTH_KEYS_PART = ("size", "origin")


def _scale(v, k):
    if isinstance(v, (int, float)):
        return v * k
    if isinstance(v, list):
        return [_scale(x, k) for x in v]
    return v


def _to_mm(raw: dict):
    """Модель в дюймах переводим в мм один раз при загрузке."""
    k = 25.4
    for st in raw.get("stock", []):
        for key in ("thickness", "width", "length"):
            if key in st:
                st[key] = st[key] * k
    if "kerf" in raw:
        raw["kerf"] = raw["kerf"] * k
    for p in raw.get("parts", []):
        for key in LENGTH_KEYS_PART:
            if key in p:
                p[key] = _scale(p[key], k)
        for h in p.get("holes", []):
            h["d"], h["at"] = h["d"] * k, _scale(h["at"], k)
        for c in p.get("cuts", []):
            for key in ("from", "to", "keep"):
                if key in c:
                    c[key] = _scale(c[key], k)
        for tr in p.get("trim", []):
            for key in ("through", "keep"):
                if key in tr:
                    tr[key] = _scale(tr[key], k)


def _check_raw(raw: dict) -> list:
    """Понятные ошибки вместо KeyError на кривом JSON."""
    out = []
    def need(obj, keys, where):
        for key in keys:
            if key not in obj:
                out.append(err("missing_field", where=where, field=key))
    need(raw, ("title", "stock", "parts", "steps"), "model")
    for i, st in enumerate(raw.get("stock", [])):
        need(st, ("id", "kind", "name", "thickness", "width", "length"), f"stock[{i}]")
        if st.get("kind") not in (None, "board", "sheet"):
            out.append(err("bad_value", where=f"stock[{i}]", field="kind", value=st.get("kind")))
    for i, p in enumerate(raw.get("parts", [])):
        where = p.get("id", f"parts[{i}]")
        need(p, ("id", "name", "stock", "size"), where)
        if "size" in p and (len(p["size"]) != 3 or min(p["size"]) <= 0):
            out.append(err("bad_value", [where], where=where, field="size", value=p["size"]))
        for j, h in enumerate(p.get("holes", [])):
            need(h, ("d", "at"), f"{where}.holes[{j}]")
        for j, c in enumerate(p.get("cuts", [])):
            need(c, ("from", "to"), f"{where}.cuts[{j}]")
        for j, tr in enumerate(p.get("trim", [])):
            need(tr, ("through",), f"{where}.trim[{j}]")
            if "through" in tr and len(tr["through"]) != 3:
                out.append(err("bad_value", [where], where=f"{where}.trim[{j}]", field="through",
                               value="нужно 3 точки / need 3 points"))
        sn = p.get("snap", [])
        for j, x in enumerate([sn] if isinstance(sn, dict) else sn):
            need(x, ("to",), f"{where}.snap[{j}]")
        rot = p.get("rotate")
        for j, x in enumerate([rot] if isinstance(rot, dict) else (rot or [])):
            need(x, ("axis",), f"{where}.rotate[{j}]")
            if x.get("axis") not in (None, "x", "y", "z"):
                out.append(err("bad_value", [where], where=f"{where}.rotate[{j}]", field="axis", value=x.get("axis")))
            if "deg" not in x and not ("rise" in x and "run" in x):
                out.append(err("missing_field", [where], where=f"{where}.rotate[{j}]", field="deg | rise+run"))
    for i, st in enumerate(raw.get("steps", [])):
        need(st, ("title",), f"steps[{i}]")
    return out


def load(path: str) -> Project:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        return Project(title="", subtitle="", difficulty="", time="", kerf=3, stock={}, parts=[], steps=[],
                       tools=[], tips=[], extra_materials=[],
                       build_errors=[err("bad_json", line=e.lineno, col=e.colno, msg=e.msg)])
    return load_dict(raw)


def load_dict(raw: dict) -> Project:
    raw = json.loads(json.dumps(raw))  # копия: дальше мутируем
    units = raw.get("units", "mm")
    lang = raw.get("lang", "ru")
    problems = _check_raw(raw)
    if problems:
        prj = Project(title=raw.get("title", ""), subtitle="", difficulty="", time="", kerf=3, stock={},
                      parts=[], steps=[], tools=[], tips=[], extra_materials=[], build_errors=problems,
                      lang=lang, units=units)
        return prj
    if units == "in":
        _to_mm(raw)
    errors: list = []
    stock = {s["id"]: Stock(s["id"], s["kind"], s["name"], float(s["thickness"]), float(s["width"]),
                            float(s["length"])) for s in raw["stock"]}
    parts = [_build_part(p, errors) for p in raw["parts"]]
    steps = [Step(s["title"], s.get("add", []), s.get("focus", []), s.get("text", ""), s.get("glue", False),
                  s.get("view", "front-right")) for s in raw["steps"]]
    prj = Project(
        title=raw["title"], subtitle=raw.get("subtitle", ""),
        difficulty=raw.get("difficulty", ""), time=raw.get("time", ""),
        kerf=raw.get("kerf", 3), stock=stock, parts=parts, steps=steps,
        tools=raw.get("tools", []), tips=raw.get("tips", []),
        extra_materials=raw.get("extra_materials", []), build_errors=errors,
        lang=lang, units=units, disclaimer=raw.get("disclaimer", ""),
        load_bearing=raw.get("load_bearing", False),
    )
    if not errors:
        _apply_snaps(prj)
    assign_letters(prj)
    return prj


def letter_for(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(ord("A") + r) + s
    return s


def assign_letters(prj: Project):
    groups: dict = {}
    for p in prj.parts:
        if p.local is None or p.local.empty:
            continue
        groups.setdefault(p.signature(), []).append(p)
    for i, (_, ps) in enumerate(groups.items()):
        for p in ps:
            p.letter = letter_for(i)


def part_groups(prj: Project) -> list[list[Part]]:
    groups: dict = {}
    for p in prj.parts:
        groups.setdefault(p.letter, []).append(p)
    return [groups[k] for k in sorted(groups, key=lambda L: (len(L), L))]


# ---------- контакты и крепёж ----------

def find_contact(a: Part, b: Part) -> Contact | None:
    best = None
    pa, pb = a.poly, b.poly
    for fa in pa.faces:
        for fb in pb.faces:
            pts = G.face_contact(fa, fb, CONTACT_TOL)
            if pts:
                c = Contact(a.id, b.id, fa.n, pts, fa.tag, fb.tag)
                if best is None or c.area > best.area:
                    best = c
    return best


def all_contacts(prj: Project) -> list[Contact]:
    out = []
    ps = prj.parts
    for i in range(len(ps)):
        for j in range(i + 1, len(ps)):
            c = find_contact(ps[i], ps[j])
            if c:
                out.append(c)
    return out


def _std_length(need: float) -> int:
    for L in SCREW_LENGTHS:
        if L >= need:
            return L
    return SCREW_LENGTHS[-1]


def screws_for(prj: Project, c: Contact, newer: str | None = None) -> list[Screw]:
    """Саморез идёт сквозь деталь, которая касается соседа своей пластью, в торец/пласть соседа."""
    a, b = prj.part(c.a), prj.part(c.b)
    if (a.fasten_to and b.id not in a.fasten_to) or (b.fasten_to and a.id not in b.fasten_to):
        return []
    cands = []
    if c.tag_a in ("+t", "-t"):
        cands.append(a)
    if c.tag_b in ("+t", "-t"):
        cands.append(b)
    if not cands:
        return []
    t = cands[0]
    if len(cands) == 2 and newer in (a.id, b.id):
        t = prj.part(newer)
    f = b if t is a else a
    n_t = c.n if t is a else G.mul(c.n, -1)  # от t к f

    centroid, e1, e2 = G.principal_axis(c.pts, n_t)
    proj1 = [G.dot(G.sub(p, centroid), e1) for p in c.pts]
    lo, hi = min(proj1), max(proj1)
    L = hi - lo
    if t.removable or f.removable:
        n = 2 if L >= 60 else 1
    else:
        n = 1 if L < 60 else max(2, round(L / 120) + 1)
    inset = min(25.0, L / 4)
    positions = [(lo + hi) / 2] if n == 1 else [lo + inset + k * (L - 2 * inset) / (n - 1) for k in range(n)]

    plane_d = G.dot(n_t, c.pts[0])
    depth = f.poly.extent(n_t)[1] - plane_d
    length = _std_length(t.thickness + min(max(depth - 5, 10), 30))
    dia = 3.5 if t.thickness <= 25 else 4.0
    res = []
    for s in positions:
        p = G.add(centroid, G.mul(e1, s))
        if not G.point_in_convex(c.pts, p, c.n):
            continue
        entry = G.sub(p, G.mul(n_t, t.thickness))
        res.append(Screw(t.id, f.id, entry, G.mul(n_t, -1), dia, length))
    return res


def plan_screws(prj: Project, issues: list | None = None) -> dict[int, list[Screw]]:
    placed: set[str] = set()
    per_step: dict[int, list[Screw]] = {}
    contacts = all_contacts(prj)
    for si, st in enumerate(prj.steps):
        new = set(st.add)
        cur = []
        for c in contacts:
            ids = {c.a, c.b}
            if ids & new and ids <= (placed | new):
                newer = next(iter(ids & new)) if len(ids & new) == 1 else None
                got = screws_for(prj, c, newer)
                if not got and issues is not None:
                    a, b = prj.part(c.a), prj.part(c.b)
                    if not (a.fasten_to or b.fasten_to):
                        issues.append(warn("joint_glue_only", [c.a, c.b], a=c.a, b=c.b))
                cur += got
        per_step[si] = cur
        placed |= new
    return per_step


# ---------- проверки ----------

def _hole_check(p: Part, out: list):
    prof = p.profile("-t")
    if len(prof) < 3:
        return
    for h in p.holes:
        r = h.d / 2
        u, v = h.at
        dmin = math.inf
        signs = []
        for i in range(len(prof)):
            (x0, y0), (x1, y1) = prof[i], prof[(i + 1) % len(prof)]
            ex, ey = x1 - x0, y1 - y0
            dmin = min(dmin, abs((u - x0) * ey - (v - y0) * ex) / math.hypot(ex, ey))
            signs.append(ex * (v - y0) - ey * (u - x0))
        inside = all(x >= 0 for x in signs) or all(x <= 0 for x in signs)
        if not inside or dmin < r:
            out.append(err("hole_outside", [p.id], part=p.id, d=Mm(h.d)))
        elif dmin - r < 10:
            out.append(warn("hole_near_edge", [p.id], part=p.id, d=Mm(h.d), m=Mm(10)))


def validate(prj: Project) -> list[Issue]:
    out: list[Issue] = list(prj.build_errors)
    if any(i.level == "error" for i in out):
        return out
    ids = [p.id for p in prj.parts]
    dups = sorted({x for x in ids if ids.count(x) > 1})
    if dups:
        out.append(err("dup_ids", dups, ids=dups))
        return out

    for p in prj.parts:
        st = prj.stock.get(p.stock)
        if not st:
            out.append(err("unknown_stock", [p.id], part=p.id, stock=p.stock))
            continue
        if abs(p.thickness - st.thickness) > 0.5:
            out.append(err("thickness_mismatch", [p.id], part=p.id, t=Mm(p.thickness), st=Mm(st.thickness)))
        w, l = sorted(p.face_dims)
        if st.kind == "board":
            if w > st.width + 0.5:
                out.append(err("too_wide", [p.id], part=p.id, w=Mm(w), sw=Mm(st.width)))
            if l > st.length + 0.5:
                out.append(err("too_long", [p.id], part=p.id, l=Mm(l), sl=Mm(st.length)))
        elif not ((w <= st.width + 0.5 and l <= st.length + 0.5) or (l <= st.width + 0.5 and w <= st.length + 0.5)):
            out.append(err("sheet_too_small", [p.id], part=p.id, w=Mm(w), l=Mm(l), sw=Mm(st.width), sl=Mm(st.length)))
        _hole_check(p, out)

    ps = prj.parts
    for i in range(len(ps)):
        for j in range(i + 1, len(ps)):
            sep = G.separation(ps[i].poly, ps[j].poly)
            if sep < -CONTACT_TOL:
                out.append(err("overlap", [ps[i].id, ps[j].id], a=ps[i].id, b=ps[j].id, depth=Mm(-sep)))
            elif CONTACT_TOL < sep < GAP_WARN:
                out.append(warn("gap", [ps[i].id, ps[j].id], a=ps[i].id, b=ps[j].id, gap=Mm(sep)))

    contacts = all_contacts(prj)
    adj = {p.id: set() for p in ps}
    for c in contacts:
        adj[c.a].add(c.b)
        adj[c.b].add(c.a)
    if ps:
        seen, stack = set(), [ps[0].id]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack += adj[n] - seen
        lost = [p.id for p in ps if p.id not in seen]
        if lost:
            out.append(err("disconnected", lost, parts=lost))

    added = [pid for s in prj.steps for pid in s.add]
    for pid in ids:
        if added.count(pid) == 0:
            out.append(err("part_not_installed", [pid], part=pid))
        elif added.count(pid) > 1:
            out.append(err("part_installed_twice", [pid], part=pid))
    for s in prj.steps:
        for pid in s.add + s.focus:
            if pid not in ids:
                out.append(err("step_unknown_part", [pid], step=s.title, part=pid))

    touching = {frozenset((c.a, c.b)) for c in contacts}
    for p in ps:
        for sn in p.raw_snaps:
            if not any(frozenset((p.id, t)) in touching for t in sn["to"]):
                out.append(warn("snap_edge_only", [p.id], part=p.id, targets=sn["to"]))

    if not any(i.level == "error" for i in out):
        per_step = plan_screws(prj, out)
        placed: set[str] = set()
        for si, s in enumerate(prj.steps):
            if s.add and placed and not per_step[si]:
                out.append(warn("step_no_fastener", s.add, step=s.title))
            placed |= set(s.add)
    return out


def errors_of(issues):
    return [i for i in issues if i.level == "error"]
