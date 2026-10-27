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

    def screw(self, kind: str, d: float, length: float) -> str:
        """3.5×50 мм  или  #6 × 2″ — в дюймах как продаются в США. Конфирмат — всегда в мм."""
        if kind == "confirmat" or self.units == "mm":
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
        "hole_outside": "{part}: проём «{name}» выходит за край детали",
        "hole_overlap": "{part}: проёмы «{name}» и «{other}» сливаются или ближе 3 мм — между ними сломается перемычка",
        "hole_blocked": "{part}: проём «{name}» с другой стороны закрыт деталью {other} — сдвиньте одно из двух",
        "hole_near_edge": "{part}: проём «{name}» ближе {m} к краю — может расколоться",
        "overlap": "Детали {a} и {b} пересекаются (на {depth})",
        "gap": "Между {a} и {b} зазор {gap}. Должны касаться — поправьте размер или origin; зазор задуман — добавьте пару в gaps_ok",
        "disconnected": "Детали не касаются остальной конструкции: {parts}",
        "part_not_installed": "Деталь {part} ни разу не устанавливается в шагах сборки",
        "part_installed_twice": "Деталь {part} устанавливается несколько раз",
        "step_unknown_part": "Шаг «{step}»: неизвестная деталь {part}",
        "snap_edge_only": "{part}: после snap к {targets} касание только по ребру или точке — проверьте угол наклона и резы, плоскости должны совпадать",
        "step_no_fastener": "Шаг «{step}»: не нашлось, чем крепить новую деталь",
        "joint_glue_only": "Стык {a}–{b}: обе детали касаются торцами — саморез некуда вкрутить. Нужен крепёж — перестройте узел, чтобы одна деталь накрывала другую; так и задумано — добавьте fasten_to",
        "screw_near_edge": "Стык {a}–{b}: кромка {part} уже {m} — саморез может её расколоть; лучше шкант, конфирмат или только клей",
        "screw_clash": "Стык {a}–{b}: саморезу некуда встать — мешает саморез {c}→{d} внутри {part}, пропущен. В углах это нормально; если крепежа стало мало — сдвиньте деталь на 10–20 мм или ограничьте пары через fasten_to",
        "screw_in_hole": "Стык {a}–{b}: саморез попадает в отверстие «{hole}», пропущен",
        "screw_short_joint": "Стык {a}–{b}: площадка слишком узкая для самореза ({w}) — только клей",
        "screw_too_long": "Стык {a}–{b}: в {part} всего {t} материала — саморез вылезет насквозь, пропущен",
        "sag_warn": "{part}: при нагрузке {kg} кг прогиб {sag} на пролёте {span} — заметно на глаз (лучше до {lim}). Возьмите материал толще, сократите пролёт или добавьте опору посередине",
        "sag_bad": "{part}: при нагрузке {kg} кг прогиб {sag} на пролёте {span} — деталь заметно прогнётся. Нужен материал толще, пролёт короче или опора посередине",
        "load_unspecified": "Нагрузка нигде не задана — посчитано как книги, {kgm} кг на метр. Для сиденья, ступеньки, столешницы укажите load_kg и load_type: \"point\"",
        "unstable": "Конструкция опрокинется сама: центр масс за пределами опоры",
        "tip_over": "Опрокинется от лёгкого толчка (угол {deg}°): расширьте основание или крепите к стене (флаг wall_mount и шаг крепления)",
        "anchor_children": "Детская мебель высотой {h}: обязательно крепите к стене — добавьте фурнитуру крепления и шаг про это",
        "attach_unknown": "Шаг attach ссылается на узел «{group}», которого нет (нет шагов с таким group)",
        "group_not_attached": "Узел «{group}» собран, но ни один шаг attach не ставит его на место",
        "same_as": "Так же, как в шаге {n}",
        "times": "×{n}",
        "subassembly": "Узел — соберите отдельно на столе",
        "summary_ok": "OK: {parts} деталей, {steps} шагов",
        "error": "ОШИБКА", "warning": "Внимание",
        "not_built": "PDF не собран: сначала исправьте ошибки.",
        "pcs": "шт", "screw": "саморез", "confirmat": "конфирмат",
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
        "cut_sub_kerf": "Учтён пропил {kerf}.",
        "cut_offcut": "{stock} №{n} заполнен на {pct}% — в магазине хватит куска {size}",
        "cut_tight": "{stock}: если укоротить каждую деталь на {mm}, хватит {n} шт. — на одну меньше",
        "budget": "Материалы",
        "tpl_title": "Шаблон 1:1 — {name}",
        "tpl_tile": "лист {k} из {n} (ряд {row}, колонка {col})",
        "tpl_print": "Печатайте в масштабе 100 % (не «по размеру страницы») и проверьте линейкой отрезок справа. Сплошная линия — край детали, пунктир — деталь продолжается. Листы склеивайте по голубой полосе.",
        "tpl_origin": "Координаты — от левого нижнего угла детали, как на чертеже деталей.",
        "tpl_hole_only": "Отметьте центр проёма на детали по координатам, совместите с ним перекрестье шаблона и обведите контур.",
        "cut_sub_board": "Отпилите детали поперёк доски.",
        "cut_sub_rip": "Сначала отпилите детали поперёк, потом распустите по ширине те, что уже доски.",
        "cut_sub_sheet": "Лист удобнее всего распилить в магазине — покажите эту схему.",
        "stock_no": "№{n}",
        "screw_spec": "саморез {spec}",
        "confirmat_spec": "конфирмат {spec}",
        "confirmat_line": "Конфирматы {spec} — {n} шт (+ ступенчатое сверло под конфирмат)",
        "glue": "клей ПВА", "glue_sub": "на все стыки",
        "screw_marks": "● — места саморезов; ",
        "screw_marks_back": "○ — вход с обратной стороны",
        "zoom_edge": "от края {m}",
        "pos_z": "{p}: {d} от низа {q}",
        "pos_y": "{p}: {d} от передней кромки {q}",
        "pos_x": "{p}: {d} от левой кромки {q}",
        "tips_title": "Важно",
        "continued": "(продолжение)",
        "safety_title": "Безопасность",
        "disclaimer": "Инструкция сгенерирована автоматически по 3D-модели. Перед распилом сверьте размеры с вашим материалом. Прочность конструкции не рассчитывается: за безопасность изготовления и использования отвечаете вы.",
        "safety_general": "Работайте в защитных очках, электроинструмент используйте по инструкции производителя. Держите пальцы подальше от линии реза.",
        "safety_load_bearing": "Несущая конструкция: прочность проверена только приблизительной оценкой прогиба. Не нагружайте сильнее расчётного, при сомнениях усиливайте крепёж и берите материал толще.",
        "loads_title": "Расчётные нагрузки",
        "load_line": "{name} ({letter}): {kg} кг {how} — прогиб около {sag} на пролёте {span}",
        "load_uniform": "равномерно", "load_point": "в центре (сели/встали)",
        "load_default_note": "Для полок без указанной нагрузки принято {kgm} кг на метр — как книги.",
        "stability_line": "Устойчивость: опрокинется при наклоне примерно на {deg}°.",
        "safety_children": "Для детей: скруглите углы и кромки, отшлифуйте всё до гладкости, утопите шляпки саморезов, используйте безопасные покрытия. Высокую мебель обязательно крепите к стене.",
        "safety_outdoor": "Для улицы: берите оцинкованный или нержавеющий крепёж и водостойкий клей (класс D3/D4).",
        "safety_outdoor_noglue": "Для улицы: берите оцинкованный или нержавеющий крепёж — обычный заржавеет.",
        "text_too_long": "Поле {field} не влезает в вёрстку (больше {max} строк) — сократите, иначе текст обрежется",
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
        "hole_outside": "{part}: opening “{name}” runs past the edge",
        "hole_overlap": "{part}: openings “{name}” and “{other}” merge or are closer than 3 mm — the bridge between them will break",
        "hole_blocked": "{part}: opening “{name}” is covered by {other} on the other side — move one of them",
        "hole_near_edge": "{part}: opening “{name}” is closer than {m} to the edge — may split",
        "overlap": "Parts {a} and {b} intersect (by {depth})",
        "gap": "Gap of {gap} between {a} and {b}. If they should touch, fix a size or origin; if the gap is intended, add the pair to gaps_ok",
        "disconnected": "Parts do not touch the rest of the build: {parts}",
        "part_not_installed": "Part {part} is never installed in the assembly steps",
        "part_installed_twice": "Part {part} is installed more than once",
        "step_unknown_part": "Step “{step}”: unknown part {part}",
        "snap_edge_only": "{part}: after snapping to {targets} it touches only along an edge or point — check the angle and cuts, the planes must coincide",
        "step_no_fastener": "Step “{step}”: nothing to fasten the new part with",
        "joint_glue_only": "Joint {a}–{b}: both parts meet end-to-end — no place for a screw. If it needs fastening, rework it so one part overlaps the other; if intended, add fasten_to",
        "screw_near_edge": "Joint {a}–{b}: the edge of {part} is narrower than {m} — a screw may split it; consider dowels, confirmat screws or glue only",
        "screw_clash": "Joint {a}–{b}: no room for a screw — it would hit screw {c}→{d} inside {part}, skipped. Normal at corners; if too few fasteners remain, shift a part by 10–20 mm or restrict pairs with fasten_to",
        "screw_in_hole": "Joint {a}–{b}: a screw would run into the hole “{hole}”, skipped",
        "screw_short_joint": "Joint {a}–{b}: contact is too narrow for a screw ({w}) — glue only",
        "screw_too_long": "Joint {a}–{b}: only {t} of material in {part} — a screw would poke through, skipped",
        "sag_warn": "{part}: under {kg} kg it sags {sag} over a {span} span — visible (aim for under {lim}). Use thicker stock, shorten the span or add a middle support",
        "sag_bad": "{part}: under {kg} kg it sags {sag} over a {span} span — it will visibly bow. Use thicker stock, a shorter span or a middle support",
        "load_unspecified": "No load is set anywhere — assumed books, {kgm} kg per metre. For a seat, step or worktop set load_kg and load_type: \"point\"",
        "unstable": "The build tips over on its own: centre of mass is outside the footprint",
        "tip_over": "Tips over with a light push (angle {deg}°): widen the base or anchor it to the wall (wall_mount flag and an anchoring step)",
        "anchor_children": "Children's furniture {h} tall: it must be anchored to the wall — add anchoring hardware and a step for it",
        "attach_unknown": "attach step refers to sub-assembly “{group}”, which does not exist (no steps with that group)",
        "group_not_attached": "Sub-assembly “{group}” is built but no attach step puts it in place",
        "same_as": "Same as in step {n}",
        "times": "×{n}",
        "subassembly": "Sub-assembly — build it separately on the bench",
        "summary_ok": "OK: {parts} parts, {steps} steps",
        "error": "ERROR", "warning": "Warning",
        "not_built": "PDF not built: fix the errors first.",
        "pcs": "pcs", "screw": "screw", "confirmat": "confirmat",
        "difficulty": "Difficulty", "time": "Time", "n_parts": "Parts", "n_screws": "Screws",
        "buy": "Shopping list", "tools": "Tools",
        "screws_line": "Wood screws {spec} — {n} pcs (+ a couple spare)",
        "stock_line": "{name} — {n} pcs",
        "parts_title": "Parts",
        "parts_sub": "All dimensions in {units}. Part letters match the letters in the assembly steps.",
        "thickness": "thickness {t}",
        "bevel_note": "bevel {angles} — dashed: the other face",
        "cut_title": "Cutting plan",
        "cut_sub_kerf": "Kerf of {kerf} included.",
        "cut_offcut": "{stock} #{n} is only {pct}% used — an offcut of {size} is enough",
        "cut_tight": "{stock}: shorten every part by {mm} and {n} will do — one fewer",
        "budget": "Materials",
        "tpl_title": "1:1 template — {name}",
        "tpl_tile": "sheet {k} of {n} (row {row}, column {col})",
        "tpl_print": "Print at 100 % (not “fit to page”) and check the ruler bar on the right. Solid line is the part edge, dashed means the part continues. Tape sheets together along the blue strip.",
        "tpl_origin": "Coordinates are from the bottom-left corner of the part, as on the parts page.",
        "tpl_hole_only": "Mark the opening centre on the part using the coordinates, line up the template crosshair with it and trace the outline.",
        "cut_sub_board": "Crosscut the parts from the board.",
        "cut_sub_rip": "Crosscut the parts first, then rip the narrower ones to width.",
        "cut_sub_sheet": "Easiest is to have the store cut the sheet — show them this layout.",
        "stock_no": "#{n}",
        "screw_spec": "screw {spec}",
        "confirmat_spec": "confirmat {spec}",
        "confirmat_line": "Confirmat screws {spec} — {n} pcs (+ a stepped confirmat drill bit)",
        "glue": "wood glue", "glue_sub": "on every joint",
        "screw_marks": "● — screw positions; ",
        "screw_marks_back": "○ — driven from the back side",
        "zoom_edge": "{m} from edge",
        "pos_z": "{p}: {d} up from the bottom of {q}",
        "pos_y": "{p}: {d} back from the front edge of {q}",
        "pos_x": "{p}: {d} in from the left edge of {q}",
        "tips_title": "Important",
        "continued": "(continued)",
        "safety_title": "Safety",
        "disclaimer": "These instructions were generated automatically from a 3D model. Check the dimensions against your material before cutting. Structural strength is not calculated: you are responsible for safe building and use.",
        "safety_general": "Wear safety glasses and follow the manufacturer's instructions for power tools. Keep fingers away from the cut line.",
        "safety_load_bearing": "Load-bearing build: strength is only roughly estimated from shelf sag. Do not load it beyond the figures below; when in doubt, add fasteners or use thicker stock.",
        "loads_title": "Design loads",
        "load_line": "{name} ({letter}): {kg} kg {how} — sag about {sag} over a {span} span",
        "load_uniform": "spread evenly", "load_point": "at the centre (sitting/standing)",
        "load_default_note": "Shelves without a stated load assume {kgm} kg per metre — like books.",
        "stability_line": "Stability: tips over when leaned about {deg}°.",
        "safety_children": "For children: round over corners and edges, sand everything smooth, countersink screw heads, use child-safe finishes. Always anchor tall furniture to the wall.",
        "safety_outdoor": "Outdoors: use galvanized or stainless fasteners and waterproof (D3/D4, Type II) glue.",
        "safety_outdoor_noglue": "Outdoors: use galvanized or stainless fasteners — plain steel will rust.",
        "text_too_long": "Field {field} does not fit the layout (more than {max} lines) — shorten it or it will be cut",
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
