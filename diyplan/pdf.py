"""Сборка PDF-инструкции: обложка → детали и раскрой → шаги → советы."""
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
from .model import Project, part_groups, plan_screws

W, H = A4
M = 36
INK = HexColor("#1E1E1E")
MUTED = HexColor("#6B6B6B")
LINE = HexColor("#D8D8D8")
ACCENT = HexColor("#D9381E")
WOOD = HexColor("#F4E6CB")
YEL = HexColor("#FFC93C")

FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/TTF/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
]


def register_fonts():
    env = os.environ.get("DIYPLAN_FONT"), os.environ.get("DIYPLAN_FONT_BOLD")
    for reg, bold in ([env] if env[0] else []) + FONT_CANDIDATES:
        if reg and os.path.exists(reg) and os.path.exists(bold or reg):
            pdfmetrics.registerFont(TTFont("DejaVu", reg))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", bold or reg))
            return
    raise SystemExit("Не найден шрифт с кириллицей. Укажите путь в DIYPLAN_FONT / DIYPLAN_FONT_BOLD.")


# ---------- примитивы ----------

def text(c, x, y, s, size=10, bold=False, color=INK, align="left"):
    c.setFont("DejaVu-Bold" if bold else "DejaVu", size)
    c.setFillColor(color)
    {"left": c.drawString, "center": c.drawCentredString, "right": c.drawRightString}[align](x, y, s)


def para(c, x, y, s, width, size=10, leading=None, color=INK, bold=False):
    leading = leading or size * 1.35
    font = "DejaVu-Bold" if bold else "DejaVu"
    for chunk in s.split("\n"):
        for line in simpleSplit(chunk, font, size, width) or [""]:
            text(c, x, y, line, size, bold, color)
            y -= leading
    return y


def footer(c, prj: Project, page: int):
    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.line(M, 28, W - M, 28)
    text(c, M, 16, prj.title, 8, color=MUTED)
    text(c, W - M, 16, str(page), 8, color=MUTED, align="right")


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


def chip(c, x, y, label, value):
    c.setFillColor(HexColor("#F3F1EC"))
    c.roundRect(x, y, 118, 40, 6, fill=1, stroke=0)
    text(c, x + 10, y + 25, label, 8, color=MUTED)
    text(c, x + 10, y + 9, value, 12, bold=True)


def dim_h(c, x0, x1, y, value, size=7.5):
    c.setStrokeColor(MUTED); c.setLineWidth(0.5)
    c.line(x0, y, x1, y)
    for x in (x0, x1):
        c.line(x, y - 3, x, y + 3)
    s = f"{value:.0f}"
    w = c.stringWidth(s, "DejaVu", size) + 4
    c.setFillColor(HexColor("#FFFFFF")); c.rect((x0 + x1) / 2 - w / 2, y - 4, w, 8, fill=1, stroke=0)
    text(c, (x0 + x1) / 2, y - 2.6, s, size, color=INK, align="center")


def dim_v(c, x, y0, y1, value, size=7.5):
    c.saveState()
    c.translate(x, (y0 + y1) / 2)
    c.rotate(90)
    dim_h(c, -(y1 - y0) / 2, (y1 - y0) / 2, 0, value, size)
    c.restoreState()


# ---------- страницы ----------

def cover(c, prj: Project, total_screws: Counter, uses):
    c.setFillColor(YEL)
    c.rect(0, H - 150, W, 150, fill=1, stroke=0)
    text(c, M, H - 70, prj.title, 34, bold=True)
    para(c, M, H - 100, prj.subtitle, W - 2 * M, 13)
    iso.draw_scene(c, prj, (M, 330, W - 2 * M, H - 150 - 345), {p.id: "old" for p in prj.parts},
                   arrows=False, labels=False, extra=30)
    y = 270
    chip(c, M, y, "Сложность", prj.difficulty or "—")
    chip(c, M + 130, y, "Время", prj.time or "—")
    chip(c, M + 260, y, "Деталей", str(len(prj.parts)))
    chip(c, M + 390, y, "Саморезов", str(sum(total_screws.values())))

    col = (W - 2 * M - 20) / 2
    yy = 240
    text(c, M, yy, "Что купить", 12, bold=True)
    y1 = yy - 18
    for name, n in cutlist.shopping(prj, uses):
        y1 = para(c, M, y1, f"• {name} — {n} шт", col, 9)
    for spec, n in sorted(total_screws.items()):
        y1 = para(c, M, y1, f"• Саморезы по дереву {spec} мм — {n} шт (+ пару про запас)", col, 9)
    for m in prj.extra_materials:
        y1 = para(c, M, y1, f"• {m}", col, 9)
    text(c, M + col + 20, yy, "Инструменты", 12, bold=True)
    y2 = yy - 18
    for t in prj.tools:
        y2 = para(c, M + col + 20, y2, f"• {t}", col, 9)


def parts_page(c, prj: Project, uses):
    text(c, M, H - 60, "Детали", 20, bold=True)
    text(c, M, H - 78, "Все размеры в миллиметрах. Буква на детали совпадает с буквой в шагах сборки.", 9, color=MUTED)
    groups = part_groups(prj)
    cols = 3
    cell_w = (W - 2 * M) / cols
    cell_h = 195
    maxdim = max(max(g[0].face_dims) for g in groups)
    scale = min((cell_w - 60) / maxdim, (cell_h - 100) / maxdim)
    top = H - 95
    for i, g in enumerate(groups):
        p = g[0]
        cx = M + (i % cols) * cell_w
        cy = top - (i // cols + 1) * cell_h
        fa, fb = p.face_dims
        rw, rh = fa * scale, fb * scale
        rx = cx + 28 + (cell_w - 40 - rw) / 2
        ry = cy + 26 + (cell_h - 100 - rh) / 2
        prof, prof2 = p.profile("-t"), p.profile("+t")
        u0 = min(q[0] for q in prof + prof2)
        v0 = min(q[1] for q in prof + prof2)
        P = lambda q: (rx + (q[0] - u0) * scale, ry + (q[1] - v0) * scale)
        # пунктир — габарит заготовки, если деталь не прямоугольная
        if len(prof) != 4 or p.bevels():
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
        if p.bevels():  # вторая пласть отличается — рисуем её контур
            path = c.beginPath()
            path.moveTo(*P(prof2[0]))
            for q in prof2[1:]:
                path.lineTo(*P(q))
            path.close()
            c.setStrokeColor(ACCENT); c.setLineWidth(0.6); c.setDash(3, 2)
            c.drawPath(path, fill=0, stroke=1)
            c.setDash()
        # вершины, которые не совпадают с углами габарита, — подписываем координатами
        corners = {(0, 0), (round(fa), 0), (0, round(fb)), (round(fa), round(fb))}
        pcx = sum(P(q)[0] for q in prof) / len(prof)
        pcy = sum(P(q)[1] for q in prof) / len(prof)
        for q in prof:
            uu, vv = round(q[0] - u0), round(q[1] - v0)
            if (uu, vv) in corners:
                continue
            x, y = P(q)
            dx, dy = x - pcx, y - pcy
            L = math.hypot(dx, dy) or 1
            tx, ty = x + dx / L * 6, y + dy / L * 6
            align = "left" if dx > 3 else "right" if dx < -3 else "center"
            c.setFillColor(ACCENT); c.circle(x, y, 1.6, fill=1, stroke=0)
            text(c, tx, ty - (2 if abs(dy) < abs(dx) else 0) + (0 if dy >= 0 else -6), f"{uu} / {vv}",
                 6.5, bold=True, color=ACCENT, align=align)
        for h in p.holes:
            hx, hy = P((h.at[0], h.at[1]))
            c.setFillColor(HexColor("#3B2A1C"))
            c.circle(hx, hy, h.d / 2 * scale, fill=1, stroke=0)
            c.setStrokeColor(ACCENT); c.setLineWidth(0.4); c.setDash(2, 2)
            c.line(rx, hy, hx, hy)
            c.line(hx, ry, hx, hy)
            c.setDash()
            text(c, hx + h.d / 2 * scale + 3, hy + 2, f"⌀{h.d:g}", 7.5, bold=True, color=ACCENT)
            text(c, hx + h.d / 2 * scale + 3, hy - 8, f"{h.at[0] - u0:.0f} / {h.at[1] - v0:.0f}", 6.5, color=ACCENT)
        dim_h(c, rx, rx + rw, ry - 10, fa)
        dim_v(c, rx - 10, ry, ry + rh, fb)
        bev = p.bevels()
        if bev:
            text(c, cx + 30, cy + cell_h - 49, "скос " + ", ".join(f"{a:g}°" for a in sorted(set(bev)))
                 + " — пунктир: обратная сторона", 6.5, color=ACCENT)
        iso.label(c, cx + 14, cy + cell_h - 22, p.letter, r=10, size=11)
        text(c, cx + 30, cy + cell_h - 26, f"{p.name}  ×{len(g)}", 10, bold=True)
        text(c, cx + 30, cy + cell_h - 38, f"толщина {p.thickness:g}", 7.5, color=MUTED)

    rows = (len(groups) + cols - 1) // cols
    y = top - rows * cell_h - 30
    text(c, M, y, "Раскрой", 20, bold=True)
    text(c, M, y - 16, f"Учтён пропил {prj.kerf:g} мм. Сначала отпилите детали поперёк, потом распустите по ширине.",
         9, color=MUTED)
    y -= 40
    bar_w = W - 2 * M
    for u in uses:
        st = prj.stock[u.stock_id]
        sc = bar_w / st.length
        bh = st.width * sc
        if st.kind == "sheet":
            bh = min(bh, 220)
            sc = min(sc, 220 / st.width)
        y -= bh + 18
        text(c, M, y + bh + 5, f"{st.name} {st.thickness:g}×{st.width:g}×{st.length:g}  —  №{u.index}", 8.5, bold=True)
        c.setFillColor(HexColor("#EDEDED")); c.setStrokeColor(MUTED); c.setLineWidth(0.6)
        c.rect(M, y, st.length * sc, st.width * sc, fill=1, stroke=1)
        for pl in u.placed:
            x0 = M + pl.x * sc
            y0 = y + (st.width - pl.y - pl.h) * sc
            c.setFillColor(WOOD); c.setStrokeColor(INK); c.setLineWidth(0.7)
            c.rect(x0, y0, pl.w * sc, pl.h * sc, fill=1, stroke=1)
            mid = x0 + pl.w * sc / 2
            if pl.h * sc > 22:
                iso.label(c, mid, y0 + pl.h * sc / 2 + 4, pl.piece.letter, r=7, size=8)
                text(c, mid, y0 + 3, f"{pl.w:.0f}×{pl.h:.0f}", 6.5, align="center")
            else:
                text(c, mid, y0 + pl.h * sc / 2 - 3, f"{pl.piece.letter} {pl.w:.0f}×{pl.h:.0f}", 6.5, bold=True, align="center")


def step_block(c, prj: Project, si: int, num: int, box, screws_by_step, placed_before: list[str]):
    st = prj.steps[si]
    x, y, w, h = box
    iso.label(c, x + 16, y + h - 18, str(num), r=16, size=16)
    text(c, x + 40, y + h - 23, st.title, 14, bold=True)

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
                               arrows=False, extra=30, view=st.view)

    # правая колонка: что нужно + текст
    rx = x + w * 0.64
    ry = y + h - 60
    if st.add:
        letters = Counter(prj.part(pid).letter for pid in st.add)
        for L, n in sorted(letters.items()):
            iso.label(c, rx + 10, ry, L, r=10, size=11)
            name = next(p.name for p in prj.parts if p.letter == L)
            text(c, rx + 26, ry - 4, f"×{n}  {name}", 10, bold=True)
            ry -= 26
    specs = Counter(s.spec for s in cur)
    for spec, n in sorted(specs.items()):
        screw_icon(c, rx + 10, ry - 14)
        text(c, rx + 26, ry - 4, f"×{n}", 12, bold=True)
        text(c, rx + 26, ry - 16, f"саморез {spec}", 8, color=MUTED)
        ry -= 36
    if st.glue:
        glue_icon(c, rx + 10, ry - 22)
        text(c, rx + 26, ry - 6, "клей ПВА", 10, bold=True)
        text(c, rx + 26, ry - 18, "на все стыки", 8, color=MUTED)
        ry -= 38
    if cur:
        hidden = len(cur) - shown
        note = "● — места саморезов" + (f"; ещё {hidden} с невидимой стороны" if hidden and shown else "")
        if not shown:
            note = "Саморезы — с невидимой на рисунке стороны"
        ry = para(c, rx, ry - 4, note, w * 0.36, 7.5, color=ACCENT) - 6
    para(c, rx, ry - 6, st.text, w * 0.36, 9.2)
    c.setStrokeColor(LINE); c.setLineWidth(0.6)
    c.line(x, y + 20, x + w, y + 20)


def tips_page(c, prj: Project):
    text(c, M, H - 60, "Важно", 20, bold=True)
    y = H - 95
    for i, t in enumerate(prj.tips, 1):
        iso.label(c, M + 10, y + 3, "!", r=10, fill="#D9381E", size=11)
        y = para(c, M + 30, y, t, W - 2 * M - 30, 10.5) - 10


def build(prj: Project, out: str):
    register_fonts()
    c = canvas.Canvas(out, pagesize=A4)
    c.setTitle(prj.title)
    c.setAuthor("diyplan")
    screws_by_step = plan_screws(prj)
    total = Counter(s.spec for v in screws_by_step.values() for s in v)
    uses = cutlist.plan(prj)

    page = 1
    cover(c, prj, total, uses); footer(c, prj, page); c.showPage(); page += 1
    parts_page(c, prj, uses); footer(c, prj, page); c.showPage(); page += 1

    placed: list[str] = []
    half = (H - 2 * M - 20) / 2
    slot = 0
    for si, st in enumerate(prj.steps):
        box = (M, H - M - (slot + 1) * half, W - 2 * M, half)
        step_block(c, prj, si, si + 1, box, screws_by_step, list(placed))
        placed += [p for p in st.add if p not in placed]
        slot += 1
        if slot == 2:
            footer(c, prj, page); c.showPage(); page += 1; slot = 0
    if slot:
        footer(c, prj, page); c.showPage(); page += 1
    if prj.tips:
        tips_page(c, prj); footer(c, prj, page); c.showPage()
    c.save()
