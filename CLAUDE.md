# rimworld-agent

Code-first AI play for RimWorld. Plain Python plays the game. An LLM is called only when that code
meets something it can't handle, and the fix it makes is more code, so the same situation is
handled without it next time.

## Layout

- `src/rimsdk/`: typed client for the RimMCP mod's HTTP bridge. `_generated.py` is generated
  (`uv run python -m rimsdk.codegen`); never edit it by hand. `mapview.py` has `Rect`, `MapView`
  and `scan`.
- `src/rimagent/`: the runtime.
  - `runtime.py`: the clock loop. Each cycle reads the colony, dispatches events, runs due managers,
    checks tripwires and alerts, then runs game time in chunks.
  - `manager.py`: `Manager` and `Context`.
  - `snapshot.py`: cached reads for one cycle.
  - `escalate.py`: wakes a headless Claude Code session on incidents.
- `src/rimagent/managers/`: **the colony's policies**. Every `Manager` subclass in a module here
  is loaded automatically, and reloaded when its file changes.
- `tests/`: `fakegame.FakeRim` is a scripted stand-in for the game; `tests/fixtures/live/` holds
  real replies.
- `runs/<timestamp>/`: `journal.jsonl` plus `incidents/NNN-kind.{md,json,diff,session.json}`.

## Game knowledge

`docs/reference/` holds early-game facts distilled from the RimWorld wiki for this project: mood (every
common thought and its value), rooms (bedroom vs barracks, impressiveness), food, threats, health, work and
a day-by-day playbook. Read the relevant file before writing a manager that changes how the colony lives.

## Writing a manager

```python
from rimsdk.mapview import Rect
from ..manager import Context, Manager

class BedsManager(Manager):
    name = "beds"
    every_hours = 6                      # how often update() runs, in game hours
    handles = ()                         # event kinds for on_event(): death, downed, injured,
                                         # mentalBreak, hostiles, lowFood, threatLetter, letter,
                                         # or history kinds such as "message"
    alerts = ("Alert_NeedColonistBeds",) # game alerts this manager owns (get_events alerts[].type)

    def update(self, ctx: Context) -> None:
        snap = ctx.snapshot              # snap.colonists, snap.zones_of("stockpile"), snap.base_center,
                                         # snap.food_days, snap.alerts, snap.view(Rect(...)), snap.colony
        ...
        ctx.log(self.name, "Placed 3 beds.", where=str(rect))
```

Rules:
- **Derive from game state; don't remember.** Each `update()` works out what's missing now and does
  only that, so running it twice does no harm. Managers are re-created on reload, so instance state
  is lost.
  - *Exception:* `self.memory`, a dict that survives hot reloads but not a restart. It's for what
    the game can't show, such as which blueprints this manager placed. The map shows every
    blueprint the same way, so counting them all once made barricade blueprints look like beds.
    Check what's remembered against the game, and cope with finding it empty.
- **Change the game only through `ctx.rim`**, and never run time: no `advance`/`advance_time`/`set_game_speed`.
  The runtime owns the clock.
- **Keep updates quick:** a handful of calls. Pass `request_id=uuid.uuid4().hex` when creating things.
- **Problems you can't solve in code** go through `ctx.raise_incident(kind, summary, "warn" | "halt", **details)`.
  Exceptions also become incidents, but a clear incident is better.
- **Claim an alert in `alerts` only if the manager really deals with it.** An unclaimed
  Critical/High alert that shows for 12 game hours stops the runtime to ask for code. So do the
  lower-priority alerts in `runtime.GAP_ALERTS` (no meal source, idle colonists, an unused research
  bench) after 6 hours.
- **Ask for short time runs when needed.** A manager that needs time to pass in small steps (say,
  during a fight) calls `ctx.request_chunk(hours)` each cycle. `managers/defense.py` asks for 0.1
  hours (250 ticks) while hostiles are near.
- **The base layout is in `managers/planner.py`.** On day one it fixes where the kitchen, store, workshop,
  house and wing go (`ctx.board["plan"]`), and reserves the footprint: `snapshot.view` shows open ground there
  as `§`, so other sites keep out. Something that belongs in the base gets a slot in `layout()`, not a spot
  of its own found near the stockpile: that is how trial s1 ended with every stockpile and bench outdoors.
  - The plan is drawn north-up and laid on the map by a `Frame` (`rimsdk.mapview`): any of four turns, mirrored
    or not, whichever site scores best. So nothing may assume the house is north of the store: take a
    building's rotation from the plan (`stove_rotation`, `facing`), and put ugly things out of the back door
    with `beds.away_from_base`. Only beds, chairs, the stove and the bench turn; tables, lamps and pots take
    only "north" (the game refuses the rest).
- **Defense is in `managers/defense.py`.** It arms colonists, drafts and gathers them at the base
  when hostiles come within 45 cells, undrafts after, and rescues the downed. It handles
  `hostiles`, `downed`, and threat letters while hostiles are on the map. Improve the tactic
  there; don't write a second defense manager.
- **Write a test** in `tests/` using `FakeRim`. Extend `FakeRim` when a manager needs a call it
  doesn't fake yet.
- **Never guess a reply's shape.** Before code reads a field, or `FakeRim` fakes a call, look at a
  real reply: `uv run python -m rimagent inspect <tool> ...`. For a tool that changes the game,
  read RimMCP's description with `inspect --doc`. A fake built on assumptions only tests the
  assumptions.
  - *Example:* an early beds manager assumed `check_placement` reports existing blueprints with an
    "identical" reason (the game actually says "Space already occupied."). It also assumed
    `place_blueprint` results carry `status` (they carry `outcome`). Its fake agreed with both
    guesses, so the tests passed and the live game would have got duplicate beds.
- **Blueprints aren't buildings.** `list_buildings` shows only finished ones. Planned and
  half-built things show on `get_map_view` as "blueprint or unfinished building", without saying
  what they are. `place_blueprint` is safe to repeat at the exact same spot, rotation and
  material: that placement comes back `alreadySatisfied`.
  - **A different material where a building stands is a replacement**: the game tears it down to rebuild
    it. In trial 17 the house switched its wall material, every built wall got a steel blueprint, the
    walls came down and the roof killed a colonist. Never re-place a standing building in another material.

## Letters that must be answered

A letter with `canDismiss: false` (get_events letters) must be answered (`answer_letter`). When it expires
the game opens it as a window that holds time paused, and reloading brings it back: trials 9, 15 and 18
stalled on these. `managers/letters.py` answers joiners and halts on any other kind before it expires:
give that kind an answer there.

## The SDK, briefly

- **Calls and results.** `ctx.rim.<tool>(...)` covers every RimMCP tool. Only URL path ids are
  positional; every other argument is keyword-only. Each call returns a `Result` dict, and
  `.data` is the payload.
- **Errors.** Calls raise `rimsdk.errors.*`: `BadRequest` (bad arguments, with the game's reason),
  `NotFound`, `Conflict`.
- **Docs.** `help(RimClient.<tool>)`, or `uv run python -m rimagent inspect --doc <tool>`, gives
  the tool's description and arguments.
- **Coordinates.** Cells are (x, z), with z running north. Rects are a south-west corner plus
  width and height: `Rect(...).to_api()`.
- **Finding spots and building.**
  - `check_placement(def_=..., x=..., z=..., width=..., height=...)` finds where a building fits,
    checking an area of up to 20x20.
  - `place_blueprint(placements=[{"def": ..., "x": ..., "z": ..., "rotation": ...}])` places
    blueprints, and reports each one as applied or rejected with the reason.
- **Zones and orders.** `set_zone(kind="stockpile"|"growing", add=[rect])` creates a zone.
  `set_growing_zone(zone_id=..., plant=...)` sets its crop. `designate(kind=..., thing_ids=... | rects=...)`
  gives map orders.
- **Food.** The game counts only *stored* food: food outside a stockpile shows as 0 days.

## Looking at the live game (read-only)

```sh
uv run python -m rimagent inspect --tools
uv run python -m rimagent inspect get_colony_status
uv run python -m rimagent inspect list_pawns detail=full maxChars=60000
uv run python -m rimagent inspect get_map_view x=100 z=120 width=40 height=40
uv run python -m rimagent run --dry-run    # one runtime cycle; prints the changes managers would make
uv run pytest -q
```

Arguments to `inspect` use the tool's wire (camelCase) names, with JSON values.

Evaluations can start from the main menu with a new colony: `uv run python -m rimagent eval --new SEED:BIOME`
(see `src/rimagent/starts.py`), or several in a row with `rimagent evalset SEED:BIOME ...` for a mean and spread
across maps. That needs RimMCP's "Unattended game setup" on (Mod settings). The older trials used the save `rimagent-landed-named`: `rimagent-landed` with the faction and
settlement already named. Unnamed, RimWorld asks for names around day 4, in a window that holds the
game paused, and RimMCP can't answer it.

The game may be unfocused with Run in background off. Calls then wait for focus (up to 10
minutes) instead of failing.
