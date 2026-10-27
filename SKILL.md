---
name: diy-instructions
description: Turns a DIY woodworking idea (birdhouse, shelf, box, bench, stool, planter, shoe rack, doghouse, feeder, nightstand) into a printable step-by-step assembly PDF in the style of flat-pack furniture manuals — dimensioned part drawings, cut plan for boards/sheets, shopping list with screws, isometric pictures for every step, 1:1 print templates and a rough strength check. Supports sloped/gable roofs, sub-assemblies, metric and inches, Russian and English. Use when the user wants to build something from boards, plywood, OSB or chipboard and asks for an instruction, plan, drawing or cut list.
---

# DIY instructions: idea → model → PDF

You do not draw pictures or compute cut lists in your head. You write a **JSON model** of the
build; the `diyplan` engine builds the parts, validates the geometry, places screws, checks sag
and stability, plans the cutting and renders the PDF. Dimensions in the PDF are consistent as long
as the model passes `check`.

Reference: `references/model-format.md` (every field), `references/recipes.md` (how typical builds
are put together). Working examples: `examples/*.json` — `wall-shelf` (loads, wall hardware),
`stool` (point load, sheet sizes and prices), `shoe-rack` (chipboard, confirmat, support rail,
`fasten_to`), `workbench-in` (inches, sub-assemblies, mirrored frame), `birdhouse` and
`titmouse-house` (single and gable roofs). Read the one closest to the request before designing.

## Workflow

1. **Safety gate first** — before asking anything, check the request against "Do not build" below.
2. **Clarify in one message** (not an interrogation): what it is for and rough size; material the
   user can actually buy (board thickness×width×length, or sheet); tools (can they rip boards / cut
   angles?); for anything people sit on, stand on or load — the expected load. If the user is not
   available, pick sensible defaults and say which ones you picked.
3. **Design**: decide who covers whom at every joint (which part sits on the end of which), then
   write `model.json`. Prefer an order of steps where every new part attaches to what is already built.
4. **Check**: `diyplan check model.json --json` until `ok` is `true`. Treat warnings as real until
   you understand them — see "Reading warnings".
5. **Look at it**: `diyplan preview model.json -o preview/` writes the PDF and a PNG per page. Open the
   PNGs. If a new part is hidden, change the step's `view`; if a step is crowded, split it.
6. Hand over the PDF and say in two lines what to buy and anything you assumed.

Install once: `pip install -e <skill dir>` (needs only reportlab; PNG preview needs `pdftoppm`).
Without installing: `python -m diyplan ...` from the skill directory.

## Do not build

The engine checks geometry and gives only a rough sag estimate — it does not do structural design.
Do not produce instructions for things whose failure can seriously injure someone: ladders and step
stools taller than one step, swings, pull-up bars, climbing frames and slides, bunk beds and loft
beds, cribs and baby furniture, railings and guards, anything structural in a house (joists,
rafters, decks above ground, stairs). Say so in one or two sentences, suggest a proven plan or a
professional, and offer something adjacent you can do (a toy box, an under-bed drawer, a low bench).
A regular low bed, a bench, a stool and shelves are fine — with `load_bearing` and stated loads.
A stool people stand on is fine up to ~50 cm seat height (one step): give the top `load_kg: 150,
load_type: "point"` and a base at least as wide as the top. Anything taller to stand on is a ladder.

## Rules that keep the model honest

- Units: everything in the model (sizes, coordinates, kerf, holes) is in `units` — `mm` by default,
  `in` for US users (then use local names: 2×4, 3/4″ plywood). `lang` is `ru` or `en` and should match
  the language of all texts you write in the model.
- Each part starts as a blank `size: [dx, dy, dz]`; the **smallest** dimension is the thickness and
  must equal the stock thickness; for a board the middle one must fit the board width.
- Parts never overlap; a joint is two faces touching. If two parts "go into" each other, shorten one.
- Every structural joint needs one part touching the other with its **face** (that part gets the
  screws). Two parts meeting edge-to-edge or end-to-end cannot be screwed — redesign or accept glue.
- Boards laid side by side in one plane (a panel, a slatted seat, a wall of boards) are a *seam*,
  not a joint; that is fine as long as something across them holds them.
- Never compute rotated coordinates by hand: give a rough position, the tilt (`rotate`) and let
  `snap` drop the part into contact. Cut sloped tops with `trim` using the same plane points.
- State loads: `load_kg` on shelves/tops (`load_type: "point"` for seats and steps). Add the
  `safety` flags that apply: `load_bearing`, `children`, `outdoor`, `wall_mount`.
- Step text is short and practical, like a furniture manual. Do not repeat dimensions that the PDF
  already shows (parts page, position dimensions on steps).

## What the engine does for you

Screws (type, length ≈ 2.5× the thickness of the part they pass through, spacing, edge distance,
no collisions, no poke-through; confirmat screws into chipboard/MDF edges), shopping list including
screws and hardware, position dimensions on steps ("shelf: 262 mm up from the bottom of A"), zoom
callouts for joints, ghosting of parts that hide the new one, cut plan with board-length/sheet-size
choice and hints, material cost if prices are given, sag/stability report, 1:1 templates for shaped
cuts and large openings, safety page and disclaimer.

## Reading warnings

| code | meaning → what to do |
|---|---|
| `gap` | parts almost touch. Should touch → fix a size/origin. Gap intended → add the pair to `gaps_ok`. |
| `snap_edge_only` | tilt of the part ≠ tilt of the cut it rests on. Use identical rise/run or trim points. |
| `joint_glue_only` | end meets end; no screw possible. Make one part overlap the other, or `fasten_to` if intended. |
| `screw_clash` | two screws would meet inside a part. Shift one part 10–20 mm, or restrict with `fasten_to`. |
| `screw_too_long` | the receiving part is too thin there; screw from the other side or redesign. |
| `screw_short_joint` / `screw_near_edge` | edge too narrow for a screw (thin sheet edge) — redesign or glue. |
| `hole_blocked` | an opening is covered by a neighbouring part (drain hole over a foot). Move one. |
| `hole_near_edge`, `hole_overlap` | move openings apart / away from edges. |
| `sag_warn`, `sag_bad` | shelf will bow. Thicker stock, shorter span, or a support rail along the back. |
| `tip_over`, `anchor_children` | widen the base or anchor to the wall (`wall_mount` + hardware + a step). |
| `load_unspecified` | set `load_kg` on the loaded parts. |
| `text_too_long` | shorten the title/subtitle/step title. |
| `step_not_touching` | the new part floats: the message names the nearest part and the gap — fix origin/size. |
| `step_no_fastener` | the new part touches but nothing could be screwed — check who covers whom. |
| `load_not_checked` | a load is set but no supports were found — the part must rest on something or butt into uprights. |

## Limits (tell the user when you hit them)

Parts are convex: no grooves, tenons, L-shaped cut-outs or notches at an edge (build L-shapes from
two parts). Openings are through-holes inside a face (circle, rectangle, slot, arch). Fasteners are
screws and confirmat screws; hinges, drawer slides, brackets go to `extra_materials` / `hardware`
markers and the step text. No doors or drawers that move.
