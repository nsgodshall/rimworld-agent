"""Letters: answer the ones the game insists on before they hold it paused.

Some letters can't be dismissed (get_events letters[].canDismiss false) and must be answered. When one
expires the game opens it as a window that holds the game paused, and saving and loading brings it back.
That was the "window RimMCP doesn't list" that stopped trials 9, 15 and 18: in trial 18, "Wanderer
joins: Humps" (AcceptJoiner) with expiresInTicks 1. So:

- A wanderer who wants to join (AcceptJoiner) is accepted when the house has a free bedroom (board
  house_beds), and turned away otherwise: a colonist without a bedroom sleeps outside (docs/reference/mood.md).
- Any other must-answer letter close to expiring stops the run, so code gets written for it instead of the
  game freezing.
"""

from __future__ import annotations

from typing import Any

from rimsdk import errors

from ..manager import Context, Manager

JOINER = "AcceptJoiner"
URGENT_TICKS = 2 * 2500  # a must-answer letter this close to expiring, with no code for it, stops the run


def option(letter: dict[str, Any], text: str) -> dict[str, Any] | None:
    return next((o for o in letter.get("options") or [] if o.get("text") == text and not o.get("disabledReason")), None)


class LettersManager(Manager):
    name = "letters"
    priority = 4
    every_hours = 1  # well inside any letter's expiry

    def update(self, ctx: Context) -> None:
        letters = ctx.rim.get_events(detail="full").data.get("letters") or []
        for letter in letters:
            if letter.get("canDismiss", True) or not letter.get("options"):
                continue
            if letter.get("type") == JOINER:
                self.answer_joiner(ctx, letter)
            elif (letter.get("expiresInTicks") or URGENT_TICKS + 1) <= URGENT_TICKS and letter.get("id") not in self.memory.get("raised", []):
                self.memory.setdefault("raised", []).append(letter.get("id"))
                ctx.raise_incident("letterNeedsAnswer", f"'{letter.get('label')}' ({letter.get('type')}) must be answered "
                                   f"within {letter.get('expiresInTicks')} ticks, or the game holds itself paused.",
                                   "halt", letter={k: letter.get(k) for k in ("id", "label", "type", "text", "options")})

    def answer_joiner(self, ctx: Context, letter: dict[str, Any]) -> None:
        free_bedrooms = ctx.board.get("house_beds", 0) - len(ctx.snapshot.colonists)
        choice = option(letter, "Accept") if free_bedrooms > 0 else option(letter, "Reject")
        if choice is None:
            return
        try:
            result = ctx.rim.answer_letter(letter["id"], option=choice["id"], revision=letter.get("revision")).data or {}
        except (errors.BadRequest, errors.Conflict, errors.NotFound) as exc:
            ctx.log(self.name, f"Couldn't answer '{letter.get('label')}': {exc.message}")
            return
        ctx.log(self.name, f"{result.get('answered') or choice['text']}: '{letter.get('label')}' "
                           f"({max(free_bedrooms, 0)} free bedrooms).", letter=letter.get("id"))
