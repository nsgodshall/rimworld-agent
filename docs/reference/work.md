# Work, skills, research and recreation

## Work priorities

- Two modes: **simple** (each work type on or off; on = 3) and **manual** (1 highest … 4 lowest). RimMCP's
  `set_pawn_work_priority` with 0 or 3 keeps simple mode; any other value switches the colony to manual.
- Within one priority, pawns do work types in their **natural order** (left to right in the Work tab):
  Firefight, Patient, Doctor, Bed rest, Basic, Warden, Handle, Cook, Hunt, Construct, Grow, Mine, Plant cut,
  Smith, Tailor, Art, Craft, Haul, Clean, Research.
- Starting colonists come with work they're poor at **switched off**. Turn on everything a colonist is
  capable of: idle is worse than unskilled (this project's `managers/work.py`). The wiki's advice: "a colonist
  is better off researching than being idle; you can't fail research."
- **Incapable** work (from backstory or traits, e.g. a colonist who can't haul or clean) is disabled for good:
  `list_work detail=normal` → `work[].disabled`. Plan around it.
- Wiki's manual-priority starter (for when manual mode is worth it): Firefight, Patient, Bed rest, Basic = 1
  for everyone; Doctor, Warden, Cook, Construct, Grow = 1 for the best at each; passions = 2; the rest 4.

## Skills and passions

- Skills 0–20. Doing work raises the skill; skills above 10 decay slowly without practice.
- **Passion** (minor or major) for a skill: faster learning and **mood gain while doing that work**. Put
  colonists on what they're passionate about.
- Key early thresholds (approximate): Cooking ≥ 6 for fine meals; Construction low skill still builds wood,
  but quality is lower; Medical matters most: the best doctor tends.

## Research (early order, temperate)

- Needs a research bench (`SimpleResearchBench`, 3×2) and a colonist with Intellectual enabled.
- Useful early projects (defNames: verify with `get_research`):
  - **Battery**, **Solar panel**: steady power (wiki's first pick once there's a generator).
  - **Complex furniture**: billiards and poker tables, more furniture.
  - **Stonecutting**: stone blocks for fireproof walls.
  - **Microelectronics basics**: comms console (trading), then more.
  - **Pemmican / packaged food**, **hydroponics** later.
- Research speed scales with Intellectual skill; anyone researching beats nobody.

## Recreation

- Recreation need falls during the day; colonists fill it in their free time (schedule "Anything" or
  "Recreation" hours).
- **Tolerance**: each activity type gets boring after use (bored past 50%, recovers below 30%). Several
  *types* are needed. Wealthier colonies need more variety.
- Bands: starved (0%) −20 · deprived −10 · unfulfilled −5 · satisfied (70%+) +5 · fully (85%+) +10.
- Early sources:
  - No building: **skygazing, walking** (outdoors; "meditative" type), **socialising** at a table.
  - `HorseshoesPin`: 1×1, 10 steel (or other metal), no research; dexterity type. **Build one first.**
  - `ChessTable`: 1×1, 70 wood, available in this game without research; cerebral type, 2 players.
  - `HoopstoneRing`, `GameOfUrBoard`: not available here yet (research or DLC).
  - Later: billiards (complex furniture), TV (research), telescope.
- Put recreation in the dining room so one decent room gives both "dining room" and "rec room" bonuses.

## Schedules

- Default: sleep 22:00–06:00, the rest "Anything". Night owls want the opposite. A recreation hour in the
  evening helps keep recreation up when work is plentiful.
