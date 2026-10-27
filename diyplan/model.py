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

SCREW_LENGTHS = [16, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100, 120]
CONTACT_TOL = 0.05   # мм: грани считаются касающимися
GAP_WARN = 10.0      # мм: меньший зазор — подозрительно похоже на ошибку


SAFETY_FLAGS = ("load_bearing", "children", "outdoor", "wall_mount")


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
    """Сквозной проём в пласти: круг (d), прямоугольник/паз/арка (w×h). at — центр."""
    d: float
    at: tuple[float, float]  # центр в осях пласти заготовки, от её минимального угла
    name: str = "Отверстие"
    shape: str = "circle"    # circle | rect | slot | arch
    w: float = 0.0
    h: float = 0.0

    @property
    def size_label_mm(self):
        return (self.d,) if self.shape == "circle" else (self.w, self.h)

    def outline(self, n=40):
        """Контур относительно центра (du, dv), против часовой."""
        if self.shape == "circle":
            r = self.d / 2
            return [(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n)) for k in range(n)]
        w, h = self.w / 2, self.h / 2
        if self.shape == "rect":
            return [(-w, -h), (w, -h), (w, h), (-w, h)]
        if self.shape == "slot":  # скруглённые торцы по короткой стороне
            if self.w >= self.h:
                r, c = h, w - h
                arc = lambda cx, a0: [(cx + r * math.cos(a0 + math.pi * k / 12), r * math.sin(a0 + math.pi * k / 12))
                                      for k in range(13)]
                return arc(c, -math.pi / 2) + arc(-c, math.pi / 2)
            r, c = w, h - w
            arc = lambda cy, a0: [(r * math.cos(a0 + math.pi * k / 12), cy + r * math.sin(a0 + math.pi * k / 12))
                                  for k in range(13)]
            return arc(-c, math.pi) + arc(c, 0)
        if self.shape == "arch":  # прямоугольник с полукруглым верхом, h — полная высота
            r = w
            base = -h
            top = h - r
            pts = [(-w, base), (w, base), (w, top)]
            pts += [(r * math.cos(math.pi * k / 16), top + r * math.sin(math.pi * k / 16)) for k in range(1, 16)]
            pts += [(-w, top)]
            return pts
        raise ValueError(self.shape)

    @property
    def radius(self):
        return max(math.hypot(u, v) for u, v in self.outline(24))


@dataclass
class Hardware:
    """Фурнитура на пласти: крючок, петля для подвеса, точка крепления к стене."""
    name: str
    at: tuple[float, float]
    side: str = "+t"


@dataclass
class Part:
    id: str
    name: str
    stock: str
    size: tuple[float, float, float]
    origin: tuple = (0.0, 0.0, 0.0)
    R: tuple = G.IDENT
    holes: list[Hole] = field(default_factory=list)
    hardware: list[Hardware] = field(default_factory=list)
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
    kind: str = "screw"   # screw | confirmat

    @property
    def spec(self):
        return f"{self.d:g}×{self.length}"

    @property
    def key(self):
        return (self.kind, self.d, self.length)


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
    safety: list = field(default_factory=list)   # load_bearing, children, outdoor, wall_mount
    fastener: str = "auto"                        # auto | screw | confirmat
    gaps_ok: list = field(default_factory=list)   # пары деталей, между которыми зазор задуман
    cover_view: str = "front-right"

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


def _repeat(item):
    """at + repeat {n, step:[du, dv]} → список центров."""
    at = list(map(float, item["at"]))
    rep = item.get("repeat")
    if not rep:
        return [at]
    du, dv = rep.get("step", [0, 0])
    return [[at[0] + k * du, at[1] + k * dv] for k in range(int(rep.get("n", 1)))]


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
        holes=[Hole(float(h.get("d", 0)), tuple(at), h.get("name", "Отверстие"), h.get("shape", "circle"),
                    float(h.get("w", 0)), float(h.get("h", 0)))
               for h in p.get("holes", []) for at in _repeat(h)],
        hardware=[Hardware(x["name"], tuple(at), x.get("side", "+t"))
                  for x in p.get("hardware", []) for at in _repeat(x)],
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
        for h in p.get("holes", []) + p.get("hardware", []):
            for key in ("d", "w", "h", "at"):
                if key in h:
                    h[key] = _scale(h[key], k)
            if "repeat" in h and "step" in h["repeat"]:
                h["repeat"]["step"] = _scale(h["repeat"]["step"], k)
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
            need(h, ("at",), f"{where}.holes[{j}]")
            shape = h.get("shape", "circle")
            if shape not in ("circle", "rect", "slot", "arch"):
                out.append(err("bad_value", [where], where=f"{where}.holes[{j}]", field="shape", value=shape))
            elif shape == "circle":
                need(h, ("d",), f"{where}.holes[{j}]")
            else:
                need(h, ("w", "h"), f"{where}.holes[{j}]")
        for j, x in enumerate(p.get("hardware", [])):
            need(x, ("name", "at"), f"{where}.hardware[{j}]")
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
    for flag in raw.get("safety", []):
        if flag not in SAFETY_FLAGS:
            out.append(err("bad_value", where="safety", field="safety", value=f"{flag} ({', '.join(SAFETY_FLAGS)})"))
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
        safety=list(raw.get("safety", [])),
        fastener=raw.get("fastener", "auto"), gaps_ok=raw.get("gaps_ok", []),
        cover_view=raw.get("cover_view", "front-right"),
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


# Правила крепежа (ориентиры для саморезов по дереву):
EDGE_MIN = 15.0        # мм от торца площадки до самореза
NARROW_WARN = 12.0     # кромка уже — саморез может расколоть
NARROW_SKIP = 8.0      # кромка уже — саморез не ставим
MIN_EMBED = 15.0       # минимальное заглубление во вторую деталь
CLEAR = 3.0            # зазор между телами саморезов
NUDGES = (0, 8, -8, 16, -16, 24, -24, 32, -32)


@dataclass
class Slot:
    """Площадка стыка, вдоль которой ставим ряд саморезов."""
    c: Contact
    t: Part            # сквозь неё
    f: Part            # в неё
    n_t: tuple         # от t к f
    centroid: tuple
    e1: tuple          # длинная ось площадки
    lo: float
    hi: float
    short: float       # ширина площадки поперёк ряда


def joint_slot(prj: Project, c: Contact, newer: str | None = None) -> Slot | None:
    a, b = prj.part(c.a), prj.part(c.b)
    if (a.fasten_to and b.id not in a.fasten_to) or (b.fasten_to and a.id not in b.fasten_to):
        return None
    cands = []
    if c.tag_a in ("+t", "-t"):
        cands.append(a)
    if c.tag_b in ("+t", "-t"):
        cands.append(b)
    if not cands:
        return None
    t = cands[0]
    if len(cands) == 2 and newer in (a.id, b.id):
        t = prj.part(newer)
    f = b if t is a else a
    n_t = c.n if t is a else G.mul(c.n, -1)
    centroid, e1, e2 = G.principal_axis(c.pts, n_t)
    p1 = [G.dot(G.sub(p, centroid), e1) for p in c.pts]
    p2 = [G.dot(G.sub(p, centroid), e2) for p in c.pts]
    return Slot(c, t, f, n_t, centroid, e1, min(p1), max(p1), max(p2) - min(p2))


def _diameter(t: Part) -> float:
    return 3.0 if t.thickness <= 12 else 3.5 if t.thickness <= 25 else 4.0 if t.thickness <= 32 else 5.0


def _long_dir(p: Part):
    a, b = p.face_axes
    ax = a if p.size[a] >= p.size[b] else b
    e = [0.0, 0.0, 0.0]
    e[ax] = 1.0
    return p.dir_to_world(tuple(e))


def is_seam(prj: Project, c: Contact) -> bool:
    """Доски бок о бок в одной плоскости (щит, стенка из досок, сиденье из реек):
    это шов по длинным кромкам, а не узел — его держит обвязка, саморез туда не нужен.
    Стык торец в торец (наращивание по длине) — не шов."""
    if c.tag_a in ("+t", "-t") or c.tag_b in ("+t", "-t"):
        return False
    a, b = prj.part(c.a), prj.part(c.b)
    ea = [0.0, 0.0, 0.0]; ea[a.thick_axis] = 1.0
    eb = [0.0, 0.0, 0.0]; eb[b.thick_axis] = 1.0
    na, nb = a.dir_to_world(tuple(ea)), b.dir_to_world(tuple(eb))
    if abs(G.dot(na, nb)) < 0.99 or abs(G.dot(na, c.n)) > 0.05:
        return False
    return abs(G.dot(_long_dir(a), c.n)) < 0.5 and abs(G.dot(_long_dir(b), c.n)) < 0.5


def fastener_for(prj: Project, slot: "Slot") -> str:
    """Конфирмат — в кромку ЛДСП/МДФ (там саморез держит плохо), если проект не просит иного."""
    from .structure import material_of
    mode = prj.fastener
    if mode in ("screw", "confirmat"):
        return mode
    into_edge = (slot.c.tag_b if slot.t.id == slot.c.a else slot.c.tag_a) not in ("+t", "-t")
    mat = material_of(prj.stock[slot.f.stock])
    if into_edge and mat in ("chipboard", "mdf") and slot.f.thickness >= 15:
        return "confirmat"
    return "screw"


def _screw_at(slot: Slot, s: float) -> tuple | None:
    """Точка ряда → (точка на площадке, доступная глубина в детали f)."""
    p = G.add(slot.centroid, G.mul(slot.e1, s))
    if not G.point_in_convex(slot.c.pts, p, slot.c.n):
        return None
    depth = G.ray_exit(slot.f.poly, p, slot.n_t)
    return p, depth


CONFIRMAT_LENGTHS = [50, 60, 70]


def _make_screw(slot: Slot, p, depth, kind="screw") -> Screw | None:
    """Длина ≈ 2,5 толщины пробиваемой детали (заглубление ~1,5 толщины), но так, чтобы не вылезти."""
    t = slot.t
    room = depth - 3.0
    if room < MIN_EMBED:
        return None
    if kind == "confirmat":
        fit = [L for L in CONFIRMAT_LENGTHS if MIN_EMBED <= L - t.thickness <= room]
        if not fit:
            return None
        good = [x for x in fit if x - t.thickness >= 32]
        L = min(good) if good else max(fit)
        entry = G.sub(p, G.mul(slot.n_t, t.thickness))
        return Screw(t.id, slot.f.id, entry, G.mul(slot.n_t, -1), 7.0, L, "confirmat")
    target = min(room, max(25.0, 1.5 * t.thickness))
    length = None
    for L in SCREW_LENGTHS:
        if MIN_EMBED <= L - t.thickness <= target:
            length = L
    if length is None:
        return None
    entry = G.sub(p, G.mul(slot.n_t, t.thickness))
    return Screw(t.id, slot.f.id, entry, G.mul(slot.n_t, -1), _diameter(t), length)


def _shaft(s: Screw):
    return s.point, G.sub(s.point, G.mul(s.normal, s.length))


def _hole_axes(prj: Project):
    """Оси отверстий в мире: (деталь, имя, начало, конец, радиус)."""
    out = []
    for p in prj.parts:
        e = [0.0, 0.0, 0.0]
        e[p.thick_axis] = p.size[p.thick_axis]
        a, b = p.face_axes
        for h in p.holes:
            q = [0.0, 0.0, 0.0]
            q[a], q[b] = h.at
            out.append((p.id, h.name, p.to_world(tuple(q)), p.to_world(tuple(G.add(tuple(q), tuple(e)))), h.d / 2))
    return out


def plan_screws(prj: Project, issues: list | None = None) -> dict[int, list[Screw]]:
    """Расставить саморезы по шагам: ряд по каждой площадке стыка, с отступами от краёв,
    без встреч с уже стоящими саморезами и отверстиями, без выхода насквозь."""
    def note(i):
        if issues is not None:
            issues.append(i)

    placed: set[str] = set()
    per_step: dict[int, list[Screw]] = {}
    contacts = all_contacts(prj)
    holes = _hole_axes(prj)
    accepted: list[Screw] = []
    for si, st in enumerate(prj.steps):
        new = set(st.add)
        cur: list[Screw] = []
        for c in contacts:
            ids = {c.a, c.b}
            if not (ids & new and ids <= (placed | new)):
                continue
            newer = next(iter(ids & new)) if len(ids & new) == 1 else None
            slot = joint_slot(prj, c, newer)
            if slot is None:
                a, b = prj.part(c.a), prj.part(c.b)
                if not (a.fasten_to or b.fasten_to or is_seam(prj, c)):
                    note(warn("joint_glue_only", [c.a, c.b], a=c.a, b=c.b))
                continue
            kind = fastener_for(prj, slot)
            if slot.short < NARROW_SKIP:
                note(warn("screw_short_joint", [c.a, c.b], a=c.a, b=c.b, w=Mm(slot.short)))
                continue
            if slot.short < NARROW_WARN:
                note(warn("screw_near_edge", [slot.f.id], a=c.a, b=c.b, part=slot.f.id, m=Mm(NARROW_WARN)))

            L = slot.hi - slot.lo
            inset = EDGE_MIN if L >= 2 * EDGE_MIN + 1 else L / 2
            usable = L - 2 * inset
            if slot.t.removable or slot.f.removable:
                n = 2 if usable >= 20 else 1
            else:
                n = 1 if usable < 20 else max(2, round(usable / 120) + 1)
            base = [(slot.lo + slot.hi) / 2] if n == 1 else \
                [slot.lo + inset + k * usable / (n - 1) for k in range(n)]

            got = 0
            failures = []
            for s0 in base:
                done = False
                reason = None
                for dz in NUDGES:
                    s = s0 + dz
                    if s < slot.lo + inset - 1e-6 or s > slot.hi - inset + 1e-6:
                        continue
                    at = _screw_at(slot, s)
                    if not at:
                        continue
                    scr = _make_screw(slot, *at, kind=kind)
                    if scr is None:
                        reason = reason or ("deep", at[1])
                        continue
                    a0, a1 = _shaft(scr)
                    clash = next((o for o in accepted + cur
                                  if G.seg_seg_distance(a0, a1, *_shaft(o)) < (scr.d + o.d) / 2 + CLEAR), None)
                    if clash:
                        reason = reason or ("clash", clash)
                        continue
                    hole = next((h for h in holes
                                 if G.seg_seg_distance(a0, a1, h[2], h[3]) < h[4] + scr.d / 2 + 2), None)
                    if hole:
                        reason = reason or ("hole", hole)
                        continue
                    cur.append(scr)
                    got += 1
                    done = True
                    break
                if not done and reason:
                    failures.append(reason)
            # молчим, если длинный стык потерял один из многих; шумим, если узел ослаб заметно
            if failures and (got == 0 or len(base) <= 2):
                why, obj = failures[0]
                if why == "deep":
                    note(warn("screw_too_long", [slot.f.id], a=c.a, b=c.b, part=slot.f.id, t=Mm(max(obj, 0))))
                elif why == "clash":
                    note(warn("screw_clash", [slot.f.id], a=c.a, b=c.b, part=slot.f.id, c=obj.through, d=obj.into))
                else:
                    note(warn("screw_in_hole", [obj[0]], a=c.a, b=c.b, hole=obj[1]))
        per_step[si] = cur
        accepted += cur
        placed |= new
    if issues is not None:  # одинаковые предупреждения — один раз
        seen, uniq = set(), []
        for i in issues:
            k = (i.level, i.code, i.params.get("a"), i.params.get("b"), str(i.params.get("hole", "")))
            if k not in seen:
                seen.add(k)
                uniq.append(i)
        issues[:] = uniq
    return per_step


# ---------- проверки ----------

def _hole_check(p: Part, out: list):
    prof = p.profile("-t")
    if len(prof) < 3:
        return
    area = sum(prof[i][0] * prof[(i + 1) % len(prof)][1] - prof[(i + 1) % len(prof)][0] * prof[i][1]
               for i in range(len(prof)))
    sgn = 1 if area > 0 else -1
    for h in p.holes:
        pts = [(h.at[0] + du, h.at[1] + dv) for du, dv in h.outline(32)]
        dmin = math.inf
        for (u, v) in pts:
            for i in range(len(prof)):
                (x0, y0), (x1, y1) = prof[i], prof[(i + 1) % len(prof)]
                ex, ey = x1 - x0, y1 - y0
                dmin = min(dmin, sgn * (ex * (v - y0) - ey * (u - x0)) / math.hypot(ex, ey))
        if dmin < 0:
            out.append(err("hole_outside", [p.id], part=p.id, name=h.name))
        elif dmin < 10:
            out.append(warn("hole_near_edge", [p.id], part=p.id, name=h.name, m=Mm(10)))
    for i, a in enumerate(p.holes):
        for b in p.holes[i + 1:]:
            if math.hypot(a.at[0] - b.at[0], a.at[1] - b.at[1]) < a.radius + b.radius + 3 and \
                    _outlines_close(a, b):
                out.append(warn("hole_overlap", [p.id], part=p.id, name=a.name, other=b.name))


def _outlines_close(a: Hole, b: Hole) -> bool:
    pa = [(a.at[0] + u, a.at[1] + v) for u, v in a.outline(32)]
    pb = [(b.at[0] + u, b.at[1] + v) for u, v in b.outline(32)]
    return min(math.hypot(x0 - x1, y0 - y1) for x0, y0 in pa for x1, y1 in pb) < 3


def _hole_blocked(prj: Project, contacts, out: list):
    """Сквозное отверстие, которое с другой стороны закрыла соседняя деталь (дренаж над ножкой)."""
    for c in contacts:
        for pid, tag in ((c.a, c.tag_a), (c.b, c.tag_b)):
            if tag not in ("+t", "-t"):
                continue
            p = prj.part(pid)
            other = c.b if pid == c.a else c.a
            a, b = p.face_axes
            for h in p.holes:
                q = [0.0, 0.0, 0.0]
                q[a], q[b] = h.at
                q[p.thick_axis] = p.size[p.thick_axis] if tag == "+t" else 0.0
                w = p.to_world(tuple(q))
                if G.point_in_convex(c.pts, w, c.n):
                    out.append(warn("hole_blocked", [pid, other], part=pid, name=h.name, other=other))


def validate(prj: Project) -> list[Issue]:
    out: list[Issue] = list(prj.build_errors)
    if any(i.level == "error" for i in out):
        return out
    ids = [p.id for p in prj.parts]
    gaps_ok = {frozenset(pair) for pair in prj.gaps_ok}
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
            elif CONTACT_TOL < sep < GAP_WARN and frozenset((ps[i].id, ps[j].id)) not in gaps_ok:
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

    _hole_blocked(prj, contacts, out)
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
