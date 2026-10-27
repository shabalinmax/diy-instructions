# Recipes

Sketches of how common builds go together. Coordinates are examples in mm.

## Box / case (box, planter, toolbox, nightstand carcass)

- Decide one rule and keep it: **long sides cover the ends** (long sides run full length, ends sit
  between them), or the opposite. Never both at one corner.
- Bottom between the four walls (screwed through the walls into the bottom's edges) or under them
  (screwed through the bottom into the walls' edges). For a cleanable bottom: `removable: true`.
- Carcass from sheet (nightstand, shoe rack): sides full height; bottom, shelves and top between
  the sides; a plinth set back 30–50 mm from the front; a back rail or back panel against racking.
  The engine prints shelf heights and set-backs on the steps — you don't need them in the text.
- Chipboard/MDF: the engine switches to confirmat screws into edges; mention a stepped drill.

## Shelves

- Shelf between two sides, screwed through the sides. Span over ~600 mm in 16–18 mm sheet or
  ~800 mm in 20 mm pine will sag under books — add a rail under the back edge (`fasten_to` the
  sides only, so the shelf just rests on it) or shorten the span. Always set `load_kg`.
- Wall shelf: back board between the sides or behind the bottom; `wall_mount` flag; `hardware`
  markers for the wall screws on the back; a last step "fix to the wall" with `focus` on the back.

## Bench / stool / low table

- Legs or side panels at least as wide as ~60 % of the seat depth; a stretcher low between the
  legs and aprons under the seat stop racking.
- Seat `load_kg: 120, load_type: "point"`; flag `load_bearing`.
- Seat of several boards side by side is fine (seam); each board is screwed into the aprons/legs.
- A stool to stand on (≤ 50 cm): top `load_kg: 150, load_type: "point"`; base footprint at least
  as large as the top; stretchers low between the legs.

## Media unit / TV stand / chest of drawers-like carcasses

- Long top over a divider: the divider is a middle support — the engine splits the span.
- Anything with a TV on it or taller than ~60 cm in a home with children: `wall_mount` flag, an
  anti-tip strap or bracket as `hardware` on the back rail, and a final step to fix it.

## Feeders and hanging builds

- A floor with a low rim (raised edge strips, `fasten_to` the floor only), corner posts or two
  sides, a roof; leave it open on at least two sides.
- Hanging points (eye screws) as `hardware` on the roof or sides with `side` facing up/out, and
  the rope/wire in `extra_materials`. A last step "hang it" can be text-only on the roof step.

## Frames from boards (raised bed, garden box)

- Boards stacked edge to edge form a wall (seams). Corner posts (40×40, 50×50) inside the corners
  carry the screws; a middle post on long walls stops them bowing.

## Roofs

- **Single slope**: give every wall the same `trim` (three points of the roof plane); the roof is a
  blank with `rotate` of the same `rise`/`run` and `snap` down onto the walls. Overhang is just a
  bigger blank.
- **Gable 45°**: gables use `cuts` for both top corners; side walls `trim` along the slope; the long
  slope `rotate −45` + `snap` down, extended past the ridge by one board thickness; the short slope
  `rotate +45` + `snap` down, then `snap` along `[1, 0, 1]` to butt into the long one. Fasten the
  roof to the gables (`fasten_to`), because screws into a 45°-bevelled side top poke through.
- **Gable at another angle**: trim both slopes with a vertical plane at the ridge — a glued butt joint.

## Houses for animals and birds

- Entry holes: birds — round (titmouse 28–32 mm, starling 45–50 mm); pets — `arch` or large circle,
  raised above the floor by 50–100 mm so bedding stays in.
- No paint inside, no perch under a bird house entrance; a removable roof or floor for cleaning.
- Mark `outdoor`.

## Step order

- Start from a part that defines the build (bottom, a side), add neighbours one by one, so each
  new part touches something already standing.
- Build sub-assemblies (`group`) when people really do that on a bench: a seat frame, a lid with
  rims, two identical end frames (`times`, `same_as`).
- Put drilling/cutting of shaped parts in their own `focus` step before assembly.
