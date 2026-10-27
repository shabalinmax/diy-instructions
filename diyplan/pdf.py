"""Сборка PDF-инструкции: обложка → детали и раскрой → шаги → важное.

Вёрстка потоковая: всё, что не влезает, переносится на следующую страницу
(список покупок, сетка деталей, раскрой, шаги с длинным текстом, советы).
"""
from __future__ import annotations

import math
import os
from collections import Counter

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from . import cutlist, iso
from .i18n import Fmt
from .model import Project, part_groups, plan_screws

W, H = A4
M = 36
TOP = H - 50          # верхняя граница контента
BOTTOM = 44           # нижняя граница (над футером)
INK = HexColor("#1E1E1E")
MUTED = HexColor("#6B6B6B")
LINE = HexColor("#D8D8D8")
ACCENT = HexColor("#D9381E")
WOOD = HexColor("#F4E6CB")
YEL = HexColor("#FFC93C")

FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
FONT_CANDIDATES = [
    (os.path.join(FONT_DIR, "DejaVuSans.ttf"), os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
]
_fonts_ready = False


def register_fonts():
    """Шрифт с кириллицей лежит в пакете; DIYPLAN_FONT / DIYPLAN_FONT_BOLD — чтобы подменить."""
    global _fonts_ready
    if _fonts_ready:
        return
    env = os.environ.get("DIYPLAN_FONT"), os.environ.get("DIYPLAN_FONT_BOLD")
    for reg, bold in ([env] if env[0] else []) + FONT_CANDIDATES:
        if reg and os.path.exists(reg) and os.path.exists(bold or reg):
            pdfmetrics.registerFont(TTFont("DejaVu", reg))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold or reg))
            _fonts_ready = True
            return
    raise SystemExit("Font with Cyrillic glyphs not found. Set DIYPLAN_FONT / DIYPLAN_FONT_BOLD.")


# ---------- примитивы ----------

def text(c, x, y, s, size=10, bold=False, color=INK, align="left"):
    c.setFont("DejaVu-Bold" if bold else "DejaVu", size)
    c.setFillColor(color)
    {"left": c.drawString, "center": c.drawCentredString, "right": c.drawRightString}[align](x, y, s)


def wrap(s, width, size=10, bold=False):
    font = "DejaVu-Bold" if bold else "DejaVu"
    lines = []
    for chunk in (s or "").split("\n"):
        lines += simpleSplit(chunk, font, size, width) or [""]
    return lines


def para(c, x, y, s, width, size=10, leading=None, color=INK, bold=False, draw=True):
    """Абзац; возвращает y под ним. draw=False — только измерить."""
    leading = leading or size * 1.35
    for line in wrap(s, width, size, bold):
        if draw:
            text(c, x, y, line, size, bold, color)
        y -= leading
    return y


def fit_text(c, s, width, size, bold=False):
    """Обрезать строку с многоточием, если не влезает."""
    font = "DejaVu-Bold" if bold else "DejaVu"
    if c.stringWidth(s, font, size) <= width:
        return s
    while s and c.stringWidth(s + "…", font, size) > width:
        s = s[:-1]
    return s + "…"


def screw_icon(c, x, y, h=26):
    c.setStrokeColor(INK)
    c.setFillColor(HexColor("#BFC3C7"))
    c.setLineWidth(0.8)
    c.ellipse(x - 6, y + h - 4, x + 6, y + h, fill=1, stroke=1)
    p = c.beginPath()
    p.moveTo(x - 2.2, y + h - 4); p.lineTo(x + 2.2, y + h - 4); p.lineTo(x + 1.6, y + 6); p.lineTo(x, y); p.lineTo(x - 1.6, y + 6); p.close()
    c.drawPath(p, fill=1, stroke=1)
    for k in range(5):
        yy = y + 7 + k * (h - 13) / 5
        c.line(x - 2.4, yy, x + 2.4, yy + 2.5)


def glue_icon(c, x, y):
    c.setStrokeColor(INK)
    c.setLineWidth(0.8)
    c.setFillColor(HexColor("#FFFFFF"))
    c.roundRect(x - 7, y, 14, 20, 3, fill=1, stroke=1)
    c.setFillColor(HexColor("#2E7DD7"))
    c.rect(x - 7, y + 6, 14, 7, fill=1, stroke=0)
    c.setFillColor(HexColor("#FFFFFF"))
    p = c.beginPath()
    p.moveTo(x - 3, y + 20); p.lineTo(x + 3, y + 20); p.lineTo(x, y + 28); p.close()
    c.drawPath(p, fill=1, stroke=1)


def chip(c, x, y, w, label, value):
    c.setFillColor(HexColor("#F3F1EC"))
    c.roundRect(x, y, w, 40, 6, fill=1, stroke=0)
    text(c, x + 10, y + 25, label, 8, color=MUTED)
    text(c, x + 10, y + 9, fit_text(c, value, w - 16, 12, True), 12, bold=True)


def dim_h(c, x0, x1, y, label, size=7.5):
    c.setStrokeColor(MUTED); c.setLineWidth(0.5)
    c.line(x0, y, x1, y)
    for x in (x0, x1):
        c.line(x, y - 3, x, y + 3)
    w = c.stringWidth(label, "DejaVu", size) + 4
    c.setFillColor(HexColor("#FFFFFF")); c.rect((x0 + x1) / 2 - w / 2, y - 4, w, 8, fill=1, stroke=0)
    text(c, (x0 + x1) / 2, y - 2.6, label, size, color=INK, align="center")


def dim_v(c, x, y0, y1, label, size=7.5):
    c.saveState()
    c.translate(x, (y0 + y1) / 2)
    c.rotate(90)
    dim_h(c, -(y1 - y0) / 2, (y1 - y0) / 2, 0, label, size)
    c.restoreState()


# ---------- документ с курсором ----------

class Doc:
    def __init__(self, prj: Project, out: str, fmt: Fmt):
        self.prj, self.fmt = prj, fmt
        self.c = canvas.Canvas(out, pagesize=A4)
        self.c.setTitle(prj.title)
        self.c.setAuthor("diyplan")
        self.page = 1
        self.y = TOP

    def footer(self):
        c = self.c
        c.setStrokeColor(LINE)
        c.setLineWidth(0.6)
        c.line(M, 28, W - M, 28)
        text(c, M, 16, fit_text(c, self.prj.title, W - 2 * M - 40, 8), 8, color=MUTED)
        text(c, W - M, 16, str(self.page), 8, color=MUTED, align="right")

    def new_page(self):
        self.footer()
        self.c.showPage()
        self.page += 1
        self.y = TOP

    def need(self, h, title=None):
        """Хватит ли места на h пунктов; если нет — новая страница (с повтором заголовка)."""
        if self.y - h < BOTTOM:
            self.new_page()
            if title:
                self.heading(f"{title} {self.fmt.t('continued')}", size=14)
                self.y -= 10
            return True
        return False

    def heading(self, s, size=20, sub=None):
        text(self.c, M, self.y - size, s, size, bold=True)
        self.y -= size + 8
        if sub:
            self.y = para(self.c, M, self.y - 4, sub, W - 2 * M, 9, color=MUTED) - 4

    def save(self):
        self.footer()
        self.c.save()


# ---------- обложка ----------

def cover(d: Doc, total_screws: Counter, uses):
    c, prj, f = d.c, d.prj, d.fmt
    c.setFillColor(YEL)
    c.rect(0, H - 150, W, 150, fill=1, stroke=0)
    if c.stringWidth(prj.title, "DejaVu-Bold", 34) < W - 2 * M:
        text(c, M, H - 70, prj.title, 34, bold=True)
        sub_y = H - 100
    else:
        lines = wrap(prj.title, W - 2 * M, 22, True)[:2]
        if len(wrap(prj.title, W - 2 * M, 22, True)) > 2:
            lines[1] = fit_text(c, lines[1] + " …", W - 2 * M, 22, True)
        for i, line in enumerate(lines):
            text(c, M, H - 52 - i * 26, line, 22, bold=True)
        sub_y = H - 52 - len(lines) * 26 - 6
    sub = wrap(prj.subtitle, W - 2 * M, 12)[:max(1, int((sub_y - (H - 145)) / 16))]
    para(c, M, sub_y, "\n".join(sub), W - 2 * M, 12)
    iso.draw_scene(c, prj, (M, 330, W - 2 * M, H - 150 - 345), {p.id: "old" for p in prj.parts},
                   arrows=False, labels=False, extra=30)
    cw = (W - 2 * M - 3 * 10) / 4
    chips = [(f.t("difficulty"), prj.difficulty or "—"), (f.t("time"), prj.time or "—"),
             (f.t("n_parts"), str(len(prj.parts))), (f.t("n_screws"), str(sum(total_screws.values())))]
    for i, (lab, val) in enumerate(chips):
        chip(c, M + i * (cw + 10), 270, cw, lab, val)

    col = (W - 2 * M - 20) / 2
    buy = [f.t("stock_line", name=name, n=n) for name, n in cutlist.shopping(prj, uses, f)]
    buy += [f.t("confirmat_line" if k[0] == "confirmat" else "screws_line", spec=f.screw(*k), n=n)
            for k, n in sorted(total_screws.items())]
    buy += list(prj.extra_materials)
    two_columns(d, 240, (f.t("buy"), buy), (f.t("tools"), list(prj.tools)), col)
    if d.page == 1 and d.y > BOTTOM + 30:
        para(c, M, BOTTOM + 14, f.t("disclaimer"), W - 2 * M, 6.5, color=MUTED)


def two_columns(d: Doc, y0, left, right, col):
    """Два списка рядом; переполнение уходит на следующие страницы."""
    c = d.c
    cols = [(M, left), (M + col + 20, right)]
    for x, (title, items) in cols:
        text(c, x, y0, title, 12, bold=True)
    ys = [y0 - 18, y0 - 18]
    queues = [list(left[1]), list(right[1])]
    while any(queues):
        for k, (x, _) in enumerate(cols):
            while queues[k]:
                item = queues[k][0]
                h = len(wrap("• " + item, col, 9)) * 9 * 1.35
                if ys[k] - h < BOTTOM:
                    break
                ys[k] = para(c, x, ys[k], "• " + item, col, 9)
                queues[k].pop(0)
        if any(queues):
            d.new_page()
            for k, (x, (title, _)) in enumerate(cols):
                if queues[k]:
                    text(c, x, TOP - 12, f"{title} {d.fmt.t('continued')}", 12, bold=True)
            ys = [TOP - 30, TOP - 30]
    d.y = min(ys)


# ---------- детали ----------

def part_cell(c, f: Fmt, g, cx, cy, cell_w, cell_h):
    p = g[0]
    fa, fb = p.face_dims
    draw_w, draw_h = cell_w - 60, cell_h - 100
    scale = min(draw_w / fa, draw_h / fb, 0.6)
    rw, rh = fa * scale, fb * scale
    rx = cx + 28 + (cell_w - 40 - rw) / 2
    ry = cy + 26 + (cell_h - 100 - rh) / 2
    prof, prof2 = p.profile("-t"), p.profile("+t")
    u0 = min(q[0] for q in prof + prof2)
    v0 = min(q[1] for q in prof + prof2)
    P = lambda q: (rx + (q[0] - u0) * scale, ry + (q[1] - v0) * scale)
    bev = p.bevels()
    if len(prof) != 4 or bev:
        c.setStrokeColor(MUTED); c.setLineWidth(0.4); c.setDash(2, 2)
        c.rect(rx, ry, rw, rh, fill=0, stroke=1)
        c.setDash()
    path = c.beginPath()
    path.moveTo(*P(prof[0]))
    for q in prof[1:]:
        path.lineTo(*P(q))
    path.close()
    c.setFillColor(WOOD); c.setStrokeColor(INK); c.setLineWidth(0.9)
    c.drawPath(path, fill=1, stroke=1)
    if bev:
        path = c.beginPath()
        path.moveTo(*P(prof2[0]))
        for q in prof2[1:]:
            path.lineTo(*P(q))
        path.close()
        c.setStrokeColor(ACCENT); c.setLineWidth(0.6); c.setDash(3, 2)
        c.drawPath(path, fill=0, stroke=1)
        c.setDash()
    corners = {(0, 0), (round(fa), 0), (0, round(fb)), (round(fa), round(fb))}
    pcx = sum(P(q)[0] for q in prof) / len(prof)
    pcy = sum(P(q)[1] for q in prof) / len(prof)
    for q in prof:
        uu, vv = q[0] - u0, q[1] - v0
        if (round(uu), round(vv)) in corners:
            continue
        x, y = P(q)
        dx, dy = x - pcx, y - pcy
        L = math.hypot(dx, dy) or 1
        tx, ty = x + dx / L * 6, y + dy / L * 6
        align = "left" if dx > 3 else "right" if dx < -3 else "center"
        c.setFillColor(ACCENT); c.circle(x, y, 1.6, fill=1, stroke=0)
        text(c, tx, ty - (2 if abs(dy) < abs(dx) else 0) + (0 if dy >= 0 else -6), f"{f.num(uu)} / {f.num(vv)}",
             6.5, bold=True, color=ACCENT, align=align)
    for h in p.holes:
        hx, hy = P((h.at[0], h.at[1]))
        c.setFillColor(HexColor("#3B2A1C"))
        c.circle(hx, hy, h.d / 2 * scale, fill=1, stroke=0)
        c.setStrokeColor(ACCENT); c.setLineWidth(0.4); c.setDash(2, 2)
        c.line(rx, hy, hx, hy)
        c.line(hx, ry, hx, hy)
        c.setDash()
        text(c, hx + h.d / 2 * scale + 3, hy + 2, f"⌀{f.num(h.d)}", 7.5, bold=True, color=ACCENT)
        text(c, hx + h.d / 2 * scale + 3, hy - 8, f"{f.num(h.at[0] - u0)} / {f.num(h.at[1] - v0)}", 6.5, color=ACCENT)
    dim_h(c, rx, rx + rw, ry - 10, f.num(fa))
    dim_v(c, rx - 10, ry, ry + rh, f.num(fb))
    if bev:
        text(c, cx + 30, cy + cell_h - 49,
             f.t("bevel_note", angles=", ".join(f.angle(a) for a in sorted(set(bev)))), 6.5, color=ACCENT)
    iso.label(c, cx + 14, cy + cell_h - 22, p.letter, r=10, size=11 if len(p.letter) == 1 else 8)
    text(c, cx + 30, cy + cell_h - 26, fit_text(c, f"{p.name}  ×{len(g)}", cell_w - 34, 10, True), 10, bold=True)
    text(c, cx + 30, cy + cell_h - 38, f.t("thickness", t=f.len(p.thickness)), 7.5, color=MUTED)


def parts_section(d: Doc):
    c, f = d.c, d.fmt
    d.heading(f.t("parts_title"), sub=f.t("parts_sub", units=f.unit_label))
    groups = part_groups(d.prj)
    cols, cell_h = 3, 195
    cell_w = (W - 2 * M) / cols
    for i in range(0, len(groups), cols):
        d.need(cell_h, f.t("parts_title"))
        for k, g in enumerate(groups[i:i + cols]):
            part_cell(c, f, g, M + k * cell_w, d.y - cell_h, cell_w, cell_h)
        d.y -= cell_h


def cut_section(d: Doc, uses):
    c, f, prj = d.c, d.fmt, d.prj
    d.y -= 14
    d.need(120)
    d.heading(f.t("cut_title"), sub=f.t("cut_sub", kerf=f.len(prj.kerf)))
    bar_w = W - 2 * M
    for u in uses:
        st = prj.stock[u.stock_id]
        sc = bar_w / st.length
        if st.kind == "sheet":
            sc = min(sc, 260 / st.width)
        bh = st.width * sc
        d.need(bh + 30, f.t("cut_title"))
        d.y -= 14
        text(c, M, d.y, fit_text(c, f"{st.name} {f.dims(st.thickness, st.width, st.length)}  —  "
                                    f"{f.t('stock_no', n=u.index)}", bar_w, 8.5, True), 8.5, bold=True)
        y = d.y - 6 - bh
        c.setFillColor(HexColor("#EDEDED")); c.setStrokeColor(MUTED); c.setLineWidth(0.6)
        c.rect(M, y, st.length * sc, st.width * sc, fill=1, stroke=1)
        for pl in u.placed:
            x0 = M + pl.x * sc
            y0 = y + (st.width - pl.y - pl.h) * sc
            pw, ph = pl.w * sc, pl.h * sc
            c.setFillColor(WOOD); c.setStrokeColor(INK); c.setLineWidth(0.7)
            c.rect(x0, y0, pw, ph, fill=1, stroke=1)
            mid = x0 + pw / 2
            dims = f"{f.num(pl.w)}×{f.num(pl.h)}"
            if ph > 22 and pw > 18:
                iso.label(c, mid, y0 + ph / 2 + 4, pl.piece.letter, r=7, size=8 if len(pl.piece.letter) == 1 else 6)
                if c.stringWidth(dims, "DejaVu", 6.5) < pw - 2:
                    text(c, mid, y0 + 3, dims, 6.5, align="center")
            elif pw > 14:
                label = f"{pl.piece.letter} {dims}"
                if c.stringWidth(label, "DejaVu-Bold", 6.5) > pw - 2:
                    label = pl.piece.letter
                text(c, mid, y0 + ph / 2 - 3, label, 6.5, bold=True, align="center")
        d.y = y - 8


# ---------- шаги ----------

def _step_side(c, d: Doc, si, rx, ry, colw, cur, shown, draw=True):
    """Правая колонка шага. Возвращает y под последней строкой."""
    prj, f = d.prj, d.fmt
    st = prj.steps[si]
    if st.add:
        letters = Counter(prj.part(pid).letter for pid in st.add)
        for L, n in sorted(letters.items(), key=lambda kv: (len(kv[0]), kv[0])):
            if draw:
                iso.label(c, rx + 10, ry, L, r=10, size=11 if len(L) == 1 else 8)
                name = next(p.name for p in prj.parts if p.letter == L)
                text(c, rx + 26, ry - 4, fit_text(c, f"×{n}  {name}", colw - 28, 10, True), 10, bold=True)
            ry -= 26
    for k, n in sorted(Counter(s.key for s in cur).items()):
        if draw:
            screw_icon(c, rx + 10, ry - 14)
            text(c, rx + 26, ry - 4, f"×{n}", 12, bold=True)
            text(c, rx + 26, ry - 16, f.t("confirmat_spec" if k[0] == "confirmat" else "screw_spec",
                                         spec=f.screw(*k)), 8, color=MUTED)
        ry -= 36
    if st.glue:
        if draw:
            glue_icon(c, rx + 10, ry - 22)
            text(c, rx + 26, ry - 6, f.t("glue"), 10, bold=True)
            text(c, rx + 26, ry - 18, f.t("glue_sub"), 8, color=MUTED)
        ry -= 38
    if cur:
        hidden = len(cur) - shown
        note = f.t("screw_marks") + (f.t("screw_marks_hidden", n=hidden) if hidden and shown else "")
        if not shown:
            note = f.t("screws_hidden_all")
        ry = para(c, rx, ry - 4, note, colw, 7.5, color=ACCENT, draw=draw) - 6
    return para(c, rx, ry - 6, st.text, colw, 9.2, draw=draw)


def step_block(d: Doc, si: int, box, screws_by_step, placed_before: list[str]):
    c, prj = d.c, d.prj
    st = prj.steps[si]
    x, y, w, h = box
    iso.label(c, x + 16, y + h - 18, str(si + 1), r=16, size=16 if si < 9 else 13)
    text(c, x + 40, y + h - 23, fit_text(c, st.title, w - 50, 14, True), 14, bold=True)

    cur = screws_by_step.get(si, [])
    old = [s for k, v in screws_by_step.items() if k < si for s in v]
    img_box = (x, y + 26, w * 0.62, h - 56)
    if st.add:
        styles = {pid: "old" for pid in placed_before}
        styles.update({pid: "new" for pid in st.add})
        ref = [prj.part(pid) for pid in styles]
        shown = iso.draw_scene(c, prj, img_box, styles, cur, old, ref_parts=ref, extra=120, view=st.view)
    else:
        styles = {pid: "focus" for pid in st.focus}
        shown = iso.draw_scene(c, prj, img_box, styles, ref_parts=[prj.part(p) for p in st.focus],
                               arrows=False, extra=30, view=st.view) if st.focus else 0
    _step_side(c, d, si, x + w * 0.64, y + h - 60, w * 0.36, cur, shown)
    c.setStrokeColor(LINE); c.setLineWidth(0.6)
    c.line(x, y + 20, x + w, y + 20)


def steps_section(d: Doc, screws_by_step):
    c, prj = d.c, d.prj
    d.new_page()
    full = TOP - BOTTOM
    half = full / 2
    placed: list[str] = []
    slot = 0
    for si, st in enumerate(prj.steps):
        cur = screws_by_step.get(si, [])
        # сколько места просит правая колонка
        need = TOP - _step_side(c, d, si, 0, TOP - 60, (W - 2 * M) * 0.36, cur, len(cur), draw=False) + 30
        tall = need > half
        if tall and slot == 1:
            d.new_page(); slot = 0
        h = full if tall else half
        box = (M, TOP - slot * half - h, W - 2 * M, h)
        step_block(d, si, box, screws_by_step, list(placed))
        placed += [p for p in st.add if p not in placed]
        slot += 2 if tall else 1
        if slot >= 2 and si < len(prj.steps) - 1:
            d.new_page(); slot = 0
    d.y = TOP - slot * half


def _bullets(d: Doc, title, items, mark="!", fill="#D9381E"):
    c = d.c
    for t in items:
        h = len(wrap(t, W - 2 * M - 30, 10.5)) * 10.5 * 1.35 + 10
        d.need(h, title)
        iso.label(c, M + 10, d.y + 3, mark, r=10, fill=fill, size=11)
        d.y = para(c, M + 30, d.y, t, W - 2 * M - 30, 10.5) - 10


def loads_block(d: Doc):
    from .model import structure_report
    from .structure import DEFAULT_SHELF_KG_PER_M
    c, f, prj = d.c, d.fmt, d.prj
    sags, stab = structure_report(prj)
    if not sags and not (stab and "load_bearing" in prj.safety):
        return
    d.need(60)
    d.y -= 6
    text(c, M, d.y - 12, f.t("loads_title"), 13, bold=True)
    d.y -= 26
    lines = []
    for x in sags:
        p = prj.part(x.part)
        lines.append(f.t("load_line", name=p.name, letter=p.letter, kg=round(x.load_kg),
                         how=f.t("load_point" if x.point else "load_uniform"), sag=f.len(x.sag), span=f.len(x.span)))
    lines = list(dict.fromkeys(lines))  # одинаковые детали — одной строкой
    if any(prj.part(x.part).load_kg is None for x in sags):
        lines.append(f.t("load_default_note", kgm=round(DEFAULT_SHELF_KG_PER_M)))
    if stab and stab.margin >= 0:
        lines.append(f.t("stability_line", deg=round(stab.tip_deg)))
    for line in lines:
        h = len(wrap("• " + line, W - 2 * M, 9.5)) * 9.5 * 1.35
        d.need(h, f.t("loads_title"))
        d.y = para(c, M, d.y, "• " + line, W - 2 * M, 9.5)
    d.y -= 6


def tips_section(d: Doc):
    """«Важно» из модели + блок безопасности (общий и по флагам safety) + дисклеймер."""
    c, f, prj = d.c, d.fmt, d.prj
    d.new_page()
    if prj.tips:
        d.heading(f.t("tips_title"))
        d.y -= 10
        _bullets(d, f.t("tips_title"), prj.tips)
        d.y -= 16
    d.need(80)
    d.heading(f.t("safety_title"))
    d.y -= 10
    items = [f.t("safety_" + flag) for flag in prj.safety] + [f.t("safety_general")]
    _bullets(d, f.t("safety_title"), items, mark="▲", fill="#1E1E1E")
    loads_block(d)
    disc = (prj.disclaimer + "\n\n" if prj.disclaimer else "") + f.t("disclaimer")
    h = len(wrap(disc, W - 2 * M - 20, 8.5)) * 8.5 * 1.4 + 20
    d.need(h + 10)
    d.y -= 8
    c.setFillColor(HexColor("#F3F1EC"))
    c.roundRect(M, d.y - h + 8, W - 2 * M, h, 6, fill=1, stroke=0)
    d.y = para(c, M + 10, d.y - 6, disc, W - 2 * M - 20, 8.5, leading=8.5 * 1.4, color=MUTED) - 10


def build(prj: Project, out: str):
    register_fonts()
    fmt = Fmt(prj.lang, prj.units)
    d = Doc(prj, out, fmt)
    screws_by_step = plan_screws(prj)
    total = Counter(s.key for v in screws_by_step.values() for s in v)
    uses = cutlist.plan(prj)

    cover(d, total, uses)
    d.new_page()
    parts_section(d)
    cut_section(d, uses)
    steps_section(d, screws_by_step)
    tips_section(d)
    d.save()
