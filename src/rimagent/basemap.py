"""The Base panel of `rimagent watch`: the base plan and how far it's built, and the search that placed it.

Both are drawn as pixel art, one map cell to a square pixel: each character is "▀" in the colour of one cell
over the colour of the cell south of it. The pictures come from state.json ("base" and "baseSearch", which
managers/planner.py publishes); this only draws them.

- The plan: walls in their material, doors, stove, bench, beds, tables, pots, floors by room, on the ground the
  map shows. What's planned but not placed is dim, a blueprint pulses blue, what's built is in full colour.
  Under it, a bar per building (built, blueprints, still to place) and why the site won.
- The search: every place some way round of the plan fits, coloured by its best score (dark to bright), over
  the ground where nothing fits, with the chosen site outlined. `reveal` draws it a row at a time, as if the
  search were sweeping the map.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

Color = tuple[int, int, int]


def rgb(hex_: str) -> Color:
    return int(hex_[1:3], 16), int(hex_[3:5], 16), int(hex_[5:7], 16)


def mix(a: Color, b: Color, t: float) -> Color:
    """`a` moved `t` of the way to `b`."""
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def css(c: Color) -> str:
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


# The ground, by the map view's symbols (and "#"/"x", built and blueprint, in the plan's state rows).
GROUND = {".": "#3a2e22", ":": "#4d3b1d", "_": "#47413b", "t": "#1f4a2a", "^": "#6e6e6e", "?": "#101010",
          "*": "#8a7634", "a": "#a0805a", "#": "#9a9a9a", "b": "#8a6a4a", "x": "#2f6f99", "=": "#6b5a2a",
          "%": "#3f7a2a", " ": "#1a1a1a"}
COLONIST = "#ffffff"  # capital letters
FLOOR = {"k": "#3d302a", "w": "#2e3142", "h": "#3b3450", "p": "#4a3f2a", "g": "#4a3f2a", "s": "#5f5a4e"}
STOCKED = "#8f7640"  # a store floor once the stockpile is there
THING = {"W": "#b8bcc4", "D": "#e3a64a", "S": "#e0482a", "R": "#9b6ee8", "B": "#4f86d9", "T": "#b5835a",
         "c": "#8c6440", "L": "#ffd75f", "H": "#c8c8c8", "C": "#e8e8e8", "e": "#a07850", "o": "#6fcf6f",
         "f": "#ff6fae"}
WOOD_WALL = "#a8743c"
BLUEPRINT = ("#3fa7d6", "#21688f")  # the pulse
# Low to high score: dark violet through red and orange to yellow.
HEAT = [rgb(c) for c in ("#1b0c41", "#3b0f70", "#5c126e", "#7e1e6c", "#a12a63", "#c43c4e", "#e05536",
                         "#f1771e", "#f9a40e", "#fcd225")]
OUTLINE = rgb("#ffffff")
BAR_WIDTH = 14
NAMES = {"house": "house", "wing": "wing", "core": "kitchen·store·shop", "garden": "street pots"}


def ground(ch: str) -> Color:
    return rgb(COLONIST) if ch.isalpha() and ch.isupper() else rgb(GROUND.get(ch, "#333333"))


def pixels(grid: list[list[Color]]) -> Text:
    """Rows of colours, north first, two to a line of "▀"."""
    out = Text()
    for i in range(0, len(grid), 2):
        top, below = grid[i], grid[i + 1] if i + 1 < len(grid) else None
        for j, c in enumerate(top):
            out.append("▀", style=f"{css(c)} on {css(below[j])}" if below else css(c))
        out.append("\n")
    return out


def plan_cell(role: str, state: str, walls: str | None, pulse: int) -> Color:
    if role in THING:
        full = rgb(WOOD_WALL if role == "W" and walls == "WoodLog" else THING[role])
        if state == "#":
            return full
        if state == "x":
            return rgb(BLUEPRINT[pulse % 2])
        return mix(full, rgb("#1c1c1c"), 0.6)  # planned, not placed yet
    if role in FLOOR:
        if role in "pg" and state in "=*":
            return rgb(STOCKED) if state == "=" else rgb(GROUND["*"])
        if state.isalpha() and state.isupper():
            return rgb(COLONIST)
        return mix(rgb(FLOOR[role]), ground(state), 0.25)
    return mix(ground(state), rgb("#000000"), 0.3)  # the margin: the ground as it is


def progress_bar(built: int, blueprints: int, total: int) -> Text:
    if not total:
        return Text("")
    b = round(BAR_WIDTH * built / total)
    p = min(BAR_WIDTH - b, round(BAR_WIDTH * blueprints / total))
    return Text.assemble(("█" * b, "green"), ("▒" * p, css(rgb(BLUEPRINT[0]))), ("░" * (BAR_WIDTH - b - p), "grey46"),
                         (f" {built}/{total}", "bold" if built == total else ""),
                         (f" +{blueprints}" if blueprints else "", css(rgb(BLUEPRINT[0]))))


def describe(frame: list, away: list | None) -> str:
    turns, mirror = (frame[2], frame[3]) if len(frame) > 3 else (0, False)
    way = {(0, -1): "south", (0, 1): "north", (1, 0): "east", (-1, 0): "west"}.get(tuple(away or (0, -1)), "?")
    return f"turned {90 * turns}°{', mirrored' if mirror else ''} · back door {way}"


def score_line(terms: dict | None) -> Text:
    if not terms:
        return Text("")
    t = Text.assemble(("score ", "grey50"), (f"{terms.get('score', '-')}", "bold"))
    for i, (key, label) in enumerate((("walk", "walk"), ("trees", "trees"), ("rich", "rich soil"),
                                      ("room", "room"), ("farmland", "farmland"), ("edge", "edge"))):
        if key in terms:
            t.append("\n      " if i == 3 else "  ")
            t.append(f"{label} ", style="grey50")
            t.append(str(terms[key]))
    return t


def legend() -> Text:
    t = Text()
    for role, label in (("W", "wall"), ("D", "door"), ("S", "stove"), ("R", "bench"), ("B", "bed"), ("f", "pots")):
        t.append("■", style=THING[role])
        t.append(f"{label} ", style="grey62")
    t.append("■", style=BLUEPRINT[0])
    t.append("blueprint", style="grey62")
    return t


def plan_text(base: dict[str, Any], pulse: int) -> Text:
    roles, state = base.get("roles") or [], base.get("state") or []
    grid = [[plan_cell(r, s, base.get("walls"), pulse) for r, s in zip(rrow, srow)] for rrow, srow in zip(roles, state)]
    out = pixels(grid)
    progress = base.get("progress") or {}
    for name in ("house", "wing", "core", "garden"):
        if name in progress:
            out.append(f"{NAMES[name][:18]:<18} ", style="grey62")
            out.append_text(progress_bar(*progress[name]))
            out.append("\n")
    out.append(describe(base.get("frame") or [], base.get("away")) + "\n", style="grey70")
    out.append_text(score_line(base.get("terms")))
    out.append("\n")
    out.append_text(legend())
    return out


def search_grid(search: dict[str, Any], scale: int) -> list[list[Color]]:
    """The search's rows shrunk `scale` times each way (a block's best score, else its first cell's ground),
    with the chosen site's outline."""
    rows = search.get("rows") or []
    r = search.get("rect") or {}
    c = search.get("chosen") or {}
    north = r.get("z", 0) + len(rows) - 1
    outline = set()
    if c:
        for x in range(c["x"], c["x"] + c["width"]):
            outline |= {(x, c["z"]), (x, c["z"] + c["height"] - 1)}
        for z in range(c["z"], c["z"] + c["height"]):
            outline |= {(c["x"], z), (c["x"] + c["width"] - 1, z)}
    grid = []
    for i in range(0, len(rows), scale):
        line = []
        for j in range(0, len(rows[i]), scale):
            block = [(rows[i + di][j + dj], (r.get("x", 0) + j + dj, north - i - di))
                     for di in range(scale) for dj in range(scale) if i + di < len(rows) and j + dj < len(rows[i + di])]
            digits = [int(ch) for ch, _ in block if ch.isdigit()]
            if any(xz in outline for _, xz in block):
                line.append(OUTLINE)
            elif digits:
                line.append(HEAT[max(digits)])
            else:
                line.append(mix(ground(block[0][0]), rgb("#000000"), 0.45))
        grid.append(line)
    return grid


def search_text(search: dict[str, Any], width: int, reveal: float = 1.0) -> Text:
    """The search, shrunk to fit `width` columns; `reveal` (0 to 1) of its rows drawn, the newest bright."""
    cols = len((search.get("rows") or [""])[0])
    scale = max(1, -(-cols // max(1, width)))
    grid = search_grid(search, scale)
    shown = max(0, min(len(grid), round(len(grid) * reveal)))
    dark = rgb("#0c0c0c")
    if shown < len(grid):  # the sweep: what's searched, a bright scan line, and the dark still to come
        grid = grid[:shown] + [[mix(c, OUTLINE, 0.6) for c in grid[shown]]] + [[dark] * len(row) for row in grid[shown + 1:]]
    out = pixels(grid)
    tried, fits = search.get("tried", 0), search.get("fits", 0)
    out.append(f"{tried:,} placements tried · {fits:,} fit\n", style="grey70")
    out.append("low ", style="grey50")
    for c in HEAT:
        out.append("█", style=css(c))
    out.append(" high  ", style="grey50")
    out.append("█", style=css(OUTLINE))
    out.append(" chosen\n", style="grey50")
    out.append_text(score_line(search.get("terms")))
    return out
