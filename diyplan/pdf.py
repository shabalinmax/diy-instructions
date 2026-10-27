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
                   arrows=False, labels=False, extra=30, view=prj.cover_view)
    cw = (W - 2 * M - 3 * 10) / 4
    money = cutlist.cost(uses)
    chips = [(f.t("difficulty"), prj.difficulty or "—"), (f.t("time"), prj.time or "—"),
             (f.t("budget"), "≈ " + fmt_money(money, prj.currency)) if money is not None
             else (f.t("n_parts"), str(len(prj.parts))),
             (f.t("n_screws"), str(sum(total_screws.values())))]
    for i, (lab, val) in enumerate(chips):
        chip(c, M + i * (cw + 10), 270, cw, lab, val)

    col = (W - 2 * M - 20) / 2
    buy = [f.t("stock_line", name=name, n=n) for name, n in cutlist.shopping(prj, uses, f)]
    buy += [f.t("confirmat_line" if k[0] == "confirmat" else "screws_line", spec=f.screw(*k), n=n)
            for k, n in sorted(total_screws.items())]
    hw = Counter(m.name for p in prj.parts for m in p.hardware)
    buy += [f.t("stock_line", name=name, n=n) for name, n in hw.items()]
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

def _hole_label(f: Fmt, h) -> str:
    if h.shape == "circle":
        return f"⌀{f.num(h.d)}"
    return f"{f.num(h.w)}×{f.num(h.h)}"


def draw_part_2d(c, f: Fmt, p, x, y, w, h, max_scale=0.6):
    """Чертёж пласти детали в прямоугольнике (x, y, w, h): контур, габариты, точки резов,
    проёмы и фурнитура. Координаты — от левого нижнего угла габарита детали.
    Если проёмов больше одного — их координаты уходят в таблицу под чертежом."""
    fa, fb = p.face_dims
    prof, prof2 = p.profile("-t"), p.profile("+t")
    u0 = min(q[0] for q in prof + prof2)
    v0 = min(q[1] for q in prof + prof2)
    holes_tab = len(p.holes) > 1 or p.hardware
    groups = []
    if holes_tab:
        for hh in p.holes:
            key = (hh.name, _hole_label(f, hh))
            if not groups or groups[-1][0] != key:
                groups.append((key, []))
            groups[-1][1].append(hh)
        hw = {}
        for m in p.hardware:
            hw.setdefault(m.name, []).append(m)
        groups += [((name, "●"), ms) for name, ms in hw.items()]
    tab_lines = []
    for (name, lab), items in groups:
        coords = "  ".join(f"{f.num(i.at[0] - u0)}/{f.num(i.at[1] - v0)}" for i in items)
        tab_lines += wrap(f"{lab} {name} ×{len(items)}: {coords}", w - 12, 6.5)
    if tab_lines:
        tab_lines = tab_lines[:6]
    tab_h = 9 * len(tab_lines) + (4 if tab_lines else 0)
    draw_w, draw_h = w - 40, h - 34 - tab_h
    scale = min(draw_w / fa, draw_h / fb, max_scale)
    rw, rh = fa * scale, fb * scale
    rx = x + 26 + (draw_w - rw) / 2
    ry = y + 22 + tab_h + (draw_h - rh) / 2
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
    placed_labels = []
    for q in prof:
        uu, vv = q[0] - u0, q[1] - v0
        if (round(uu), round(vv)) in corners:
            continue
        px, py = P(q)
        dx, dy = px - pcx, py - pcy
        L = math.hypot(dx, dy) or 1
        tx, ty = px + dx / L * 6, py + dy / L * 6 + (0 if dy >= 0 else -6)
        lab = f"{f.num(uu)} / {f.num(vv)}"
        lw = c.stringWidth(lab, "DejaVu-Bold", 6.5)
        align = "left" if dx > 3 else "right" if dx < -3 else "center"
        x0 = tx if align == "left" else tx - lw if align == "right" else tx - lw / 2
        x0 = min(max(x0, x + 2), x + w - lw - 2)            # не вылезать из ячейки
        while any(abs(ty - yy) < 8 and x0 < xx + ww and xx < x0 + lw for xx, yy, ww in placed_labels):
            ty -= 8                                         # не наезжать на соседнюю подпись
        placed_labels.append((x0, ty, lw))
        c.setFillColor(ACCENT); c.circle(px, py, 1.6, fill=1, stroke=0)
        text(c, x0, ty, lab, 6.5, bold=True, color=ACCENT)
    for hh in p.holes:
        pts = [P((hh.at[0] + du, hh.at[1] + dv)) for du, dv in hh.outline(32)]
        path = c.beginPath()
        path.moveTo(*pts[0])
        for q in pts[1:]:
            path.lineTo(*q)
        path.close()
        c.setFillColor(HexColor("#3B2A1C")); c.drawPath(path, fill=1, stroke=0)
        if not holes_tab:
            hx, hy = P(hh.at)
            c.setStrokeColor(ACCENT); c.setLineWidth(0.4); c.setDash(2, 2)
            c.line(rx, hy, hx, hy)
            c.line(hx, ry, hx, hy)
            c.setDash()
            rr = hh.radius * scale
            text(c, hx + rr + 3, hy + 2, _hole_label(f, hh), 7.5, bold=True, color=ACCENT)
            text(c, hx + rr + 3, hy - 8, f.t("center_at", u=f.num(hh.at[0] - u0), v=f.num(hh.at[1] - v0)),
                 6.5, color=ACCENT)
    for m in p.hardware:
        hx, hy = P(m.at)
        c.setFillColor(INK); c.circle(hx, hy, 2.6, fill=1, stroke=0)
        c.setFillColor(YEL); c.circle(hx, hy, 1.0, fill=1, stroke=0)
    dim_h(c, rx, rx + rw, ry - 10, f.num(fa))
    dim_v(c, rx - 10, ry, ry + rh, f.num(fb))
    ty = y + 4 + tab_h - 9
    for line in tab_lines:
        text(c, x + 6, ty, line, 6.5, color=ACCENT)
        ty -= 9


def part_cell(c, f: Fmt, g, cx, cy, cell_w, cell_h):
    p = g[0]
    names = wrap(f"{p.name}  ×{len(g)}", cell_w - 34, 10, True)
    if len(names) > 2:
        names = names[:1] + [fit_text(c, " ".join(names[1:]), cell_w - 34, 10, True)]
    iso.label(c, cx + 14, cy + cell_h - 22, p.letter, r=10, size=11 if len(p.letter) == 1 else 8)
    for i, line in enumerate(names):
        text(c, cx + 30, cy + cell_h - 26 - i * 12, line, 10, bold=True)
    yy = cy + cell_h - 38 - (len(names) - 1) * 12
    text(c, cx + 30, yy, f.t("thickness", t=f.len(p.thickness)), 7.5, color=MUTED)
    bev = p.bevels()
    if bev:
        text(c, cx + 30, yy - 11,
             f.t("bevel_note", angles=", ".join(f.angle(a) for a in sorted(set(bev)))), 6.5, color=ACCENT)
        yy -= 11
    draw_part_2d(c, f, p, cx, cy, cell_w, yy - cy - 14)


def focus_drawing(d: Doc, pids, box) -> int:
    """Подготовительный шаг: крупный чертёж детали с размерами вместо изометрии."""
    x, y, w, h = box
    parts = [d.prj.part(pid) for pid in pids]
    n = len(parts)
    for i, p in enumerate(parts):
        bw = w / n
        iso.label(d.c, x + i * bw + 14, y + h - 14, p.letter, r=10, size=11 if len(p.letter) == 1 else 8)
        draw_part_2d(d.c, d.fmt, p, x + i * bw, y, bw, h - 24, max_scale=1.2)
    return 0


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


def cut_section(d: Doc, uses, hints=()):
    c, f, prj = d.c, d.fmt, d.prj
    bar_w = W - 2 * M
    longest = {}
    for u in uses:
        longest[u.stock_id] = max(longest.get(u.stock_id, 0), u.length)

    def scale(u):
        st = prj.stock[u.stock_id]
        sc = bar_w / longest[u.stock_id]   # доски одной партии — в одном масштабе
        if st.kind == "sheet":
            sc = min(bar_w / u.length, 260 / u.width)
        return sc

    kinds = {prj.stock[u.stock_id].kind for u in uses}
    rip = any(prj.stock[u.stock_id].kind == "board" and pl.h < u.width - 1 for u in uses for pl in u.placed)
    parts_ = [f.t("cut_sub_kerf", kerf=f.len(prj.kerf))]
    if "board" in kinds:
        parts_.append(f.t("cut_sub_rip" if rip else "cut_sub_board"))
    if "sheet" in kinds:
        parts_.append(f.t("cut_sub_sheet"))
    d.y -= 14
    d.need(70 + (uses[0].width * scale(uses[0]) + 30 if uses else 0))   # заголовок не остаётся один
    d.heading(f.t("cut_title"), sub=" ".join(parts_))
    for h in hints:
        line = "→ " + hint_text(f, h)
        d.need(14, f.t("cut_title"))
        d.y = para(c, M, d.y, line, bar_w, 8.5, color=iso.DIM, bold=True) - 2
    for u in uses:
        st = prj.stock[u.stock_id]
        sc = scale(u)
        bh = u.width * sc
        d.need(bh + 30, f.t("cut_title"))
        d.y -= 14
        price = f"  ·  {fmt_money(u.price, prj.currency)}" if u.price is not None else ""
        text(c, M, d.y, fit_text(c, f"{st.name} {f.dims(st.thickness, u.width, u.length)}  —  "
                                    f"{f.t('stock_no', n=u.index)}{price}", bar_w, 8.5, True), 8.5, bold=True)
        y = d.y - 6 - bh
        c.setFillColor(HexColor("#EDEDED")); c.setStrokeColor(MUTED); c.setLineWidth(0.6)
        c.rect(M, y, u.length * sc, u.width * sc, fill=1, stroke=1)
        outside = []
        for pl in u.placed:
            x0 = M + pl.x * sc
            y0 = y + (u.width - pl.y - pl.h) * sc
            pw, ph = pl.w * sc, pl.h * sc
            c.setFillColor(WOOD); c.setStrokeColor(INK); c.setLineWidth(0.7)
            c.rect(x0, y0, pw, ph, fill=1, stroke=1)
            mid = x0 + pw / 2
            dims = f"{f.num(pl.w)}×{f.num(pl.h)}"
            if ph > 22 and pw > 18:
                iso.label(c, mid, y0 + ph / 2 + 4, pl.piece.letter, r=7, size=8 if len(pl.piece.letter) == 1 else 6)
                if c.stringWidth(dims, "DejaVu", 6.5) < pw - 2:
                    text(c, mid, y0 + 3, dims, 6.5, align="center")
            else:
                label = f"{pl.piece.letter} {dims}"
                if c.stringWidth(label, "DejaVu-Bold", 7) <= pw - 4 and ph >= 8:
                    text(c, mid, y0 + ph / 2 - 3, label, 7, bold=True, align="center")
                else:  # узкая полоска — подпись снаружи с выноской
                    outside.append((mid, y0 + ph / 2, label))
        ly = y - 12
        lx = M
        for mx, my, label in sorted(outside):
            w_ = c.stringWidth(label, "DejaVu-Bold", 7) + 10
            x_ = max(lx, mx - 4)               # подпись под своей полоской, если есть место
            if x_ + w_ > M + bar_w:
                ly -= 11
                x_ = max(M, mx - 4) if mx - 4 + w_ <= M + bar_w else M + bar_w - w_
            c.setStrokeColor(MUTED); c.setLineWidth(0.4)
            c.line(mx, y, mx, ly + 8)
            c.line(mx, ly + 8, x_ + 4, ly + 8)
            text(c, x_ + 4, ly, label, 7, bold=True)
            lx = x_ + w_
        d.y = (ly - 8) if outside else (y - 8)


def fmt_money(x, currency):
    s = f"{x:,.0f}".replace(",", " ")
    return f"{s} {currency}".strip() if currency else s


def hint_text(f: Fmt, h) -> str:
    p = dict(h.params)
    if h.code == "cut_offcut":
        return f.t("cut_offcut", stock=p["stock"], n=p["n"], pct=p["pct"], size=f.dims(p["w"], p["h"]))
    if h.code == "cut_tight":
        return f.t("cut_tight", stock=p["stock"], mm=f.len(p["mm"]), n=p["n"])
    return h.code


def position_dims(prj: Project, new_ids, placed_ids, view: str, fmt: Fmt, limit=3):
    """Размеры положения: где на соседней детали стоит новая, если её можно сдвинуть
    вдоль площадки контакта (полка на боковине, цоколь с отступом, перекладина).
    Возвращает [(a3, b3, off3, подпись_на_рисунке, строка_для_колонки)]."""
    from . import geom as G
    from .model import find_contact
    Rv = iso.view_rot(iso.VIEWS.get(view, 0))
    out, seen = [], set()
    for pid in new_ids:
        p = prj.part(pid)
        pv = p.poly.verts
        # оси, по которым положение уже задано упором в соседнюю деталь, — размер не нужен
        fixed = set()
        for rid in placed_ids:
            ct = find_contact(p, prj.part(rid))
            if ct:
                ax = max(range(3), key=lambda i: abs(ct.n[i]))
                if abs(ct.n[ax]) > 0.99:
                    fixed.add(ax)
        plo = [min(v[i] for v in pv) for i in range(3)]
        phi = [max(v[i] for v in pv) for i in range(3)]
        for qid in placed_ids:
            q = prj.part(qid)
            ct = find_contact(p, q)
            if not ct:
                continue
            nax = max(range(3), key=lambda i: abs(ct.n[i]))
            if abs(ct.n[nax]) < 0.99:
                continue  # наклонный стык — положение задаёт сама плоскость
            qv = q.poly.verts
            qlo = [min(v[i] for v in qv) for i in range(3)]
            qhi = [max(v[i] for v in qv) for i in range(3)]
            for k in (2, 1, 0):
                if k == nax or k in fixed or (pid, k) in seen:
                    continue
                inside = plo[k] > qlo[k] + 1 and phi[k] < qhi[k] - 1
                sticks_out = qlo[k] + 1 < plo[k] < qhi[k] - 1 and phi[k] > qhi[k] + 1   # фронтон на столбиках
                if inside or sticks_out:
                    seen.add((pid, k))
                    off = plo[k] - qlo[k]
                    corners = [(x, y, z) for x in (plo[0], phi[0]) for y in (plo[1], phi[1]) for z in (plo[2], phi[2])]
                    corner = max(corners, key=lambda cc: G.dot(G.mat_vec(Rv, cc), iso.VIEW_DIR))
                    a3 = list(corner); a3[k] = qlo[k]
                    b3 = list(corner); b3[k] = plo[k]
                    j = next(i for i in (0, 1, 2) if i not in (k, nax))
                    ctr = (plo[j] + phi[j]) / 2
                    o = [0.0, 0.0, 0.0]; o[j] = 40.0 if corner[j] >= ctr else -40.0
                    line = fmt.t(f"pos_{'xyz'[k]}", p=p.letter, d=fmt.len(off), q=q.letter)
                    out.append((tuple(a3), tuple(b3), tuple(o), fmt.num(off), line))
                    if len(out) >= limit:
                        return out
    return out


def zoom_screws(d: Doc, si: int, cur, view_name: str, commit=True) -> list:
    """Лупа на шаге: когда крепёж этого вида встречается впервые (или это конфирмат) и
    его входы видны на картинке. Возвращает саморезы узла для лупы или []."""
    if not cur:
        return []
    seen = d.__dict__.setdefault("_zoomed_specs", set())
    Rv = iso.view_rot(iso.VIEWS.get(view_name, 0))
    vis = [s for s in cur if iso.visible(G_mat_vec(Rv, s.normal))]
    if not vis:
        return []
    k = vis[0].key
    if k in seen and k[0] != "confirmat":
        return []
    if commit:
        seen.add(k)
    return vis


def G_mat_vec(R, v):
    from .geom import mat_vec
    return mat_vec(R, v)


def step_dims(prj: Project, st, scene, fmt: Fmt, limit=3):
    """Размеры положения для шага: новые детали — относительно уже стоящих
    и относительно добавленных раньше в этом же шаге. Одинаковые подписи — один раз."""
    old_ids, new_ids, mode = scene
    out, seen = [], set()
    for i, pid in enumerate(new_ids):
        refs = list(old_ids) + ([] if mode == "attach" else new_ids[:i])
        for dm in position_dims(prj, [pid], refs, st.view, fmt, limit=limit):
            if dm[4] not in seen and len(out) < limit:
                seen.add(dm[4])
                out.append(dm)
    return out


def _step_side(c, d: Doc, si, rx, ry, colw, cur, shown, draw=True, dims=(), scene=None):
    """Правая колонка шага. Возвращает y под последней строкой."""
    prj, f = d.prj, d.fmt
    st = prj.steps[si]
    notes = []
    if st.group:
        notes.append(f.t("subassembly"))
    if st.same_as:
        notes.append(f.t("same_as_mirror" if st.mirror else "same_as", n=st.same_as))
    for note in notes:
        ry = para(c, rx, ry + 4, note, colw, 8.5, color=MUTED, bold=True, draw=draw) - 6
    if st.add:
        letters = Counter(prj.part(pid).letter for pid in st.add)
        for L, n in sorted(letters.items(), key=lambda kv: (len(kv[0]), kv[0])):
            name = next(p.name for p in prj.parts if p.letter == L)
            lines = wrap(f"×{n}  {name}", colw - 28, 10, True)
            if len(lines) > 2:
                lines = [lines[0], fit_text(c, " ".join(lines[1:]), colw - 28, 10, True)]
            if draw:
                iso.label(c, rx + 10, ry, L, r=10, size=11 if len(L) == 1 else 8)
                for k2, line in enumerate(lines):
                    text(c, rx + 26, ry - 4 - k2 * 12, line, 10, bold=True)
            ry -= 26 + 12 * (len(lines) - 1)
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
    for dm in dims:
        ry = para(c, rx, ry - 2, "↔ " + dm[4], colw, 8.5, color=iso.DIM, bold=True, draw=draw) - 2
    if dims:
        ry -= 4
    if cur:
        hidden = len(cur) - shown
        note = (f.t("screw_marks") if shown else "") + (f.t("screw_marks_back") if hidden else "")
        ry = para(c, rx, ry - 4, note.strip(" ;"), colw, 7.5, color=ACCENT, draw=draw) - 6
    return para(c, rx, ry - 6, st.text, colw, 9.2, draw=draw)


def step_block(d: Doc, si: int, box, screws_by_step, scene):
    c, prj = d.c, d.prj
    st = prj.steps[si]
    old_ids, new_ids, mode = scene
    x, y, w, h = box
    iso.label(c, x + 16, y + h - 18, str(si + 1), r=16, size=16 if si < 9 else 13)
    title_w = w - 50
    if st.times > 1:
        badge = d.fmt.t("times", n=st.times)
        bw = c.stringWidth(badge, "DejaVu-Bold", 13) + 12
        c.setFillColor(YEL); c.roundRect(x + w - bw, y + h - 28, bw, 18, 9, fill=1, stroke=0)
        text(c, x + w - bw / 2, y + h - 23, badge, 13, bold=True, align="center")
        title_w -= bw + 8
    text(c, x + 40, y + h - 23, fit_text(c, st.title, title_w, 14, True), 14, bold=True)

    cur = screws_by_step.get(si, [])
    scene_ids = set(old_ids) | set(new_ids)
    old = [s for k, v in screws_by_step.items() if k < si for s in v
           if s.through in scene_ids and s.into in scene_ids]
    img_box = (x, y + 26, w * 0.62, h - 56)
    dims = step_dims(prj, st, scene, d.fmt)
    if new_ids:
        styles = {pid: "old" for pid in old_ids}
        styles.update({pid: "new" for pid in new_ids})
        ref = [prj.part(pid) for pid in styles]
        zoom = zoom_screws(d, si, cur, st.view)
        R = min(52.0, img_box[2] * 0.2, img_box[3] * 0.28)
        main_box = img_box
        if zoom:  # место под лупу — справа внизу рамки, основной рисунок ужимаем
            main_box = (img_box[0], img_box[1], img_box[2] - 2 * R - 10, img_box[3])
        shown, mv = iso.draw_scene(c, prj, main_box, styles, cur, old, ref_parts=ref, extra=120, view=st.view,
                                   dims=[(a, b, o, t) for a, b, o, t, _ in dims])
        if zoom:
            from .model import EDGE_MIN
            k = zoom[0].key
            spec = d.fmt.t("confirmat_spec" if k[0] == "confirmat" else "screw_spec", spec=d.fmt.screw(*k))
            center = (img_box[0] + img_box[2] - R - 2, img_box[1] + R + 24)
            iso.draw_zoom(c, prj, mv, center, R, styles, zoom, d.fmt.t("zoom_edge", m=d.fmt.len(EDGE_MIN)), spec)
    elif st.focus:
        shown = focus_drawing(d, st.focus, img_box)
    else:
        shown = 0
    _step_side(c, d, si, x + w * 0.64, y + h - 60, w * 0.36, cur, shown, dims=dims, scene=scene)
    c.setStrokeColor(LINE); c.setLineWidth(0.6)
    c.line(x, y + 20, x + w, y + 20)


def steps_section(d: Doc, screws_by_step):
    c, prj = d.c, d.prj
    d.new_page()
    full = TOP - BOTTOM
    half = full / 2
    from .model import step_scenes
    scenes = step_scenes(prj)
    slot = 0
    for si, st in enumerate(prj.steps):
        cur = screws_by_step.get(si, [])
        # сколько места просит правая колонка
        dims = step_dims(prj, st, scenes[si], d.fmt)
        need = TOP - _step_side(c, d, si, 0, TOP - 60, (W - 2 * M) * 0.36, cur, len(cur), draw=False,
                                dims=dims, scene=scenes[si]) + 30
        tall = need > half
        if tall and slot == 1:
            d.new_page(); slot = 0
        h = full if tall else half
        box = (M, TOP - slot * half - h, W - 2 * M, h)
        step_block(d, si, box, screws_by_step, scenes[si])
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
    glue = any(st.glue for st in prj.steps)
    items = [f.t("safety_" + flag + ("" if flag != "outdoor" or glue else "_noglue")) for flag in prj.safety]
    items += [f.t("safety_general")]
    _bullets(d, f.t("safety_title"), items, mark="▲", fill="#1E1E1E")
    loads_block(d)
    disc = (prj.disclaimer + "\n\n" if prj.disclaimer else "") + f.t("disclaimer")
    h = len(wrap(disc, W - 2 * M - 20, 8.5)) * 8.5 * 1.4 + 20
    d.need(h + 10)
    d.y -= 8
    c.setFillColor(HexColor("#F3F1EC"))
    c.roundRect(M, d.y - h + 8, W - 2 * M, h, 6, fill=1, stroke=0)
    d.y = para(c, M + 10, d.y - 6, disc, W - 2 * M - 20, 8.5, leading=8.5 * 1.4, color=MUTED) - 10


MM = 72 / 25.4
TPL_MARGIN = 12 * MM


def _template_region(p):
    """Область шаблона в координатах чертежа (от левого нижнего угла габарита):
    проёмы, фурнитура и резы с запасом 25 мм, дотянутые до ближайших краёв детали,
    чтобы шаблон можно было приложить к углу. None — шаблон не нужен."""
    prof = p.profile("-t")
    prof2 = p.profile("+t")
    u0 = min(q[0] for q in prof + prof2)
    v0 = min(q[1] for q in prof + prof2)
    fa, fb = p.face_dims
    # «кромки габарита» считаем по самой пласти -t: скос торца сам по себе шаблона не требует
    pu0, pu1 = min(q[0] for q in prof) - u0, max(q[0] for q in prof) - u0
    pv0, pv1 = min(q[1] for q in prof) - v0, max(q[1] for q in prof) - v0
    pts = []
    for hh in template_holes(p):
        pts += [(hh.at[0] + du - u0, hh.at[1] + dv - v0) for du, dv in hh.outline(16)]
    on_box = lambda q: abs(q[0]) < 0.5 or abs(q[0] - fa) < 0.5 or abs(q[1]) < 0.5 or abs(q[1] - fb) < 0.5
    for i in range(len(prof)):
        a = (prof[i][0] - u0, prof[i][1] - v0)
        b = (prof[(i + 1) % len(prof)][0] - u0, prof[(i + 1) % len(prof)][1] - v0)
        same_side = (abs(a[0] - b[0]) < 0.5 and (abs(a[0] - pu0) < 0.5 or abs(a[0] - pu1) < 0.5)) or \
                    (abs(a[1] - b[1]) < 0.5 and (abs(a[1] - pv0) < 0.5 or abs(a[1] - pv1) < 0.5))
        if not same_side:      # ребро-рез, а не кромка габарита
            pts += [a, b]
    if not pts:
        return None
    m = 25.0
    cu0, cu1 = max(0, min(q[0] for q in pts) - m), min(fa, max(q[0] for q in pts) + m)
    cv0, cv1 = max(0, min(q[1] for q in pts) - m), min(fb, max(q[1] for q in pts) + m)
    # шаблон должен касаться хотя бы одного края детали по каждой оси — чтобы было к чему приложить
    if cu0 > 0.5 and cu1 < fa - 0.5:
        if cu0 <= fa - cu1:
            cu0 = 0.0
        else:
            cu1 = fa
    if cv0 > 0.5 and cv1 < fb - 0.5:
        if cv0 <= fb - cv1:
            cv0 = 0.0
        else:
            cv1 = fb
    return cu0, cv0, cu1, cv1


def template_holes(p):
    """Проёмы, которым нужен шаблон: фигурные и крупные круглые. Мелкие отверстия сверлят по разметке."""
    return [h for h in p.holes if h.shape != "circle" or h.d >= 40]


def template_parts(prj: Project):
    if prj.templates is False:
        return []
    out = []
    for g in part_groups(prj):
        p = g[0]
        if isinstance(prj.templates, list) and not any(q.id in prj.templates for q in g):
            continue
        reg = _template_region(p)
        if reg:
            out.append((p, reg))
    return out


TPL_HEAD = 62   # высота шапки шаблона, pt


def templates_section(d: Doc, limit_pages=16):
    """Шаблоны в натуральную величину: печатать в масштабе 100 %, большие — на нескольких листах."""
    parts = template_parts(d.prj)
    if not parts:
        return
    tw = (W - 2 * TPL_MARGIN) / MM
    th = (H - 2 * TPL_MARGIN - TPL_HEAD) / MM
    ov = 10.0
    pages = 0

    def tiles(region):
        rw, rh = region[2] - region[0], region[3] - region[1]
        nx = max(1, math.ceil((rw - ov) / (tw - ov))) if rw > tw else 1
        ny = max(1, math.ceil((rh - ov) / (th - ov))) if rh > th else 1
        return nx, ny

    def emit(p, region, hole_only=False):
        nonlocal pages
        nx, ny = tiles(region)
        if pages + nx * ny > limit_pages:
            return
        for j in range(ny):
            for i in range(nx):
                d.new_page()
                pages += 1
                _template_tile(d, p, region, region[0] + i * (tw - ov), region[1] + j * (th - ov),
                               tw, th, ov, i, j, nx, ny, hole_only=hole_only)

    for p, region in parts:
        nx, ny = tiles(region)
        if nx * ny <= 2 or not template_holes(p):
            if nx * ny <= 4:
                emit(p, region)
            continue
        # большая деталь: прямые резы проще разметить рулеткой, шаблон — только на проёмы
        prof = p.profile("-t") + p.profile("+t")
        u0, v0 = min(q[0] for q in prof), min(q[1] for q in prof)
        for hh in template_holes(p):
            r = hh.radius + 15
            reg = (hh.at[0] - u0 - r, hh.at[1] - v0 - r, hh.at[0] - u0 + r, hh.at[1] - v0 + r)
            if tiles(reg)[0] * tiles(reg)[1] <= 4:
                emit(p, reg, hole_only=True)


def _template_tile(d, p, region, x0, y0, tw, th, ov, i, j, nx, ny, hole_only=False):
    c, f = d.c, d.fmt
    cu0, cv0, cu1, cv1 = region
    prof, prof2 = p.profile("-t"), p.profile("+t")
    u0 = min(q[0] for q in prof + prof2)
    v0 = min(q[1] for q in prof + prof2)
    fa, fb = p.face_dims
    ox, oy = TPL_MARGIN - x0 * MM, TPL_MARGIN - y0 * MM
    P = lambda q: (ox + (q[0] - u0) * MM, oy + (q[1] - v0) * MM)
    Q = lambda u, v: (ox + u * MM, oy + v * MM)           # координаты чертежа (от угла габарита)
    # шапка: слева название и как печатать, справа контрольный отрезок и схема листов
    top = H - TPL_MARGIN
    iso.label(c, TPL_MARGIN + 10, top - 8, p.letter, r=10, size=11 if len(p.letter) == 1 else 8)
    head = f.t("tpl_title", name=p.name)
    if nx * ny > 1:
        head += " · " + f.t("tpl_tile", k=j * nx + i + 1, n=nx * ny, row=j + 1, col=i + 1)
    bar = 100.0 if f.units == "mm" else 4 * 25.4
    right_w = bar * MM + 8
    left_w = W - 2 * TPL_MARGIN - right_w - 30
    text(c, TPL_MARGIN + 26, top - 12, fit_text(c, head, W - 2 * TPL_MARGIN - 30, 10, True), 10, bold=True)
    note = f.t("tpl_print") + (" " + f.t("tpl_glue") if nx * ny > 1 else "") + " " + \
        (f.t("tpl_hole_only") if hole_only else f.t("tpl_origin"))
    para(c, TPL_MARGIN, top - 28, note, left_w + 26, 7, color=MUTED)
    bx, by = W - TPL_MARGIN - bar * MM, top - 32
    c.setStrokeColor(INK); c.setLineWidth(1)
    c.line(bx, by, bx + bar * MM, by)
    for t in (0, 1):
        c.line(bx + t * bar * MM, by - 4, bx + t * bar * MM, by + 4)
    text(c, bx + bar * MM / 2, by + 6, f.len(bar), 7.5, bold=True, align="center")
    if nx * ny > 1:
        s = 7
        for jj in range(ny):
            for ii in range(nx):
                c.setFillColor(YEL if (ii, jj) == (i, j) else HexColor("#FFFFFF"))
                c.setStrokeColor(MUTED); c.setLineWidth(0.4)
                c.rect(bx + ii * s, by - 14 - (ny - jj) * s, s, s, fill=1, stroke=1)
    # поле: только область шаблона на этом листе
    vx0, vy0 = max(x0, cu0), max(y0, cv0)
    vx1, vy1 = min(x0 + tw, cu1), min(y0 + th, cv1)
    fx, fy = Q(vx0, vy0)
    fw, fh = (vx1 - vx0) * MM, (vy1 - vy0) * MM
    c.saveState()
    clip = c.beginPath(); clip.rect(fx, fy, fw, fh)
    c.clipPath(clip, stroke=0, fill=0)
    c.setFillColor(HexColor("#EEF3FB"))
    if i > 0:
        c.rect(fx, fy, ov * MM, fh, fill=1, stroke=0)
    if j > 0:
        c.rect(fx, fy, fw, ov * MM, fill=1, stroke=0)
    path = c.beginPath(); path.moveTo(*P(prof[0]))
    for q in prof[1:]:
        path.lineTo(*P(q))
    path.close()
    c.setFillColor(HexColor("#FBF6EC")); c.setStrokeColor(INK); c.setLineWidth(1.4)
    c.drawPath(path, fill=1, stroke=1)
    if p.bevels():
        path = c.beginPath(); path.moveTo(*P(prof2[0]))
        for q in prof2[1:]:
            path.lineTo(*P(q))
        path.close()
        c.setStrokeColor(ACCENT); c.setLineWidth(0.6); c.setDash(4, 3)
        c.drawPath(path, fill=0, stroke=1)
        c.setDash()
    for q in prof:  # координаты точек реза
        uu, vv = q[0] - u0, q[1] - v0
        if (round(uu), round(vv)) not in {(0, 0), (round(fa), 0), (0, round(fb)), (round(fa), round(fb))}:
            x, y = P(q)
            _crosshair(c, x, y, 4 * MM)
            text(c, x + (2 * MM if uu < fa / 2 else -2 * MM), y - 4 * MM, f"{f.num(uu)} / {f.num(vv)}", 7,
                 bold=True, color=ACCENT, align="left" if uu < fa / 2 else "right")
    for hh in p.holes:
        pts = [P((hh.at[0] + du, hh.at[1] + dv)) for du, dv in hh.outline(72)]
        path = c.beginPath(); path.moveTo(*pts[0])
        for q in pts[1:]:
            path.lineTo(*q)
        path.close()
        c.setStrokeColor(INK); c.setLineWidth(0.9); c.drawPath(path, fill=0, stroke=1)
        hx, hy = P(hh.at)
        _crosshair(c, hx, hy, 6 * MM)
        text(c, hx + 2 * MM, hy + 2 * MM, f"{_hole_label(f, hh)} · " +
             f.t("center_at", u=f.num(hh.at[0] - u0), v=f.num(hh.at[1] - v0)), 7, bold=True, color=ACCENT)
    for m in p.hardware:
        hx, hy = P(m.at)
        _crosshair(c, hx, hy, 4 * MM)
        text(c, hx + 2 * MM, hy - 4 * MM, f"{m.name}  {f.num(m.at[0] - u0)} / {f.num(m.at[1] - v0)}", 7,
             color=ACCENT)
    c.restoreState()
    # где деталь продолжается за шаблоном — волнистый обрыв и подпись
    c.setStrokeColor(MUTED); c.setLineWidth(0.6); c.setDash(5, 3)
    for edge, cut in (("l", vx0 > 0.5), ("r", vx1 < fa - 0.5), ("b", vy0 > 0.5), ("t", vy1 < fb - 0.5)):
        if not cut:
            continue
        if edge in "lr":
            x = fx if edge == "l" else fx + fw
            c.line(x, fy, x, fy + fh)
        else:
            y = fy if edge == "b" else fy + fh
            c.line(fx, y, fx + fw, y)
    c.setDash()


def _crosshair(c, x, y, r):
    c.setStrokeColor(ACCENT); c.setLineWidth(0.5)
    c.line(x - r, y, x + r, y)
    c.line(x, y - r, x, y + r)
    c.circle(x, y, 0.6 * MM, fill=0, stroke=1)


def build(prj: Project, out: str):
    register_fonts()
    fmt = Fmt(prj.lang, prj.units)
    d = Doc(prj, out, fmt)
    screws_by_step = plan_screws(prj)
    total = Counter(s.key for v in screws_by_step.values() for s in v)
    uses, hints = cutlist.plan_with_hints(prj)

    cover(d, total, uses)
    d.new_page()
    parts_section(d)
    cut_section(d, uses, hints)
    steps_section(d, screws_by_step)
    tips_section(d)
    templates_section(d)
    d.save()


def layout_issues(prj: Project) -> list:
    """Тексты, которые не влезут в вёрстку, — предупреждение, а не молчаливая обрезка."""
    from .model import warn
    register_fonts()
    out = []
    if len(wrap(prj.title, W - 2 * M, 22, True)) > 2:
        out.append(warn("text_too_long", field="title", max="2"))
    if prj.subtitle and pdfmetrics.stringWidth(prj.title, "DejaVu-Bold", 34) >= W - 2 * M:
        max_sub = 1
    else:
        max_sub = 2
    if len(wrap(prj.subtitle, W - 2 * M, 12)) > max_sub:
        out.append(warn("text_too_long", field="subtitle", max=str(max_sub)))
    cw = (W - 2 * M - 3 * 10) / 4 - 16
    for fld in ("difficulty", "time"):
        if pdfmetrics.stringWidth(getattr(prj, fld) or "", "DejaVu-Bold", 12) > cw:
            out.append(warn("text_too_long", field=fld, max="1"))
    for st in prj.steps:
        if pdfmetrics.stringWidth(st.title, "DejaVu-Bold", 14) > W - 2 * M - 50:
            out.append(warn("text_too_long", field=f"steps[{st.title[:20]}…].title", max="1"))
    return out
