# Rooms and shelter

## What counts as a room, and as indoors

- A **room** is a region fully enclosed by walls, doors (and other wall-like buildings). A gap anywhere makes
  it part of the outdoors. Diagonal gaps don't leak.
- **Roofs build themselves** over enclosed rooms (the game marks them for building roof; colonists with
  Construction build it). Verified in this game: a 7×6 wooden room got all 42 cells roofed within hours.
  Detect: `get_map_view ... layers=["roof"]` → `layers.roof.rows` (`b` built roof, `-` none).
- **Roofs need support**: a wall, door or similar within 6 tiles. Removing walls can drop roofs on pawns.
- Three different "outdoors" tests:
  - *Temperature and deterioration* use outdoor temperature if **≥ 25% of the room is unroofed** or it's open
    to the map edge.
  - *Psychologically outdoors* (beauty, skygazing, "Slept outside") if **≥ 300 unroofed tiles**, or open to the
    map edge and ≥ 50% unroofed.
  - *Outdoors for work* (some buildings' stats) if > 25% unroofed or > 100 unroofed tiles.
- **"Slept outside" (−4)** comes from sleeping in an outdoor space *or an incomplete room*: every wall and the
  door must be built, and the roof finished.

## Bedroom vs barracks (the biggest room decision)

- A room with beds owned by **one colonist** (or a couple sharing a bed) is a **bedroom**; two or more
  colonists' beds in one room make it a **barracks**.
- Same impressiveness, barracks is **5 lower** (4 lower from "very impressive" up):

| Impressiveness | < 20 awful | 20–30 dull | 30–40 mediocre | 40–50 decent | 50–65 slightly | 65–85 somewhat/impressive | 85–120 very |
|---|---|---|---|---|---|---|---|
| Bedroom | −2 | 0 | +1 | +2 | +3 | +4 | +5 |
| Barracks | −7 | −5 | −4 | −3 | −2 | −1 | +1 |

- **Rule: one bedroom per colonist.** A barracks of three at "dull" costs each colonist 5; three tiny
  bedrooms at "mediocre" give each +1. A 6-point swing per colonist for a few extra walls.
- Bed ownership: `assign_owner <bedId> pawnId=...` (repeats are `alreadySatisfied`). Nothing in RimMCP lists
  owners; keep your own record.

## Impressiveness, space, beauty, cleanliness

- **Impressiveness** combines wealth, beauty, space and cleanliness, and is capped by size: small rooms
  struggle to get past "slightly impressive". Early targets: bedroom ≥ 30 (mediocre), dining/rec room ≥ 40
  (decent, +2 for eating and +2 for recreation there).
- **Space** = 1.4 × tiles, minus 0.9 per tile something impassable or a bed covers:

| Space | < 12.5 cramped | 12.5–29 rather tight | 29–55 average | 55–70 somewhat spacious | 70–130 quite | 130+ very |
|---|---|---|---|---|---|---|
| Rough interior | 3×4 or less | 3×6, 4×5 | 4×7, 5×6 | | | |

  Cramped rooms drag impressiveness down and feed the "Cramped interior" (−5) need. **A 4×4 interior
  bedroom** (16 tiles, a bed and an end table) is "rather tight" and a good early size; 3×3 is cramped.
- **Beauty** (room average): floors help (wood floor beats bare soil), plants and sculptures help; **dirt,
  blood, corpses, ugly buildings hurt**. Barricades are beauty −3 each: keep them away from rooms people use.
- **Cleanliness**: floors can be cleaned, soil can't. Cooking in a dirty room causes food poisoning.
- **Wealth**: furniture quality and material. Wooden things are cheap; that's fine early.

## Layout templates (early, wood, temperate)

All coordinates are interior cells; walls go around. Doors are 1 tile in a wall; rooms can share walls.

- **Bedroom row**: N bedrooms, each 4 wide × 4 deep interior, sharing walls, doors all on one side opening
  onto a corridor or the dining room. Outer size for N rooms: (5N + 1) × 6. Bed against the back wall.
  For 3 colonists: 16 × 6 outer, 3 doors, 3 beds. About 40 walls (200 wood) + 3 doors (75 wood).
- **Dining + rec room**: about 6×6 interior: a 2×2 table (`Table2x2c`, 4 seats) with `DiningChair`s,
  a `HorseshoesPin`, later a `ChessTable`; a `TorchLamp` if dark; wood floor when affordable.
  Adjacent to the kitchen and the bedroom corridor.
- **Kitchen**: stove (`FueledStove`, 3×1, 80 steel) and butcher table (`TableButcher`, 3×1) in their own
  room with a floor, next to food storage; keeps cooking clean.
- **Storage**: a roofed room for the stockpile (deterioration stops under a roof). Food lasts much longer
  below 0 °C: a freezer needs a cooler, so power. Early: a roofed room; meals and raw crops still spoil, so
  keep stock to a few days and cook to order.

## Temperature

- Comfortable for most pawns is about **16–26 °C** (clothes widen it). Bedrooms outside it give
  "Slept in the cold/heat" (−4); far outside causes hypothermia or heatstroke.
- Heat: `Campfire` (wood fuel, no research, also cooks) or `Heater` (power; 50 steel + 1 component).
  Cool: `PassiveCooler` (wood; no power) or a cooler (power).
- Doors leak heat when opened; walls insulate. A room of wood walls with one door holds heat well.
- Detect: `get_environment` (room temperature and openRoofCells by room), `get_colony_status` environment.
