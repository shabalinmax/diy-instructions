"""Строки интерфейса и форматирование размеров (мм / дюймы).

Внутри движка всё в миллиметрах. Язык и единицы влияют только на ввод (дюймы → мм при загрузке)
и на вывод (сообщения проверки, PDF).
"""
from __future__ import annotations

from fractions import Fraction

LANGS = ("ru", "en")
MM_PER_IN = 25.4


# ---------- размеры ----------

class Fmt:
    def __init__(self, lang: str = "ru", units: str = "mm"):
        self.lang = lang if lang in LANGS else "en"
        self.units = units if units in ("mm", "in") else "mm"

    def num(self, mm: float) -> str:
        """Число без единиц: 326 или 12 7/8."""
        if self.units == "mm":
            if abs(mm) < 10 and abs(mm - round(mm)) > 0.05:
                return f"{mm:.1f}"
            return f"{mm:.0f}"
        return inches_str(mm / MM_PER_IN)

    def len(self, mm: float) -> str:
        """С единицами: 326 мм / 12 7/8″."""
        if self.units == "mm":
            return f"{mm:.0f} {self.t('unit_mm')}"
        return self.num(mm) + "″"

    def dims(self, *mm: float) -> str:
        return "×".join(self.num(v) for v in mm) + (f" {self.t('unit_mm')}" if self.units == "mm" else "″")

    def screw(self, d: float, length: float) -> str:
        """3.5×50 мм  или  #6 × 2″ — в дюймах как продаются в США."""
        if self.units == "mm":
            return f"{d:g}×{length:g}" + (f" {self.t('unit_mm')}" if self.lang == "ru" else " mm")
        gauge = {3.0: 4, 3.5: 6, 4.0: 8, 4.5: 9, 5.0: 10}.get(round(d * 2) / 2, 8)
        L = round(length / MM_PER_IN * 4) / 4
        return f"#{gauge} × {inches_str(L, 4)}″"

    def angle(self, deg: float) -> str:
        return f"{deg:g}°"

    def t(self, key: str, **kw) -> str:
        return t(key, self.lang, **kw)

    @property
    def unit_label(self) -> str:
        return self.t("unit_mm_long") if self.units == "mm" else self.t("unit_in_long")


def inches_str(x: float, denom: int = 16) -> str:
    """12.875 → '12 7/8', до 1/16 дюйма."""
    neg = x < 0
    x = abs(x)
    whole = int(x)
    frac = Fraction(round((x - whole) * denom), denom)
    if frac == 1:
        whole, frac = whole + 1, Fraction(0)
    s = str(whole) if frac == 0 else (f"{whole} {frac.numerator}/{frac.denominator}" if whole else
                                       f"{frac.numerator}/{frac.denominator}")
    return ("-" if neg else "") + s


# ---------- строки ----------

MESSAGES: dict[str, dict[str, str]] = {
    "ru": {
        "unit_mm": "мм", "unit_mm_long": "миллиметрах", "unit_in_long": "дюймах",
        # проверки
        "bad_json": "JSON не читается: строка {line}, столбец {col}: {msg}",
        "missing_field": "{where}: нет обязательного поля «{field}»",
        "bad_value": "{where}: некорректное значение поля «{field}»: {value}",
        "cut_degenerate": "{part}: рез задан совпадающими точками",
        "trim_degenerate": "{part}: плоскость trim задана точками на одной прямой",
        "part_empty": "{part}: после резов от детали ничего не осталось",
        "snap_unknown_target": "{part}: snap к неизвестной детали {target}",
        "snap_target_not_ready": "{part}: snap к {target}, которая ещё не встала на место — поставьте {target} в списке деталей раньше",
        "snap_miss": "{part}: при сдвиге не встречает {targets} — проверьте направление dir и примерное положение",
        "dup_ids": "Повторяющиеся id деталей: {ids}",
        "unknown_stock": "{part}: неизвестный материал «{stock}»",
        "thickness_mismatch": "{part}: толщина {t} не совпадает с толщиной материала {st}",
        "too_wide": "{part}: ширина {w} больше ширины доски {sw}",
        "too_long": "{part}: длина {l} больше длины доски {sl}",
        "sheet_too_small": "{part}: {w}×{l} не помещается в лист {sw}×{sl}",
        "hole_outside": "{part}: отверстие ⌀{d} выходит за край детали",
        "hole_near_edge": "{part}: отверстие ⌀{d} ближе {m} к краю — может расколоться",
        "overlap": "Детали {a} и {b} пересекаются (на {depth})",
        "gap": "Между {a} и {b} зазор {gap} — так задумано?",
        "disconnected": "Детали не касаются остальной конструкции: {parts}",
        "part_not_installed": "Деталь {part} ни разу не устанавливается в шагах сборки",
        "part_installed_twice": "Деталь {part} устанавливается несколько раз",
        "step_unknown_part": "Шаг «{step}»: неизвестная деталь {part}",
        "snap_edge_only": "{part}: после snap к {targets} касание только по ребру или точке — проверьте угол наклона и резы, плоскости должны совпадать",
        "step_no_fastener": "Шаг «{step}»: не нашлось, чем крепить новую деталь",
        "joint_glue_only": "Стык {a}–{b}: обе детали касаются торцами — саморез некуда вкрутить, только клей",
        "screw_near_edge": "Стык {a}–{b}: кромка {part} уже {m} — саморез может её расколоть; лучше шкант, конфирмат или только клей",
        "screw_clash": "Стык {a}–{b}: саморезу некуда встать — мешает саморез {c}→{d} внутри {part}, пропущен",
        "screw_in_hole": "Стык {a}–{b}: саморез попадает в отверстие «{hole}», пропущен",
        "screw_short_joint": "Стык {a}–{b}: площадка слишком узкая для самореза ({w}) — только клей",
        "screw_too_long": "Стык {a}–{b}: в {part} всего {t} материала — саморез вылезет насквозь, пропущен",
        "summary_ok": "OK: {parts} деталей, {steps} шагов",
        "error": "ОШИБКА", "warning": "Внимание",
        "not_built": "PDF не собран: сначала исправьте ошибки.",
        "pcs": "шт", "screw": "саморез",
        # PDF
        "difficulty": "Сложность", "time": "Время", "n_parts": "Деталей", "n_screws": "Саморезов",
        "buy": "Что купить", "tools": "Инструменты",
        "screws_line": "Саморезы по дереву {spec} — {n} шт (+ пару про запас)",
        "stock_line": "{name} — {n} шт",
        "parts_title": "Детали",
        "parts_sub": "Все размеры в {units}. Буква на детали совпадает с буквой в шагах сборки.",
        "thickness": "толщина {t}",
        "bevel_note": "скос {angles} — пунктир: обратная сторона",
        "cut_title": "Раскрой",
        "cut_sub": "Учтён пропил {kerf}. Сначала отпилите детали поперёк, потом распустите по ширине.",
        "stock_no": "№{n}",
        "screw_spec": "саморез {spec}",
        "glue": "клей ПВА", "glue_sub": "на все стыки",
        "screw_marks": "● — места саморезов",
        "screw_marks_hidden": "; ещё {n} с невидимой стороны",
        "screws_hidden_all": "Саморезы — с невидимой на рисунке стороны",
        "tips_title": "Важно",
        "continued": "(продолжение)",
        "safety_title": "Безопасность",
        "disclaimer": "Инструкция сгенерирована автоматически по 3D-модели. Перед распилом сверьте размеры с вашим материалом. Прочность конструкции не рассчитывается: за безопасность изготовления и использования отвечаете вы.",
        "safety_general": "Работайте в защитных очках, электроинструмент используйте по инструкции производителя. Держите пальцы подальше от линии реза.",
        "safety_load_bearing": "Несущая конструкция: прочность проверена только приблизительно. Не превышайте указанную нагрузку, при сомнениях усиливайте крепёж и берите материал толще.",
        "safety_children": "Для детей: скруглите углы и кромки, отшлифуйте всё до гладкости, утопите шляпки саморезов, используйте безопасные покрытия. Высокую мебель обязательно крепите к стене.",
        "safety_outdoor": "Для улицы: берите оцинкованный или нержавеющий крепёж и водостойкий клей (класс D3/D4).",
        "safety_wall_mount": "Крепление к стене: дюбели подбирайте под материал стены и вес, проверьте, что в месте сверления нет проводки и труб.",
    },
    "en": {
        "unit_mm": "mm", "unit_mm_long": "millimetres", "unit_in_long": "inches",
        "bad_json": "Invalid JSON: line {line}, column {col}: {msg}",
        "missing_field": "{where}: required field “{field}” is missing",
        "bad_value": "{where}: invalid value for “{field}”: {value}",
        "cut_degenerate": "{part}: cut is defined by coincident points",
        "trim_degenerate": "{part}: trim plane points are collinear",
        "part_empty": "{part}: nothing is left of the part after cuts",
        "snap_unknown_target": "{part}: snap to unknown part {target}",
        "snap_target_not_ready": "{part}: snap to {target}, which is not placed yet — list {target} earlier in parts",
        "snap_miss": "{part}: never meets {targets} when moved — check dir and the rough position",
        "dup_ids": "Duplicate part ids: {ids}",
        "unknown_stock": "{part}: unknown stock “{stock}”",
        "thickness_mismatch": "{part}: thickness {t} does not match stock thickness {st}",
        "too_wide": "{part}: width {w} exceeds board width {sw}",
        "too_long": "{part}: length {l} exceeds board length {sl}",
        "sheet_too_small": "{part}: {w}×{l} does not fit the sheet {sw}×{sl}",
        "hole_outside": "{part}: hole ⌀{d} runs past the edge",
        "hole_near_edge": "{part}: hole ⌀{d} is closer than {m} to the edge — may split",
        "overlap": "Parts {a} and {b} intersect (by {depth})",
        "gap": "Gap of {gap} between {a} and {b} — intended?",
        "disconnected": "Parts do not touch the rest of the build: {parts}",
        "part_not_installed": "Part {part} is never installed in the assembly steps",
        "part_installed_twice": "Part {part} is installed more than once",
        "step_unknown_part": "Step “{step}”: unknown part {part}",
        "snap_edge_only": "{part}: after snapping to {targets} it touches only along an edge or point — check the angle and cuts, the planes must coincide",
        "step_no_fastener": "Step “{step}”: nothing to fasten the new part with",
        "joint_glue_only": "Joint {a}–{b}: both parts meet end-to-end — no place for a screw, glue only",
        "screw_near_edge": "Joint {a}–{b}: the edge of {part} is narrower than {m} — a screw may split it; consider dowels, confirmat screws or glue only",
        "screw_clash": "Joint {a}–{b}: no room for a screw — it would hit screw {c}→{d} inside {part}, skipped",
        "screw_in_hole": "Joint {a}–{b}: a screw would run into the hole “{hole}”, skipped",
        "screw_short_joint": "Joint {a}–{b}: contact is too narrow for a screw ({w}) — glue only",
        "screw_too_long": "Joint {a}–{b}: only {t} of material in {part} — a screw would poke through, skipped",
        "summary_ok": "OK: {parts} parts, {steps} steps",
        "error": "ERROR", "warning": "Warning",
        "not_built": "PDF not built: fix the errors first.",
        "pcs": "pcs", "screw": "screw",
        "difficulty": "Difficulty", "time": "Time", "n_parts": "Parts", "n_screws": "Screws",
        "buy": "Shopping list", "tools": "Tools",
        "screws_line": "Wood screws {spec} — {n} pcs (+ a couple spare)",
        "stock_line": "{name} — {n} pcs",
        "parts_title": "Parts",
        "parts_sub": "All dimensions in {units}. Part letters match the letters in the assembly steps.",
        "thickness": "thickness {t}",
        "bevel_note": "bevel {angles} — dashed: the other face",
        "cut_title": "Cutting plan",
        "cut_sub": "Kerf of {kerf} included. Crosscut the parts first, then rip to width.",
        "stock_no": "#{n}",
        "screw_spec": "screw {spec}",
        "glue": "wood glue", "glue_sub": "on every joint",
        "screw_marks": "● — screw positions",
        "screw_marks_hidden": "; {n} more on the hidden side",
        "screws_hidden_all": "Screws go in from the side hidden in the picture",
        "tips_title": "Important",
        "continued": "(continued)",
        "safety_title": "Safety",
        "disclaimer": "These instructions were generated automatically from a 3D model. Check the dimensions against your material before cutting. Structural strength is not calculated: you are responsible for safe building and use.",
        "safety_general": "Wear safety glasses and follow the manufacturer's instructions for power tools. Keep fingers away from the cut line.",
        "safety_load_bearing": "Load-bearing build: strength is checked only roughly. Do not exceed the stated load; when in doubt, add fasteners or use thicker stock.",
        "safety_children": "For children: round over corners and edges, sand everything smooth, countersink screw heads, use child-safe finishes. Always anchor tall furniture to the wall.",
        "safety_outdoor": "Outdoors: use galvanized or stainless fasteners and waterproof (D3/D4, Type II) glue.",
        "safety_wall_mount": "Wall mounting: choose anchors for your wall type and the load, and check for wiring and pipes before drilling.",
    },
}


def t(key: str, lang: str = "ru", **kw) -> str:
    table = MESSAGES.get(lang, MESSAGES["en"])
    s = table.get(key) or MESSAGES["en"].get(key) or MESSAGES["ru"].get(key) or key
    try:
        return s.format(**kw)
    except (KeyError, IndexError):
        return s
