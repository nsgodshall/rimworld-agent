# RimWorld early-game reference, for agents

Facts and decision rules for keeping a new colony alive and content through its first weeks, written for
code (managers) and for the LLM sessions that write them. Not a tutorial: numbers, thresholds, rules, and
how each maps onto what RimMCP can read and do.

| File | Use it when |
|---|---|
| [playbook.md](playbook.md) | Deciding what the colony should do next, day by day; what "good" looks like at each point |
| [mood.md](mood.md) | Anything about mood: the formula, break thresholds, every common thought and its value, levers ranked |
| [rooms.md](rooms.md) | Building rooms: indoors rules, bedroom vs barracks, impressiveness and space, layouts that score |
| [food.md](food.md) | Crops, cooking, storage, hunting, how much food is enough |
| [threats.md](threats.md) | Raids (how big, when), cover, fighting, rescue; events (manhunters, fallout, cold snaps, fire) |
| [health.md](health.md) | Tending, medicine, bleeding, infection, rest |
| [work.md](work.md) | Work priorities, skills and passions, research order, recreation |

## Conventions

- **Values are for RimWorld 1.6 on this colony's settings** unless noted: storyteller Cassandra Classic,
  difficulty "Adventure story" (base mood 37, threat scale 0.6), temperate forest, 3 colonists, Ideology
  and Biotech installed.
- **defNames** are given where code needs them (`Bed`, `Wall`, `HorseshoesPin`...). A defName marked *(verify)*
  hasn't been confirmed against this game: check with `inspect check_placement def=... x=... z=...` or
  `inspect search_defs` before relying on it.
- **"Detect"** lines say how to see the condition through RimMCP; **"Act"** lines say which call changes it.
- Mood is a 0–1 fraction in RimMCP (`get_pawn ... mood.level`); the wiki speaks in percent. 0.35 = 35%.

## Sources

Distilled from the [RimWorld Wiki](https://rimworldwiki.com) (CC BY-SA 3.0), fetched 2026-10-29: Quickstart
Guides, Basics, Mood, Mental breaks, Thoughts and its subpages, Room stats, Recreation, Raid points, Food
production, Rice plant, Barricade, Sandbags, and others. Cross-checked against this project's live game where
the notes say so. Where the wiki and the live game disagree, the game wins: say so in the file.
