# Threats: raids, fights and events

## How big raids get

- **Raid points = (wealth points + pawn points) × difficulty × starting factor × adaption factor.** The
  storyteller "buys" raiders with points (a tribal warrior ≈ 60). Minimum 35, maximum 10,000.
- **Storyteller wealth** = items + creatures + **buildings × 0.5**. Wealth points are 0 below about 14,000
  wealth, rising to 2,400 at 400k. Colonists (and combat animals) add pawn points, so more people means bigger
  raids too.
- **Starting factor** makes the early game easier: **0.7 at day 10**, rising to 1 by day 40.
- **Adaption factor** rises when the colony is doing well (no losses) and falls after deaths or downs.
- This colony: threat scale 0.6 (Adventure story). The first threats are small: a mad animal, one or two
  raiders with melee weapons. By day 10–14 expect a few armed raiders at once.
- Practical rule: **don't build wealth you don't use** (raids grow and the expectations bonus shrinks; see mood.md).

## Cover and positioning

| Cover | Blocks shots |
|---|---|
| Wall (lean out to fire) | up to 75% |
| **Barricade / sandbags** | **55%** (identical; barricade = 5 wood, sandbags = 5 cloth) |
| Stone chunk | 50% |
| Tree | 25% |
| Open ground | 0% |

- Cover counts only against shots coming **from the far side**: stand directly behind it, facing the enemy.
  A pawn standing *on* a barricade can't take cover there.
- Barricades are **beauty −3** each (ugly): don't ring living spaces with them; put them at the approach.
- **Space shooters ≥ 2 tiles apart** (grenades, and friendly fire passes through tight groups).
- Melee pawns wait behind the shooters and engage only what reaches the line.
- Draft (`set_pawn_drafted`) and move (`order_pawn order=move x z`); drafted pawns shoot what's in range.

## Raid behaviour (early)

- **Immediate attack** is the usual early raid: they walk in and attack. Later: sappers (dig through walls),
  sieges (build mortars), drop pods (land inside the base).
- Raiders flee once enough of them are downed or dead.
- Downed raiders can be captured (prisoner bed in a separate room) and recruited, or left. Downed colonists
  **bleed**: rescue to a bed and tend them before blood loss kills (hours, not days).

## After a fight

- Undraft, rescue the downed (`order_pawn order=rescue target_id`), tend (doctor work enabled, medicine
  unforbidden). See health.md.
- **Corpses** in view cost mood (−4, −6 rotting): bury them in a `Grave` or haul them away from the base.
- Strip only living or freshly dead raiders if their apparel is wanted; "tainted" apparel costs mood.

## Events

| Event | Danger | What to do |
|---|---|---|
| Mad animal / **manhunter pack** | High early | Stay indoors, doors closed (they can't open doors); shoot from behind cover if they reach someone. They calm down after a while. |
| **Toxic fallout** | Medium | Keep everyone indoors (roofs block it); it builds toxic buildup outdoors; crops and animals outside die. |
| **Cold snap** | Medium | Outdoor crops die: harvest what's ready; heat bedrooms (campfire/heater); parkas. |
| **Heat wave** | Medium | Heatstroke outdoors; passive coolers indoors; work at dawn/dusk. |
| **Flashstorm / fire** | Medium | Firefighter work on; fires spread through wood and dry grass; keep a firebreak around wooden buildings. |
| Solar flare | Low | Power is down for a while; nothing to fix. |
| Psychic drone | Mood | −mood for one gender for days: bank mood beforehand (recreation, good meals). |
| Blight | Food | Cut the blighted plants at once before it spreads. |
| Visitors / traders | None | They walk through; don't attack them. |
| Wanderer joins / refugee | Opportunity | A new colonist: set work, add a bedroom and a bed. |

Detect: `advance` run events (`hostiles`, `threatLetter`, `letter`, `injured`, `downed`, `mentalBreak`),
`get_events` letters and alerts, `list_threats` for hostiles and manhunters with positions.
