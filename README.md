# rimworld-agent

Code-first AI play for RimWorld: an LLM writes long-running Python that drives the game, and is
woken only when that code meets something it can't handle.

The game side is the [RimMCP](https://github.com/rakanssh/rimcp) mod
([Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=3809698070)), which serves a
token-protected HTTP API on `127.0.0.1:39571`. This repo talks to that API directly; MCP is not involved.

## rimsdk

A typed client with one method per RimMCP tool, generated from the mod's own tool manifest.

```python
from rimsdk import RimClient

with RimClient.connect() as rim:              # finds RimMCP's token in RimWorld's config dir
    status = rim.get_colony_status()          # every call returns a Result: the reply's JSON dict
    print(status.tick, status.data)
    rim.set_pawn_work_priority(pawn_id, "Cooking", priority=1)
    run = rim.advance(6)                      # run 6 in-game hours; stops early on raids, injuries, ...
    print(run["status"], run.get("stoppedBy"), run["events"])
```

- **Typed methods.** Arguments are snake_case Python names; enums are `Literal`s and nested objects
  are `TypedDict`s. Docstrings carry RimMCP's descriptions (see `help(RimClient.place_blueprint)`).
  Only URL path ids (a pawn id, a work type...) are positional; every other argument is keyword-only.
- **Results.** `Result` is a dict with `.data`, `.tick`, `.map_id`, `.load_id`, `.truncated`,
  `.next_cursor` and `.changed`.
- **Errors.** Failures raise a `rimsdk.errors.RimError` subclass, such as `BadRequest`, `NotFound`,
  `Conflict`, `AccessDenied`, `NotProcessing` or `BridgeUnavailable`. `GameBusy`
  (loading, saving, main thread backed up) is retried with backoff first.
- **Helpers:**
  - `rim.advance(hours, stop_on=...)` blocks until a time run ends.
  - `rim.wait_operation(op)` waits on a save, load or setup operation.
  - `rim.pages(rim.list_pawns)` follows cursors through a list.
  - `rim.call(name, **wire_args)` calls a tool the SDK doesn't know yet.
- **Read-only mode.** `RimClient.connect(read_only=True)` refuses any tool that changes the game.

Connection settings come from `RIMCP_URL` / `RIMCP_TOKEN` if set, otherwise from RimMCP's saved
settings (`Config/Mod_*_RiMCPMod.xml`).

## rimagent

The runtime plays the colony with plain Python managers (`src/rimagent/managers/`). It runs game
time in chunks that stop early on raids, injuries and the like, and it stops on **incidents**:
- an event no manager handles,
- a manager crashing,
- a Critical/High game alert no manager claims for 12 game hours,
- food critical, or time that won't run.

With `--escalate claude`, each incident wakes a headless Claude Code session. The session reads
the report and `CLAUDE.md`, and writes or fixes managers and tests. It may edit only those files;
it sees the game only through `rimagent inspect` and dry runs, and has a spending cap. It answers
resume or halt. The runtime resumes only if `pytest` passes, then hot-reloads the managers and
re-delivers the triggering event. Each incident's report, session output and diff land in
`runs/<timestamp>/incidents/`.

```sh
uv run python -m rimagent run --hours 24                     # stop on incidents
uv run python -m rimagent run --hours 24 --escalate claude   # let Claude Code fix the code
uv run python -m rimagent run --dry-run                      # what managers would change, changing nothing
uv run python -m rimagent inspect --tools                    # read-only look at the live game
```

## Evaluation

`eval` loads a baseline save, plays it with the current code, and scores the colony out of 100.
The score has five parts:

| Part | Weight | Measures |
|---|---|---|
| Survival | 40 | colonists alive at the end |
| Food | 20 | share of samples after day one with at least 2 days of stored food |
| Mood | 15 | average mood across samples |
| Shelter | 10 | beds per colonist |
| Completion | 15 | share of the planned days actually played |

**Autonomy** is reported separately: incidents, fixing sessions, how many resumed, and their cost.
Each result records the git commit it ran, in `runs/<timestamp>/eval.json`. The storyteller is
random, so compare several trials.

```sh
uv run python -m rimagent eval --save rimagent-start --days 3 --label baseline
uv run python -m rimagent eval --save rimagent-start --days 3 --escalate claude --label self-fixing
uv run python -m rimagent evals          # compare every evaluation so far
```

The colony loaded when an eval starts is saved first as `rimagent-before-eval-<timestamp>`.

## Commands

```sh
uv run python -m rimsdk                  # connection, access, and SDK-vs-mod check
uv run pytest                            # offline tests
uv run pytest -m live                    # read-only contract tests against the running game
uv run python -m rimsdk.codegen          # regenerate from the running mod (after a RimMCP update)
uv run python -m rimsdk.codegen --bundled  # regenerate from src/rimsdk/manifest.json
```

`src/rimsdk/manifest.json` is RimMCP v1.1.0's manifest. It was read out of the release's proxy
binary as data, so nothing from that build was run. `_generated.py` is generated from it; don't edit it by hand.
