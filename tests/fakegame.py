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
    "ButcherSpot": ({"x": 0, "z": 0, "width": 1, "height": 1}, {"x": 0, "z": -1}),
    "Table2x2c": ({"x": 0, "z": 0, "width": 2, "height": 2}, None),
    "SimpleResearchBench": ({"x": -1, "z": 0, "width": 3, "height": 2}, {"x": 0, "z": -1}),
}


def _footprint(def_: str, x: int, z: int) -> list[tuple[int, int]]:
    if def_ == "Bed":
        return [(x, z), (x, z - 1)]  # facing south
    fp, _ = FOOTPRINTS.get(def_, ({"x": 0, "z": 0, "width": 1, "height": 1}, None))
    return [(x + fp["x"] + i, z + fp["z"] + j) for i in range(fp["width"]) for j in range(fp["height"])]


WORK_TYPES = ("Firefighter", "Patient", "PatientBedRest", "Research", "Cleaning", "Hauling", "Crafting", "Art",
              "PlantCutting", "Mining", "Growing",
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
        self.loose_food: list[dict[str, Any]] = []  # food outside storage, as find_things shows it
        self.stored_food: list[dict[str, Any]] = [] # food in storage, as find_things shows it
        self.no_path: set[str] = set()              # pawns that can't reach any food (shut in)
        self.animals: list[dict[str, Any]] = []     # wild animals, as list_pawns filter=wildAnimals shows them
        self.hunting: set[str] = set()              # animals designated for hunting
        self.berries: set[tuple[int, int]] = set()  # ripe wild berry bushes (Plant_Berry) by cell
        self.harvesting: set[tuple[int, int]] = set()  # plants designated for harvest
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
        self.rooms: list[dict[str, Any]] = []       # get_environment rooms.items: role, temperatureC, usesOutdoorTemperature
        self.conditions: list[dict[str, Any]] = []  # get_environment conditions: defName, label, ticksLeft
        self.medical: dict[str, Any] = {"downed": 0, "bleeding": 0, "examples": []}
        self.projects: list[dict[str, Any]] = [     # as get_research shows them; "available" is the fake's own
            {"defName": "A", "label": "A", "baseCost": 300, "finished": True},
            {"defName": "B", "label": "B", "baseCost": 500, "finished": False},
        ]
        self.research_project: str | None = None
        self.built: list[dict[str, Any]] = []      # placements built by build_blueprints
        self.replaced: list[dict[str, Any]] = []   # placements of another material over a building: torn down
        self.owners: dict[str, str] = {}
        self.schedules: dict[str, dict[int, str]] = {}  # pawn id -> hour -> TimeAssignmentDef            # bed id -> owner pawn id (the game's, not shown by any read)
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

    def list_pawns(self, *, filter=None, **_: Any) -> Result:
        return Result({"data": {"pawns": self.animals if filter == "wildAnimals" else self.colonists}})

    def list_pawn_actions(self, pawn_id, *, target_id=None, **_: Any) -> Result:
        """As in game for a food stack (fixtures: list_pawn_actions on MealSurvivalPack7759; shut in, run
        20261029-074313: a single disabled "Consume packaged survival meal: No path"), or a medicine stack
        (run 20261029-143226, MedicineIndustrial45210)."""
        stack = next((t for t in self.loose_food + self.stored_food if t["id"] == target_id), None)
        medicine = next((m for m in self.medicine if m["id"] == target_id), None)
        if stack is None and medicine is None:
            raise errors.NotFound("No such thing.", status=404)
        if medicine is not None:
            options = [{"id": "1", "text": "Pick up medicine..."},
                       {"id": "2", "text": f"Prioritize hauling medicine x{medicine['count']}"}]
        elif pawn_id in self.no_path:
            options = [{"id": "1", "text": f"Consume {stack['label'].lower()}: No path", "disabled": True}]
        else:
            options = [{"id": "1", "text": f"Consume {stack['label'].lower()}"},
                       {"id": "2", "text": f"Prioritize hauling {stack['label'].lower()} x{stack['count']}"}]
        return Result({"data": {"pawn": {"ids": {"id": pawn_id}}, "target": {"id": target_id},
                                "revision": "r1", "options": options}})

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
                                           "x": "blueprint or unfinished building", "b": "other building", "t": "tree",
                                           "#": "wall or impassable building", "^": "natural rock", "?": "unexplored"}}})

    def get_game_context(self, **_: Any) -> Result:
        return Result({"data": {"programState": "Playing"}})

    def load_game(self, *, name, save_first=None, overwrite=None, discard_unsaved=None, **_: Any) -> Result:
        self._record("load_game", name=name, save_first=save_first, discard_unsaved=discard_unsaved)
        if name != "rimagent-unstick":  # a baseline starts over; the unstick save is this game
            self.tick = 0
        return Result({"data": {"operationId": "op1", "state": "succeeded", "done": True}})

    def save_game(self, *, name, overwrite=None, **_: Any) -> Result:
        self._record("save_game", name=name, overwrite=overwrite)
        return Result({"data": {"operationId": "op-save", "state": "succeeded", "done": True}})

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
        return Result({"data": {"buildings": beds if category == "bed" else beds + self.buildings}})

    def get_environment(self, **_: Any) -> Result:
        """Shaped like the live reply (heat wave, tick 395002): rooms under rooms.items."""
        return Result({"data": {"conditions": self.conditions, "rooms": {"truncated": False, "items": self.rooms}}})

    def list_production(self, **_: Any) -> Result:
        return Result({"data": {"bills": self.bills}})

    def add_bill_to_workshop(self, workshop_id, *, recipe_def_name, **kw: Any) -> Result:
        self._record("add_bill_to_workshop", workshop_id=workshop_id, recipe_def_name=recipe_def_name, **kw)
        # As list_production shows a bill (trimmed).
        self.bills.append({"id": f"Bill_{recipe_def_name}_{len(self.bills)}", "recipe": {"defName": recipe_def_name},
                           "workbench": {"ids": {"id": workshop_id}}, "state": "active",
                           "repeatMode": kw.get("repeat_mode_def_name")})
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

    def find_things(self, *, category=None, forbidden=None, in_storage=None, def_=None, **_: Any) -> Result:
        if def_ is not None:  # a material: self.resources rows, minus their "forbidden" part
            row = next((r for r in self.resources if r.get("defName") == def_), {})
            usable = row.get("count", 0) - row.get("forbidden", 0) if forbidden is False else row.get("count", 0)
            return Result({"data": {"summary": {"matches": 1 if usable else 0, "totalStackCount": usable}, "things": []}})
        things = [{"id": i} for i in self.forbidden_food] if category == "Foods" and forbidden else []
        if category == "Foods" and in_storage is False:
            things = [t for t in self.loose_food if forbidden is None or t["forbidden"] == forbidden]
        if category == "Foods" and in_storage is None and forbidden is False:
            things = [t for t in self.stored_food + self.loose_food if not t["forbidden"]]
        if category == "Weapons":
            things = [w for w in self.weapons if forbidden is None or w["forbidden"] == forbidden]
        if category == "Medicine":
            things = [m for m in self.medicine if (forbidden is None or m["forbidden"] == forbidden)
                      and (in_storage is None or m.get("inStorage", False) == in_storage)]
        if category is None:
            things = [g for g in self.goods if forbidden is None or g["forbidden"] == forbidden]
        return Result({"data": {"things": things}})

    # --- changes -----------------------------------------------------------------------------

    def designate(self, *, kind, thing_ids=None, rects=None, def_name=None, **_: Any) -> Result:
        self._record("designate", kind=kind, thing_ids=thing_ids, rects=rects, def_name=def_name)
        if kind == "cancel":  # DesignationCommandService: removes a blueprint or frame itself
            for bp in [b for b in self.blueprints if b.get("_id") in (thing_ids or [])]:
                for c in _footprint(bp["def"], bp["x"], bp["z"]):
                    self.cells[c] = "."
                self.blueprints.remove(bp)
        if sum(r.get("width", 1) * r.get("height", 1) for r in rects or []) > 3600:
            raise errors.BadRequest("The rectangles cover more than 3600 cells; split the change into smaller calls.",
                                    status=400)
        if kind == "harvest" and def_name == "Plant_Berry":
            # As in game: each ripe plant in the rects is applied once, then alreadySatisfied.
            cells = {c for c in self.berries for r in rects or []
                     if r["x"] <= c[0] < r["x"] + r.get("width", 1) and r["z"] <= c[1] < r["z"] + r.get("height", 1)}
            new = cells - self.harvesting
            self.harvesting |= new
            return Result({"changed": bool(new), "data": {"applied": len(new), "alreadySatisfied": len(cells) - len(new),
                                                          "rejectedCount": 0}})
        if kind == "unforbid":
            self.forbidden_food = [t for t in self.forbidden_food if t not in (thing_ids or [])]
            for g in self.goods:
                if g["id"] in (thing_ids or []):
                    g["forbidden"] = False
        return Result({"changed": True, "data": {}})

    def choose_pawn_action(self, pawn_id, *, revision, option, target_id=None, **_: Any) -> Result:
        self._record("choose_pawn_action", pawn_id=pawn_id, target_id=target_id, revision=revision, option=option)
        return Result({"changed": True, "data": {}})

    def designate_animal(self, pawn_id, *, action, **_: Any) -> Result:
        self._record("designate_animal", pawn_id=pawn_id, action=action)
        (self.hunting.add if action == "hunt" else self.hunting.discard)(pawn_id)
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

    def set_storage(self, *, zone_id=None, building_id=None, priority=None, disallow_all=None, allow=None, disallow=None,
                    **_: Any) -> Result:
        self._record("set_storage", zone_id=zone_id, priority=priority, disallow_all=disallow_all, allow=allow, disallow=disallow)
        # ZoneCommandService.SetStorage: one entry per name, with kind, allow and outcome.
        entries = [{"name": n, "allow": n in (allow or []), "outcome": "applied", "reason": None}
                   for n in (allow or []) + (disallow or [])]
        return Result({"changed": True, "data": {"priority": "Normal", "entries": entries}})

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
                  "downed": p["downed"], "currentJob": p.get("currentJob"), "work": self.work[p["ids"]["id"]],
                  "schedule": {"hours": [{"hour": h, "assignment": a} for h, a in
                                         sorted(self.schedules.get(p["ids"]["id"], {h: "Anything" for h in range(24)}).items())]}}
                 for p in self.colonists]
        return Result({"data": {"manualPriorities": False, "pawns": pawns}})

    def set_pawn_work_priority(self, pawn_id, work_type_def_name, *, priority, **_: Any) -> Result:
        self._record("set_pawn_work_priority", pawn_id=pawn_id, work_type_def_name=work_type_def_name, priority=priority)
        entry = next(w for w in self.work[pawn_id] if w["defName"] == work_type_def_name)
        if entry["disabled"]:
            raise errors.Conflict("Pawn cannot do this work type.", status=409)
        previous, entry["priority"], entry["active"] = entry["priority"], priority, priority > 0
        return Result({"changed": previous != priority, "data": {"previousPriority": previous, "priority": priority,
                                                                 "manualPrioritiesChanged": False}})

    def set_pawn_assignment(self, pawn_id, assignment_kind, *, assignments=None, **_: Any) -> Result:
        """Schedule only, as PawnAssignmentCommandService does it: the given hours change, the rest stay."""
        self._record("set_pawn_assignment", pawn_id=pawn_id, assignment_kind=assignment_kind, assignments=assignments)
        hours = self.schedules.setdefault(pawn_id, {h: "Anything" for h in range(24)})
        for a in assignments or []:
            for h in range(a["startHour"], a["endHour"]):
                hours[h] = a["assignmentDefName"]
        return Result({"changed": True, "data": {}})

    def assign_owner(self, building_id, *, pawn_id, action=None, **_: Any) -> Result:
        """Mirrors RimMCP's reply (OwnerCommandService): owners after, and who lost the bed."""
        self._record("assign_owner", building_id=building_id, pawn_id=pawn_id)
        before = self.owners.get(building_id)
        for bed, owner in list(self.owners.items()):
            if owner == pawn_id:
                del self.owners[bed]  # a pawn owns one bed: assigning moves them
        self.owners[building_id] = pawn_id
        return Result({"changed": before != pawn_id, "data": {
            "owners": [{"id": pawn_id}], "slots": 1, "unassigned": [{"id": before}] if before not in (None, pawn_id) else None,
            "alreadySatisfied": "already assigned" if before == pawn_id else None}})

    def order_pawn(self, pawn_id, *, order, target_id=None, x=None, z=None, queue=None, **_: Any) -> Result:
        self._record("order_pawn", pawn_id=pawn_id, order=order, target_id=target_id, x=x, z=z)
        return Result({"changed": True, "data": {"order": order, "outcome": "jobIssued", "reason": None}})

    def set_growing_zone(self, *, zone_id, plant=None, allow_sow=None, allow_cut=None, **_: Any) -> Result:
        self._record("set_growing_zone", zone_id=zone_id, plant=plant)
        return Result({"changed": True, "data": {}})

    def place_blueprint(self, *, placements, request_id=None, **_: Any) -> Result:
        """Mirrors RimMCP's reply: per placement an outcome of applied, alreadySatisfied or rejected."""
        self._record("place_blueprint", placements=placements)
        if len(placements) > 50:
            raise errors.BadRequest("At most 50 placements per call.", status=400)
        results = []
        for p in placements:
            footprint = _footprint(p["def"], p["x"], p["z"])
            same = (p["def"], p["x"], p["z"], p.get("rotation"), p.get("stuff"))
            # BuildPlacement.Existing: the same def at the cell with the same rotation AND material. Anything else
            # goes to the game's build tool: over a building of another material that's a replacement, which
            # tears the building down (trial 17: steel walls over wooden ones, and the roof fell).
            existing = next((b for b in self.blueprints if (b["def"], b["x"], b["z"], b.get("rotation"), b.get("stuff")) == same), None)
            built = next((b for b in self.built if (b["def"], b["x"], b["z"]) == same[:3]), None)
            if existing is not None:
                results.append({**p, "outcome": "alreadySatisfied", "state": "blueprint",
                                "reason": None, "id": existing["_id"]})
            elif built is not None and (built.get("rotation"), built.get("stuff")) == same[3:]:
                results.append({**p, "outcome": "alreadySatisfied", "state": "built", "reason": None})
            elif built is not None:
                self.replaced.append({**p, "was": built.get("stuff")})
                results.append({**p, "outcome": "applied", "state": "blueprint", "reason": None, "id": f"Blueprint_replace{len(self.replaced)}"})
            elif any((b["def"], b["x"], b["z"]) == same[:3] for b in self.blueprints):
                old = next(b for b in self.blueprints if (b["def"], b["x"], b["z"]) == same[:3])
                self.blueprints.remove(old)  # the build tool puts the new blueprint in its place
                bp = {**p, "_id": f"Blueprint_{p['def']}{len(self.blueprints) + len(self.built) + 1}"}
                self.blueprints.append(bp)
                results.append({**p, "outcome": "applied", "state": "blueprint", "reason": None, "id": bp["_id"]})
            elif all(self.cells.get(c) in (".", "_") for c in footprint):
                for c in footprint:
                    self.cells[c] = "x"  # a blueprint, on the map view
                bp = {**p, "_id": f"Blueprint_{p['def']}{len(self.blueprints) + len(self.built) + 1}"}
                self.blueprints.append(bp)
                results.append({**p, "outcome": "applied", "state": "blueprint", "reason": None, "id": bp["_id"]})
            else:
                results.append({**p, "outcome": "rejected", "reason": "Space already occupied."})
        count = lambda o: sum(r["outcome"] == o for r in results)
        return Result({"changed": count("applied") > 0, "data": {
            "applied": count("applied"), "alreadySatisfied": count("alreadySatisfied"),
            "rejectedCount": count("rejected"), "results": results, "blockers": []}})

    def build_blueprints(self, n: int | None = None) -> None:
        """Colonists finish blueprints: they become buildings list_buildings shows, drawn as buildings."""
        for p in self.blueprints[:n]:
            self.built.append(p)
            for c in _footprint(p["def"], p["x"], p["z"]):
                self.cells[c] = "b"
            position = {"x": p["x"], "y": 0, "z": p["z"]}
            stuff = {"defName": p["stuff"]} if p.get("stuff") else None
            if p["def"] == "Bed":
                self.beds.append({"id": f"Bed{len(self.beds) + 1}", "position": position, "stuff": stuff})
            else:
                n_id = f"{p['def']}{len(self.buildings) + 1}"
                self.buildings.append({"ids": {"id": n_id}, "def": {"defName": p["def"]}, "position": position, "stuff": stuff})
        self.blueprints = self.blueprints[len(self.blueprints[:n]):]
