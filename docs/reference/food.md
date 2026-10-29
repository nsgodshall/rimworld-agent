# Food

## How much is enough

- A colonist eats about **1.6–2.0 nutrition a day** (this colony: `food.eatenPerDay` 5.6 for 3 colonists).
- The game counts **only stored food**: in a stockpile or on a shelf (`get_colony_status` → `food.daysLeft`,
  `food.storedNutrition`). Food lying in a field or on the ground is 0 days. The "Low food" alert and the
  `lowFood` run event fire below **4 nutrition per colonist**.
- Targets: never below 2 days stored after day one; build toward 10+ days by the first winter, and the
  wiki's "a thousand units of food stored" (raw crops) before winter in seasonal biomes.

## Crops (temperate, normal soil)

| Crop | defName | Grows (100% fertility) | Notes |
|---|---|---|---|
| Rice | `Plant_Rice` | fast (≈ 3 days at full growth speed, longer in practice) | Best early: quick, steady. Min fertility 0.7; 3.7× the work of corn per nutrition. Nutrition 0.175 per unit. |
| Potato | `Plant_Potato` | medium | Tolerates poor soil (gravel) best; good second crop |
| Corn | `Plant_Corn` | slow (≈ 11 days) | Least work per nutrition; big single harvests; risky if blight or cold hits |
| Strawberry | `Plant_Strawberry` | medium | Can be eaten raw without the raw-food penalty |
| Healroot | `Plant_Healroot` | slow | Needs research to sow (verify); makes herbal medicine |

- **Sow area**: roughly **25–40 tiles of rice per colonist** in normal soil to feed them on cooked simple meals;
  rich soil (`:` on the map view, "rich soil" in the legend) is about 1.4× fertility: use it first.
- Crops need **growing season** (temperature above freezing) and light. Outdoor crops die in a cold snap or
  winter; harvest what's mature before then.
- Growing and Plant cutting must be **enabled** for colonists to sow and harvest (see work.md). A field nobody
  is allowed to tend is wasted.
- Sowing and harvesting are manual labour; one grower can keep ~60–80 rice tiles going alongside other work.

## Cooking

- **Raw food is −7 mood** (berries exempt). Cook everything.
- Simple meal (`MealSimple`, recipe `CookMealSimple`): **0.5 raw nutrition in, 0.9 nutrition out**: cooking
  nearly doubles food value. Fine meal (`MealFine`, `CookMealFine`): meat + vegetable, cook skill 6+, +5 mood.
- Stations: `Campfire` (no research, wood fuel, slow), `FueledStove` (80 steel, wood fuel), electric stove
  (needs power and research). A stove needs a **bill**: `add_bill_to_workshop ... repeatModeDefName=TargetCount
  targetCount=N` keeps N meals stocked. Without a bill nothing gets cooked.
- **Food poisoning** comes from a dirty kitchen (no floor, blood, dirt) or a poor cook (skill < 3–4). It makes
  pawns vomit and stops work for a while. Put the stove in a room with a floor.
- Meals spoil: simple meals last a few days unfrozen; raw rice keeps longer. Keep the meal target modest
  (a day or two per colonist) until there's a freezer.

## Other food

- **Hunting**: mark animals with `designate`... (hunting is a designation kind in game; verify RimMCP support).
  Never hunt **boomalopes/boomrats** (explode, start fires), **predators** or **animals in herds** (they can
  revenge as a group). Deer, hares, squirrels are safe. Meat rots fast: butcher at a `TableButcher`, then cook.
- **Foraging**: berry bushes (`Plant_Berry`, wild) can be harvested with `designate kind=harvest`.
- **Starting rations**: survival meals (`MealSurvivalPack`) never spoil; keep them for emergencies and caravans.

## Storage

- Everything except metal deteriorates outdoors. Put the main stockpile **inside a roofed room**.
- Freezer: an enclosed room with a cooler (power) set to −5 °C, food stockpile inside, one door. Shelves hold
  3 stacks per tile.
- Animals (wild or tame) eat crops and stored food if they can reach them.
