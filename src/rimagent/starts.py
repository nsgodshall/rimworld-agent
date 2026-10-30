"""New starting saves for evaluation: one colony per (seed, biome, storyteller...), landed and named.

    uv run python -m rimagent newstart --name start-boreal-7 --seed boreal7 --biome BorealForest

Every trial up to trial 26 started from one save (rimagent-landed-named): one seed, one map, one set of
colonists, the same raid on day 5. A set of different starts says whether the code plays RimWorld or that map.

Steps, all through RimMCP's setup tools: start a Crashlanded setup, choose the storyteller and difficulty,
generate a world from the seed, find a site in the biome, take the classic ideoligion and the rolled
colonists, start. Then:
- the scenario's intro window holds the game paused: saving and loading again closes it;
- run time until the colonists are out of their drop pods;
- save, and name the faction and settlement in the save file, so the game never asks (a window that holds
  it paused and that RimMCP can't answer; see CLAUDE.md).
start_game waits for the player to approve unless RimMCP's "Unattended game setup" is on (Mod settings).
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from rimsdk import RimClient, config, errors


@dataclass
class StartSpec:
    name: str                       # the save's name
    seed: str                       # the world seed
    biome: str = "TemperateForest"
    storyteller: str = "Cassandra"
    difficulty: str = "Medium"      # Adventure story, as the first baseline
    season: str = "Spring"
    map_size: int = 250
    coverage: int = 30              # percent of the planet: smaller generates faster
    colony_name: str = "Rimagent"


def saves_dir() -> Path:
    for cfg in config.rimworld_config_dirs():
        saves = cfg.parent / "Saves"
        if saves.is_dir():
            return saves
    raise FileNotFoundError("No RimWorld Saves folder found beside the Config folders.")


def name_colony(save: Path, out: Path, name: str) -> None:
    """Name the player faction and its settlement in a save file (RimWorld's own fields, as a named colony saves
    them: the faction's <name>, the settlement's <nameInt> and <namedByPlayer>True)."""
    raw = save.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    m = re.search(r"(\n(\s*)<def>PlayerColony</def>\n)(\s*)<loadID>(\d+)</loadID>", text)
    if m is None:
        raise ValueError(f"No player faction in {save}.")
    faction_id, indent = m.group(4), m.group(3)
    if f"<def>PlayerColony</def>\n{indent}<name>" not in text:
        text = text[:m.end(1)] + f"{indent}<name>{name}</name>\n" + text[m.end(1):]
    settlement = re.search(r'<li Class="Settlement">(?:(?!</li>).)*?<faction>Faction_' + faction_id + r'</faction>.*?</li>',
                           text, flags=re.S)
    if settlement is None:
        raise ValueError(f"No settlement of Faction_{faction_id} in {save}.")
    block = settlement.group(0)
    named = re.sub(r"<nameInt>[^<]*</nameInt>", f"<nameInt>{name}</nameInt>", block, count=1)
    if "<namedByPlayer>" not in named:
        named = re.sub(r"(\n(\s*)<nameInt>[^<]*</nameInt>)", r"\1\n\2<namedByPlayer>True</namedByPlayer>", named, count=1)
    text = text[:settlement.start()] + named + text[settlement.end():]
    out.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))


def _revision(rim: RimClient) -> int:
    return rim.get_setup().data["revision"]


def _op(rim: RimClient, result, what: str, timeout: float = 900) -> dict:
    op = rim.wait_operation(result, timeout=timeout)
    if op.get("state") == "awaitingConfirmation":
        raise RuntimeError(f"{what}: RimWorld asks for confirmation ({op.get('confirmation')}). Turn on RimMCP's "
                           "'Unattended game setup' in Mod settings, or answer it in game, then run this again.")
    if op.get("state") != "succeeded":
        raise RuntimeError(f"{what} ended {op.get('state')}: {op.get('message')}")
    return op


def new_start(rim: RimClient, spec: StartSpec, say=print) -> Path:
    """Make the save `spec.name`: a landed Crashlanded colony with its faction and settlement named."""
    playing = rim.get_game_context().data.get("programState") == "Playing"
    kwargs = {"discard_unsaved": True} if playing else {}
    _op(rim, rim.start_setup(scenario="Crashlanded", wait_seconds=30, request_id=uuid.uuid4().hex, **kwargs), "start_setup")
    rim.set_setup_storyteller(storyteller=spec.storyteller, difficulty=spec.difficulty, commitment_mode=False,
                              expected_revision=_revision(rim))
    say(f"{spec.name}: generating world {spec.seed!r}...")
    _op(rim, rim.generate_world(seed=spec.seed, coverage=spec.coverage, expected_revision=_revision(rim),
                                request_id=uuid.uuid4().hex, wait_seconds=30), "generate_world")
    found = _op(rim, rim.find_starting_sites(biomes=[spec.biome], min_growing_days=30, avoid_encroaching=True,
                                             limit=5, request_id=uuid.uuid4().hex, wait_seconds=30), "find_starting_sites")
    sites = (found.get("result") or {}).get("sites") or found.get("sites") or []
    if not sites:
        raise RuntimeError(f"No {spec.biome} site in world {spec.seed!r}: {found}")
    tile = sites[0]["tileId"]
    say(f"{spec.name}: settling tile {tile} ({spec.biome}).")
    _op(rim, rim.choose_starting_site(tile_id=tile, map_size=spec.map_size, starting_season=spec.season,
                                      expected_revision=_revision(rim), request_id=uuid.uuid4().hex, wait_seconds=30),
        "choose_starting_site")
    if rim.get_setup().data.get("stage") == "ideoligion":
        rim.set_setup_ideoligion(mode="classic", expected_revision=_revision(rim), request_id=uuid.uuid4().hex)
    _op(rim, rim.start_game(expected_revision=_revision(rim), request_id=uuid.uuid4().hex, wait_seconds=30), "start_game")
    rim.wait_until_ready()
    raw, landed = f"{spec.name}-raw", f"{spec.name}-landed"
    # The scenario's intro window holds the game paused; loading a save closes it.
    _op(rim, rim.save_game(name=raw, overwrite=True, wait_seconds=30), "save")
    _op(rim, rim.load_game(name=raw, discard_unsaved=True, wait_seconds=30), "load")
    rim.wait_until_ready()
    time.sleep(10)
    for _ in range(20):  # out of the drop pods: the colonists show on the map
        try:
            rim.advance(0.2, stop_on=[])
        except errors.Conflict:
            time.sleep(3)
            continue
        if rim.list_pawns(filter="colonists").data.get("pawns"):
            break
    _op(rim, rim.save_game(name=landed, overwrite=True, wait_seconds=30), "save")
    folder = saves_dir()
    out = folder / f"{spec.name}.rws"
    name_colony(folder / f"{landed}.rws", out, spec.colony_name)
    for leftover in (raw, landed):
        (folder / f"{leftover}.rws").unlink(missing_ok=True)
    say(f"{spec.name}: saved {out}.")
    return out
