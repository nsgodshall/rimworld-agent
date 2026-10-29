"""A scripted stand-in for the game, implementing the RimClient calls the runtime and managers use."""

from __future__ import annotations

from typing import Any

from rimsdk import Result, RimClient, errors

from .conftest import FakeTransport


def grid(width: int, height: int, fill: str = ".") -> dict[tuple[int, int], str]:
    return {(x, z): fill for x in range(width) for z in range(height)}


# check_placement's footprintOffset and interactionCellOffset, facing north, as the live game gives them.
FOOTPRINTS = {
    "FueledStove": ({"x": -1, "z": 0, "width": 3, "height": 1}, {"x": 0, "z": -1}),
    "Campfire": ({"x": 0, "z": 0, "width": 1, "height": 1}, {"x": 0, "z": -1}),
    "Table2x2c": ({"x": 0, "z": 0, "width": 2, "height": 2}, None),
    "SimpleResearchBench": ({"x": -1, "z": 0, "width": 3, "height": 2}, {"x": 0, "z": -1}),
}


def _footprint(def_: str, x: int, z: int) -> list[tuple[int, int]]:
    if def_ == "Bed":
        return [(x, z), (x, z - 1)]  # facing south
    fp, _ = FOOTPRINTS.get(def_, ({"x": 0, "z": 0, "width": 1, "height": 1}, None))
    return [(x + fp["x"] + i, z + fp["z"] + j) for i in range(fp["width"]) for j in range(fp["height"])]


WORK_TYPES = ("Research", "Cleaning", "Hauling", "Crafting", "Art", "PlantCutting", "Mining", "Growing",
              "Construction", "Hunting", "Cooking", "Doctor")


class FakeRim(RimClient):
    def __init__(self, *, map_size=(100, 100), cells=None, colonists=None):
        super().__init__(FakeTransport())
        self.tick = 0
        self.paused = True
        self.map_size = map_size
        self.cells = cells if cells is not None else grid(*map_size)
        self.colonists = colonists if colonists is not None else [
            {"ids": {"id": f"Human{n}"}, "name": n, "position": {"x": 50, "y": 0, "z": 50},
             "drafted": False, "downed": False, "gear": {"equipment": [], "apparel": []}} for n in ("A", "B", "C")
        ]
        self.zones: list[dict[str, Any]] = []
        self.forbidden_food: list[str] = []
        self.food = {"eatenPerDay": 5.6, "daysLeft": 5.0}
        self.run_script: list[dict[str, Any]] = []  # runs to return, in order; then plain completed runs
        self.history: list[dict[str, Any]] = []
        self.alerts: list[dict[str, Any]] = []
        self.beds: list[dict[str, Any]] = []        # built beds, as list_buildings shows them
        self.blueprints: list[dict[str, Any]] = []  # placements not built yet
        self.buildings: list[dict[str, Any]] = []   # other built buildings, as list_buildings shows them
        self.bills: list[dict[str, Any]] = []       # as list_production shows them
        self.unavailable: set[str] = set()          # defs check_placement says aren't available (research)
        self.threats: list[dict[str, Any]] = []     # as list_threats shows them
        self.weapons: list[dict[str, Any]] = []     # as find_things shows them
        self.medicine: list[dict[str, Any]] = []    # as find_things shows them
        self.goods: list[dict[str, Any]] = []       # find_things without a category: items near the base
        self.resources: list[dict[str, Any]] = []   # as list_resources shows them
        self.medical: dict[str, Any] = {"downed": 0, "bleeding": 0, "examples": []}
        self.projects: list[dict[str, Any]] = [     # as get_research shows them; "available" is the fake's own
            {"defName": "A", "label": "A", "baseCost": 300, "finished": True},
            {"defName": "B", "label": "B", "baseCost": 500, "finished": False},
        ]
        self.research_project: str | None = None
        # list_work detail=normal's work entries, by pawn id (fixtures/live/list_work_normal.json);
        # each colonist starts with every work type on.
        self.work: dict[str, list[dict[str, Any]]] = {
            p["ids"]["id"]: [{"defName": w, "label": w, "naturalPriority": n, "disabled": False, "active": True, "priority": 3}
                             for n, w in enumerate(WORK_TYPES)]
            for p in self.colonists
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _record(self, tool: str, /, **args: Any) -> None:
        self.calls.append((tool, {k: v for k, v in args.items() if v is not None}))

    def called(self, name: str) -> list[dict[str, Any]]:
        return [args for n, args in self.calls if n == name]

    # --- time --------------------------------------------------------------------------------

    def get_advance(self, **_: Any) -> Result:
        return Result({"data": {"time": {"tick": self.tick, "paused": self.paused}, "run": None}})

    def advance(self, hours: float, *, speed=None, stop_on=None, on_poll=None) -> dict[str, Any]:
        self._record("advance", hours=hours)
        run = self.run_script.pop(0) if self.run_script else {}
        start = self.tick
        self.tick = run.get("tick", start + round(hours * 2500))
        return {"status": "completed", "endReason": "completed", "tick": self.tick, "events": [], **run}

    def set_game_speed(self, *, speed, **_: Any) -> Result:
        self._record("set_game_speed", speed=speed)
        self.paused = speed == "Paused"
        return Result({"changed": True, "data": {}})

    # --- reads -------------------------------------------------------------------------------

    def get_colony_status(self, **_: Any) -> Result:
        return Result({"data": {
            "map": {"size": {"x": self.map_size[0], "z": self.map_size[1]}},
            "time": {"ticksGame": self.tick},
            "food": self.food,
            "medical": self.medical,
            "threats": {"hostiles": sum(t.get("threatKind") != "animal" for t in self.threats),
                        "total": len(self.threats)},
        }})

    def list_pawns(self, **_: Any) -> Result:
        return Result({"data": {"pawns": self.colonists}})

    def list_threats(self, **_: Any) -> Result:
        return Result({"data": {"summary": {}, "threats": self.threats}})

    def list_resources(self, **_: Any) -> Result:
        return Result({"data": {"resources": self.resources}})

    def pawn(self, pawn_id: str) -> dict[str, Any]:
        return next(p for p in self.colonists if p["ids"]["id"] == pawn_id)

    def get_pawn(self, id, **_: Any) -> Result:
        return Result({"data": self.pawn(id)})

    def list_zones(self, **_: Any) -> Result:
        return Result({"data": {"zones": self.zones}})

    def get_events(self, *, since=None, **_: Any) -> Result:
        entries, self.history = (self.history, []) if since else ([], self.history)
        return Result({"data": {"alerts": self.alerts,
                                "history": {"entries": entries, "more": False, "cursor": f"c{self.tick}"}}})

    def get_map_view(self, *, x, z, width, height, **_: Any) -> Result:
        rows = ["".join(self.cells.get((cx, cz), "?") for cx in range(x, x + width)) for cz in range(z + height - 1, z - 1, -1)]
        return Result({"data": {"origin": {"x": x, "z": z}, "width": width, "height": height, "rows": rows,
                                "legend": {".": "soil", ":": "rich soil", "_": "ground too poor to farm, or floor",
                                           "x": "blueprint or unfinished building", "b": "other building", "t": "tree"}}})

    def get_game_context(self, **_: Any) -> Result:
        return Result({"data": {"programState": "Playing"}})

    def load_game(self, *, name, save_first=None, overwrite=None, **_: Any) -> Result:
        self._record("load_game", name=name, save_first=save_first)
        self.tick = 0
        return Result({"data": {"operationId": "op1", "state": "succeeded", "done": True}})

    def get_operation(self, operation_id, **_: Any) -> Result:
        return Result({"data": {"operationId": operation_id, "state": "succeeded", "done": True}})

    def health(self) -> dict[str, Any]:
        return {"status": "ok"}

    def get_research(self, *, available_only=None, **_: Any) -> Result:
        """As in game: blockers name what stops research; availableOnly leaves out what can't start now."""
        blockers = []
        if self.research_project is None:
            blockers.append({"kind": "noProject", "message": "No research project is chosen."})
        if not any(b["def"]["defName"] in ("SimpleResearchBench", "HiTechResearchBench") for b in self.buildings):
            blockers.append({"kind": "missingResearchBench", "message": "There is no research bench."})
        projects = [p for p in self.projects if not available_only or (p.get("available", True) and not p["finished"])]
        return Result({"data": {"blockers": blockers,
                                "projects": [{k: v for k, v in p.items() if k != "available"} for p in projects]}})

    def list_buildings(self, *, category=None, **_: Any) -> Result:
        beds = [{"ids": {"id": b["id"]}, "def": {"defName": "Bed"}, **b} for b in self.beds]
        return Result({"data": {"buildings": self.beds if category == "bed" else beds + self.buildings}})

    def list_production(self, **_: Any) -> Result:
        return Result({"data": {"bills": self.bills}})

    def add_bill_to_workshop(self, workshop_id, *, recipe_def_name, **kw: Any) -> Result:
        self._record("add_bill_to_workshop", workshop_id=workshop_id, recipe_def_name=recipe_def_name, **kw)
        self.bills.append({"workshop": workshop_id, "recipe": recipe_def_name})
        return Result({"changed": True, "data": {}})

    def check_placement(self, *, def_, x, z, width=1, height=1, rotation=None, **_: Any) -> Result:
        """As in game: positions whose footprint (and interaction cell) is open ground fit; taken cells,
        whether a blueprint, a bed or an item, are "Space already occupied."."""
        fp, ic = FOOTPRINTS.get(def_, ({"x": 0, "z": 0, "width": 1, "height": 1}, None))
        fits, taken = [], []
        for cz in range(z, z + height):
            for cx in range(x, x + width):
                cells = _footprint(def_, cx, cz) + ([(cx + ic["x"], cz + ic["z"])] if ic else [])
                (fits if all(self.cells.get(c) in (".", ":", "_") for c in cells) else taken).append({"x": cx, "z": cz})
        rejected = [{"reason": "Space already occupied.", "count": len(taken), "positions": taken[:10]}] if taken else []
        return Result({"data": {"building": {"def": {"defName": def_}, "rotation": rotation or "north",
                                             "footprintOffset": fp, "interactionCellOffset": ic},
                                "available": def_ not in self.unavailable, "fitsCount": len(fits),
                                "fits": fits[:50], "rejected": rejected}})

    def find_things(self, *, category=None, forbidden=None, **_: Any) -> Result:
        things = [{"id": i} for i in self.forbidden_food] if category == "Foods" and forbidden else []
        if category == "Weapons":
            things = [w for w in self.weapons if forbidden is None or w["forbidden"] == forbidden]
        if category == "Medicine":
            things = [m for m in self.medicine if forbidden is None or m["forbidden"] == forbidden]
        if category is None:
            things = [g for g in self.goods if forbidden is None or g["forbidden"] == forbidden]
        return Result({"data": {"things": things}})

    # --- changes -----------------------------------------------------------------------------

    def designate(self, *, kind, thing_ids=None, rects=None, **_: Any) -> Result:
        self._record("designate", kind=kind, thing_ids=thing_ids, rects=rects)
        if kind == "unforbid":
            self.forbidden_food = [t for t in self.forbidden_food if t not in (thing_ids or [])]
            for g in self.goods:
                if g["id"] in (thing_ids or []):
                    g["forbidden"] = False
        return Result({"changed": True, "data": {}})

    def set_zone(self, *, kind=None, add=None, request_id=None, **_: Any) -> Result:
        self._record("set_zone", kind=kind, add=add)
        cells = 0
        for r in add or []:
            for cx in range(r["x"], r["x"] + r.get("width", 1)):
                for cz in range(r["z"], r["z"] + r.get("height", 1)):
                    if self.cells.get((cx, cz)) in (".", ":", "_"):
                        self.cells[(cx, cz)] = "s" if kind == "stockpile" else "g"
                        cells += 1
        zone = {"id": f"zone:0:{len(self.zones) + 1}", "kind": kind, "cellCount": cells}
        if add:
            zone["representativeCell"] = {"x": add[0]["x"], "y": 0, "z": add[0]["z"]}
        self.zones.append(zone)
        return Result({"changed": True, "data": {"zone": zone, "created": True}})

    def set_research_project(self, *, project_def_name, **_: Any) -> Result:
        self._record("set_research_project", project_def_name=project_def_name)
        self.research_project = project_def_name
        return Result({"changed": True, "data": {}})

    def set_pawn_drafted(self, pawn_id, *, drafted, **_: Any) -> Result:
        self._record("set_pawn_drafted", pawn_id=pawn_id, drafted=drafted)
        self.pawn(pawn_id)["drafted"] = drafted
        return Result({"changed": True, "data": {}})

    def list_work(self, **_: Any) -> Result:
        pawns = [{"id": p["ids"]["id"], "name": p["name"], "role": "colonist", "drafted": p["drafted"],
                  "downed": p["downed"], "work": self.work[p["ids"]["id"]]} for p in self.colonists]
        return Result({"data": {"manualPriorities": False, "pawns": pawns}})

    def set_pawn_work_priority(self, pawn_id, work_type_def_name, *, priority, **_: Any) -> Result:
        self._record("set_pawn_work_priority", pawn_id=pawn_id, work_type_def_name=work_type_def_name, priority=priority)
        entry = next(w for w in self.work[pawn_id] if w["defName"] == work_type_def_name)
        if entry["disabled"]:
            raise errors.Conflict("Pawn cannot do this work type.", status=409)
        previous, entry["priority"], entry["active"] = entry["priority"], priority, priority > 0
        return Result({"changed": previous != priority, "data": {"previousPriority": previous, "priority": priority,
                                                                 "manualPrioritiesChanged": False}})

    def order_pawn(self, pawn_id, *, order, target_id=None, x=None, z=None, queue=None, **_: Any) -> Result:
        self._record("order_pawn", pawn_id=pawn_id, order=order, target_id=target_id, x=x, z=z)
        return Result({"changed": True, "data": {"order": order, "outcome": "jobIssued", "reason": None}})

    def set_growing_zone(self, *, zone_id, plant=None, allow_sow=None, allow_cut=None, **_: Any) -> Result:
        self._record("set_growing_zone", zone_id=zone_id, plant=plant)
        return Result({"changed": True, "data": {}})

    def place_blueprint(self, *, placements, request_id=None, **_: Any) -> Result:
        """Mirrors RimMCP's reply: per placement an outcome of applied, alreadySatisfied or rejected."""
        self._record("place_blueprint", placements=placements)
        results = []
        for p in placements:
            footprint = _footprint(p["def"], p["x"], p["z"])
            same = (p["def"], p["x"], p["z"], p.get("rotation"), p.get("stuff"))
            if any((b["def"], b["x"], b["z"], b.get("rotation"), b.get("stuff")) == same for b in self.blueprints):
                results.append({**p, "outcome": "alreadySatisfied", "state": "blueprint", "reason": None})
            elif all(self.cells.get(c) in (".", "_") for c in footprint):
                for c in footprint:
                    self.cells[c] = "x"  # a blueprint, on the map view
                self.blueprints.append(p)
                results.append({**p, "outcome": "applied", "state": "blueprint", "reason": None})
            else:
                results.append({**p, "outcome": "rejected", "reason": "Space already occupied."})
        count = lambda o: sum(r["outcome"] == o for r in results)
        return Result({"changed": count("applied") > 0, "data": {
            "applied": count("applied"), "alreadySatisfied": count("alreadySatisfied"),
            "rejectedCount": count("rejected"), "results": results, "blockers": []}})

    def build_blueprints(self, n: int | None = None) -> None:
        """Colonists finish blueprints: they become buildings list_buildings shows, drawn as buildings."""
        for p in self.blueprints[:n]:
            for c in _footprint(p["def"], p["x"], p["z"]):
                self.cells[c] = "b"
            position = {"x": p["x"], "y": 0, "z": p["z"]}
            if p["def"] == "Bed":
                self.beds.append({"id": f"Bed{len(self.beds) + 1}", "position": position})
            else:
                n_id = f"{p['def']}{len(self.buildings) + 1}"
                self.buildings.append({"ids": {"id": n_id}, "def": {"defName": p["def"]}, "position": position})
        self.blueprints = self.blueprints[len(self.blueprints[:n]):]
