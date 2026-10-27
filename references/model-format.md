# Model format reference

All lengths are in the model's `units` (`mm` default, or `in`). Axes: **x** left→right,
**y** front→back (the front face is at y = 0), **z** up. Angles in degrees.

## Top level

```json
{
  "title": "Скворечник",                 // required; fits 1 line at 34 pt or 2 lines at 22 pt
  "subtitle": "One or two lines",
  "lang": "ru",                          // ru | en — labels in the PDF; write all texts in this language
  "units": "mm",                         // mm | in — units of the WHOLE model, including kerf
  "difficulty": "Лёгкая",                // short: fits a small chip on the cover
  "time": "2–3 часа",
  "kerf": 3,                             // saw kerf for the cut plan
  "currency": "₽",                       // shown with prices if stock has prices
  "safety": ["outdoor"],                 // load_bearing | children | outdoor | wall_mount
  "fastener": "auto",                    // auto | screw | confirmat (auto: confirmat into chipboard/MDF edges)
  "gaps_ok": [["seat_a", "seat_b"]],     // pairs whose small gap is intentional
  "cover_view": "front-right",           // front-right | front-left | back-right | back-left
  "templates": true,                     // true (auto) | false | ["part_id", …] — 1:1 print templates
  "stock": [ … ],
  "parts": [ … ],                        // required
  "steps": [ … ],                        // required
  "tools": ["Ножовка", "Шуруповёрт"],
  "extra_materials": ["Клей ПВА"],       // screws and hardware markers are added automatically
  "tips": ["Important things in one or two sentences each"],
  "disclaimer": "optional extra text above the standard disclaimer"
}
```

## Stock

```json
{"id": "b20", "kind": "board", "name": "Доска строганая, сосна", "thickness": 20, "width": 200, "length": 3000,
 "price": 450, "options": [{"length": 2000, "price": 320}, {"length": 6000, "price": 850}]}
{"id": "ply18", "kind": "sheet", "name": "Фанера ФК 18 мм", "thickness": 18, "width": 1525, "length": 1525,
 "price": 2900, "options": [{"width": 760, "length": 1525, "price": 1600}], "grain": false}
```

- `kind: "board"` — any thickness: 20–25 mm boards, 30–50 mm planks, 40×40 / 50×50 bars (a bar is a
  board whose thickness equals its width). Board parts are crosscut from the length; parts narrower
  than the board are ripped.
- `kind: "sheet"` — plywood, OSB, chipboard (ЛДСП), MDF. Common sizes: plywood 1525×1525, 1220×2440;
  OSB 1250×2500; chipboard 2750×1830, 2800×2070. 2D cut plan; parts may rotate unless `grain: true`.
- `options` — other lengths / sheet sizes the shop sells. The cut plan picks the cheapest mix
  (or least material if no prices). Validation uses the largest option.
- `material` — `pine | spruce | oak | birch | beech | plywood | osb | mdf | chipboard`. Optional:
  guessed from the name. Used for sag (stiffness, creep) and for choosing confirmat screws.

## Part

```json
{"id": "front", "name": "Передняя стенка", "stock": "b20",
 "size": [180, 20, 330], "origin": [0, 0, 0],
 "cuts": [{"from": [0, 220], "to": [70, 290]}],
 "rotate": {"axis": "x", "rise": -40, "run": 180},
 "trim": [{"through": [[0, 0, 330], [180, 0, 330], [0, 180, 290]]}],
 "snap": [{"to": ["side_l", "side_r"], "dir": [0, 0, -1]}],
 "holes": [{"d": 50, "at": [90, 260], "name": "Леток"},
           {"shape": "rect", "w": 120, "h": 30, "at": [90, 60], "name": "Ручка"},
           {"d": 8, "at": [40, 40], "repeat": {"n": 5, "step": [50, 0]}, "name": "Дренаж"}],
 "hardware": [{"name": "Крючок", "at": [60, 70], "side": "-t", "repeat": {"n": 4, "step": [150, 0]}}],
 "load_kg": 20, "load_type": "uniform",
 "removable": false, "fasten_to": ["side_l", "side_r"]}
```

- `size` — the blank. Smallest value = thickness (= stock thickness). The two others are the
  **face axes** in x→y→z order; all 2D coordinates of the part (`cuts`, `holes`, `hardware`) are in
  these face axes, measured from the blank's corner `[0, 0]`. Example: `size [180, 20, 330]` → face
  axes are (x, z) → `at: [90, 260]` means 90 along x, 260 up.
- `origin` — where the blank corner `[0,0,0]` goes (after `rotate`).
- `cuts` — straight cut across the face through two points; keeps the side with the blank centre
  (or `keep: [u, v]`). Gables, trapezoids, clipped corners.
- `rotate` — tilt: positive `deg` raises the +axis end (`x`: the far +y end goes up; `y`: the right
  +x end goes up; `z`: turn in plan, counter-clockwise from above). `rise`/`run` instead of `deg`.
  A list applies in order.
- `trim` — cut by a world plane through 3 points; keeps the side with the part centre (or `keep`).
  Use the same three points for every part that must meet one roof plane.
- `snap` — move along `dir` until touching any of `to`. Targets must be earlier in `parts`.
  A list snaps in sequence (drop onto gables, then slide along the slope to the ridge).
- `holes` — through openings: `d` (circle) or `shape: rect | slot | arch` with `w`, `h`;
  `at` is the centre (for an arch: the centre of its bounding box). `repeat` makes a row.
  Small round holes (< 40 mm) are drilled from coordinates; shaped and large ones get a 1:1 template.
- `hardware` — markers for hooks, eye screws, wall-mount points: shown on steps and drawings,
  counted in the shopping list. `side` is the face: `-t` or `+t` (the faces at 0 and at full thickness).
- `load_kg`, `load_type` — design load for sag: `uniform` (books, shoes) or `point` (a person sitting).
- `removable` — fastened with two screws per joint, no glue (lids, cleanable floors).
- `fasten_to` — screw this part only to the listed parts; other touches are not fastened.
- `note` — free text kept with the part.

## Step

```json
{"title": "Полка", "add": ["shelf"], "glue": true, "view": "front-left", "text": "…"}
{"title": "Леток", "focus": ["front"], "text": "…"}
{"title": "Лежанка", "group": "bed", "add": ["lid", "rim_l", "rim_r"], "text": "…"}
{"title": "Лежанку на домик", "attach": "bed", "text": "…"}
{"title": "Вторая рама", "group": "frame_r", "add": ["leg_c", "leg_d", "rail_b"], "times": 1, "same_as": 2}
```

- `add` — parts installed in this step. Every part is installed exactly once over all steps.
- `focus` — a preparation step (cut, drill, mark): shows a large dimensioned drawing of these
  parts. It does **not** install them.
- `view` — camera: `front-right` (default), `front-left`, `back-right`, `back-left`.
- `glue` — glue icon.
- `group` — the step builds a separate sub-assembly on the bench (only its parts are drawn).
  `attach: "<group>"` puts the finished sub-assembly onto the main build; screws between the group
  and the main build are placed there.
- `times` — shows a ×N badge ("make N of these"). `same_as` — "same as in step N" (1-based).

## CLI

```
diyplan check model.json [--json] [--lang en] [--units in]
diyplan build model.json -o out.pdf [--force]
diyplan preview model.json -o dir/          # PDF + PNG of every page
```

`check --json` → `{"ok", "issues": [{"level", "code", "parts", "message"}], "summary": {"parts",
"steps", "stock", "screws", "loads", "stability", "cut_hints", "materials_cost", "sheets_used_pct"}}`.
