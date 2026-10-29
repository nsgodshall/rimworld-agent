# Early-game playbook

What a healthy colony has done by each point, as checks code can run. Priorities first; within a day, top to
bottom. Each item names the reference file with the detail.

## Hour 0 (landing)

- [ ] **Unforbid everything** useful near the landing site: food, medicine, weapons, steel, wood, components.
- [ ] **Arm**: best shooter takes the rifle, next the revolver, the brawler the knife. Helmet on anyone; flak
      armour slows movement, optional.
- [ ] **Work**: every capable work type on (work.md). Idle colonists are the most common early waste.
- [ ] **Stockpile** zone near the chosen base site (it stays put; later buildings orient on it).
- [ ] **Fields**: 25–40 rice tiles per colonist on the richest soil near the base (food.md).
- [ ] **Chop wood**: walls, doors, beds and furniture for three colonists take ~600 wood.

## Day 1 (before the first night)

- [ ] **Everyone sleeps indoors in a bed.** Quickest: one room. Better, for barely more wood: **one bedroom each**
      (rooms.md). A shared room is a barracks: −3 to −7 mood each, every night.
- [ ] Stockpile under a roof, or a storage room, so nothing deteriorates.
- [ ] A **table and chairs** (removes "Ate without table" −3), ideally inside a room.
- [ ] A **cooking station** (campfire at once, fueled stove soon) with a bill, so nobody eats raw (−7).

## Days 2–4

- [ ] **Recreation**: a `HorseshoesPin` and a `ChessTable` in the dining room (work.md). Recreation is worth up to
      30 mood points between starved and fully satisfied.
- [ ] **Dining/rec room** that's at least decent (impressiveness 40): floor, chairs, a lamp, kept clean.
- [ ] Butcher table; hunt safe animals (food.md) for fine meals later.
- [ ] Research bench; research running on someone (work.md).
- [ ] Defensive position at the approach the raiders come from, not around the bedrooms (threats.md).
- [ ] Medicine unforbidden and indoors; a doctor assigned (health.md).

## Days 5–10

- [ ] "Initial optimism" (+10) fades in this window: mood must hold on rooms, food and recreation by now.
      Watch `mood.average`; act before it falls below 0.45.
- [ ] Food stored ≥ 5 days and rising; second crop (potatoes or corn) if the season allows.
- [ ] Power (wood-fired generator) once steel and components allow; then a freezer.
- [ ] Each new colonist: work settings, a bedroom, a bed.

## Days 10–14

- [ ] Raids are bigger (starting factor 0.7 → rising): cover at the approach, everyone armed.
- [ ] Bedrooms and dining room improving toward "decent"/"slightly impressive".
- [ ] Prepare for the season ahead: heating for winter, food reserve, warm clothes.

## Health checks code can run every cycle

| Check | Detect | Bad sign | Look in |
|---|---|---|---|
| Mood | `get_colony_status` `mood.average`, `lowMood` | < 0.45, or anyone < 0.35 | mood.md |
| Food | `food.daysLeft` | < 2 after day one | food.md |
| Idle | alert `Alert_ColonistsIdle` | anyone idle for hours | work.md |
| Shelter | thought `SleptOutside` / `SleptInCold` on anyone | any | rooms.md |
| Barracks | thoughts with "barracks" in the label | any negative | rooms.md |
| Recreation | need `Joy` level < 0.3, thoughts "Recreation…" | unfulfilled or worse | work.md |
| Eating | thoughts `AteWithoutTable`, `AteRawFood` | any | mood.md, food.md |
| Health | `medical.bleeding`, `downed` | any outside a fight | health.md |
| Threats | `threats.hostiles`, `manhunters` | > 0 | threats.md |

The most expensive mistakes, from this project's trials: colonists with most work switched off (idle, fields
untended); everyone sleeping outdoors or in a barracks; no recreation building at all; a game window
(the naming dialog) pausing the game with nobody to close it.
