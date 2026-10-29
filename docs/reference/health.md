# Health

## Bleeding and tending

- Wounds bleed; blood loss kills in **hours**. A downed colonist must be rescued to a bed and tended.
- **Tend** = a doctor treats wounds: stops bleeding, sets tend quality (which speeds healing and lowers
  infection risk). Medicine improves quality: none < herbal (`MedicineHerbal`) < industrial (`MedicineIndustrial`)
  < glitterworld. Starting medicine is forbidden: unforbid it (`designate kind=unforbid`).
- A **drafted** doctor can tend a downed pawn where they lie (fastest in an emergency): draft, then order a
  tend. In this project `managers/medical.py` does this.
- Doctoring must be **enabled** for someone, ideally the best Medical skill. Self-tend is a per-pawn setting.
- Bed rest heals faster than wandering. Patients go to bed by themselves if Patient work is on.

## Infection and disease

- A wound can become **infected** a few days after injury; good tend quality makes it less likely. Infection
  must be out-healed by immunity: keep the patient in bed, fed, and tended daily.
- Common early diseases: flu, plague, malaria (in some biomes), food poisoning (short; from dirty kitchens).
  All are "race against immunity": tend once a day, rest.
- Detect: `get_pawn <id> detail=normal` → `health.hediffs[]`, `health.summaryHealthPercent`, `health.pain`;
  colony: `get_colony_status` → `medical.downed`, `medical.bleeding`.

## Pain, scars, and mood

- Pain lowers mood (and consciousness at high levels). Old scars can ache permanently ("Stab scar").
- A downed or bed-ridden colonist still has needs: recreation drops; visitors can cheer them up.

## Rules for code

- Never let a bleeding colonist go untended: if no doctor is free, any colonist tending beats none.
- Don't rescue someone already in a bed; don't send a rescuer into an ongoing fight.
- Keep medicine **inside, unforbidden, near beds**.
