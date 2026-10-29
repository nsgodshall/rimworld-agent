# Mood

## The formula

- **Mood target = base mood + sum of active thought offsets**, as a percentage, clamped to 0–100.
  Base mood on "Adventure story" is **37**. (Peaceful/Community 42, Strive to survive 32, Blood and dust 27,
  Losing is Fun 22.)
- The shown mood moves toward the target at most **+12 per hour rising, −8 per hour falling**. Asleep or
  unconscious, it doesn't move.
- **Break thresholds** (normal pawn): **35% minor, 20% major, 5% extreme**. Below a threshold there's a random
  chance of a break each tick; a pawn must be awake and able to move to break. Traits shift the thresholds.
- RimMCP: `get_pawn <id> detail=normal` → `mood.level` (current, 0–1), `mood.instantLevel` (the target),
  `mood.thoughts[]` (`defName`, `label`, `moodOffset`). Colony-wide: `get_colony_status` → `mood.average`,
  `mood.lowMood`.

**Worked example (this colony, day 4, trial 5):** 37 base + 10 Initial optimism − 4 Slept outside − 4 Slept in the
cold − 5 Rebuffed − 3 Ate without table... The +10 optimism **expires** (see below), so a colony that looks fine
on day 3 can slide toward 35% by day 8 with nothing new going wrong. Plan to replace it.

## Thought values (the common early-game ones)

Positive offsets add to the 37 base; to stay above the 35% minor-break line, the sum of all thoughts must stay
above about −2.

### Temporary, from the start
| Thought | Mood | Notes |
|---|---|---|
| Initial optimism | +10 | Starting colonists only; fades over the first days (verify duration in game). Replace it before it goes. |
| Initial hope | +5 | Weaker variant |
| Crashed together | 0 | Opinion, not mood |

### Expectations (always on; set by colony wealth)
Low wealth gives *high* mood: very low expectations ≈ +24 to +30 early on. As wealth grows, expectations rise
(+18, +12, +6, 0), quietly removing up to 30 mood. **Wealth costs mood twice**: lower expectations bonus
and bigger raids. Don't hoard what you don't use.

### Eating (memories, last about a day)
| Thought | Mood | Fix |
|---|---|---|
| Ate lavish meal | +12 | Lavish meal (needs cooking skill 8+... verify) |
| Ate fine meal | +5 | Meat + vegetable; cook skill 6+ |
| Ate simple meal | 0 | The baseline to aim for |
| Ate nutrient paste | −4 | |
| Ate raw food | −7 | Cook everything; berries are exempt |
| Ate rotten food | −10 | Store food under a roof; freeze it |
| Ate kibble / corpse | −12 | Never |
| **Ate without table** | **−3** | A table (any) with a chair, reachable from where they eat |
| Decent dining room … wondrous | +2 … +8 | Eat at a table *inside a room* whose impressiveness is ≥ 40 (see rooms.md) |

### Sleeping (memories, last until next sleep)
| Thought | Mood | Fix |
|---|---|---|
| **Slept outside** | −4 | Bed in an enclosed, roofed room |
| Slept on ground | −4 | A bed, not a sleeping spot |
| **Slept in the cold** / heat | −4 | Bedroom temperature in the comfortable range (≈ 16–26 °C for most) |
| Disturbed sleep | −1 (stacks) | Don't give orders to sleeping pawns; separate bedrooms |
| **Barracks** (shared bedroom) awful/dull/mediocre/decent | **−7 / −5 / −4 / −3** | Give each colonist their own bedroom |
| Barracks slightly impressive / impressive | −2 / −1 | |
| **Bedroom** awful / mediocre / decent / slightly impressive / impressive | **−2 / +1 / +2 / +3 / +4** | (dull: 0) |

A private bedroom beats a shared one by **5–9 mood per colonist** at the same quality. Lovers sharing one bed
don't make it a barracks.

### Needs (situational, while the need is in that band)
| Need | Bands → mood |
|---|---|
| Food | Hungry −6, ravenous −12, malnourished −20 … starving −44 |
| Rest | Drowsy −6, tired −12, exhausted −18 |
| **Recreation** | 0% starved −20 · 1–14% deprived −10 · 15–29% unfulfilled −5 · 70–84% satisfied +5 · ≥ 85% fully +10 |
| Comfort | uncomfortable −3 · comfortable +4 · quite +6 · extremely +8 · luxuriant +10 (sit on chairs/beds with comfort) |
| Beauty | hideous −15 · ugly −10 · unsightly −5 · pretty +5 · beautiful +10 · gorgeous +15 (average beauty of what they see) |
| Space | confined −10 · cramped −5 · spacious +5 (room size of where they spend time) |
| Outdoors | stuck indoors −1 … cabin fever −8 (needs time outside; work outside covers it early) |

Recreation is the biggest *controllable, continuous* lever: −20 to +10 is a 30-point swing.

### Misc memories
| Thought | Mood |
|---|---|
| Soaking wet (rain, outdoors) | −3 |
| Observed corpse / rotting corpse | −4 / −6 |
| Witnessed ally's death | −5 |
| Nuzzled (by an animal) | +4 to +6 |
| Rebuffed by someone | −5 (social, fades) |
| Tainted apparel (from the dead) | negative; don't wear it |

## Levers, ranked by mood gained per effort (early game)

1. **Own bedroom each** (+5 to +9 vs barracks; removes Slept outside/cold too, if roofed and warm). Small
   rooms are fine: a 3×4 interior with a bed is "rather tight", not cramped, and can reach mediocre/decent.
2. **Recreation**: a horseshoes pin (no research) plus walking/skygazing gets most colonists to satisfied
   (+5); two different types (horseshoes + Game-of-Ur/chess) avoid tolerance and get +10.
3. **Cook every meal** (removes −7 raw food) and **eat at a table** (removes −3).
4. **A dining/rec room that's at least "decent"** (impressiveness ≥ 40): +2 each for eating and for
   recreation, every day. Floors, cleanliness, a few nice things.
5. **Keep it pretty**: don't surround the base with ugly things. Barricades are beauty −3 each; corpses,
   blood, trash, unfinished frames are ugly. Floors and plants help.
6. **Comfort**: dining chairs (not stools), beds.
7. Fine meals (+5) once there's meat and a cook with 6+.

## Breaks: what to do

- **Minor** (food binge, sad wander, insulting spree, hide in room) are harmless enough: let them run.
- **Major/extreme** (tantrum, berserk, fire starting, catatonic, run wild) can destroy things or hurt people.
  Detection: `get_colony_status` `mood.lowMood`; alerts `Alert_MinorBreakRisk`, `Alert_MajorBreakRisk`,
  `Alert_ExtremeBreakRisk`; run events `mentalBreak`.
- A pawn asleep can't break. Ordering a pawn at extreme risk to bed buys hours, nothing more.
- The real fix is always the thought list: read `mood.thoughts`, sort by offset, remove the worst ones.
