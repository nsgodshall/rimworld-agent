"""Choosing what to build with, from what's in stock.

Everything used to be wood. Wood runs out early: barricades, beds, furniture, the research bench and fuel
all want it, and in trial 6 the house's last wall waited days on wood (37 in stock) while 1,065 steel sat
unused, leaving the room open to the sky. Walls, doors, beds, tables and chairs take wood or steel alike.
"""

from __future__ import annotations

from ..manager import Context

WOOD, STEEL, SILVER = "WoodLog", "Steel", "Silver"
# Wood kept back for what only wood does early: campfire and torch fuel, the butcher table, the research bench.
WOOD_RESERVE = 150
STEEL_RESERVE = 100  # components and tools come later; keep a little


def pick(ctx: Context, amount: int, prefer: tuple[str, ...] = (WOOD, STEEL), spent: dict[str, int] | None = None) -> str:
    """The first of `prefer` with `amount` to spare above its reserve, else wood (it can be felled).

    Counts what colonists can use now (unforbidden, stored or lying about); blueprints already placed
    aren't subtracted. For several
    parts of one plan, pass the same `spent` dict: each pick records its amount there, and the next
    counts it as used.
    """
    stock = {s: ctx.snapshot.usable(s) for s in prefer}
    spent = spent if spent is not None else {}
    reserve = {WOOD: WOOD_RESERVE, STEEL: STEEL_RESERVE}
    spare = {s: stock.get(s, 0) - reserve.get(s, 0) - spent.get(s, 0) for s in prefer}
    # Short of everything: wood, which the supplies manager fells more of; steel that runs out leaves
    # blueprints waiting for good (trial 7's beds).
    choice = next((s for s in prefer if spare[s] >= amount), None) or (WOOD if WOOD in prefer else max(prefer, key=spare.get))
    spent[choice] = spent.get(choice, 0) + amount
    return choice
