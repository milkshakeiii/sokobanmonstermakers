# Monster Workshop Backend Patch Plan

## Goals
Restore MonsterMakers gameplay depth in the gridtickmultiplayer module while keeping everything server-authoritative and data-driven. Frontend work is deferred.

## Decisions Locked In
- Gathering spots behave like infinite workshops with no inputs; monsters still spend time and use skills to harvest.
- `roll_for_raw_material_type` stays as an explicit TODO for now; gathering spots produce a fixed raw material type.
- Durability defaults match Django: workshops = 1000, everything else = 100 (TODO for tool-specific durability).
- Share system must match Django semantics exactly.
- Default item size is 2x1 (double-width); workshop slots declare max size.
- Renown upkeep must keep a 200-renown floor.

## Phased Workstreams (priority order)

### Phase 1: Data & Tech Tree Parity (High) [DONE]
- Replace/regen `data/tech_tree/good_types.json` with full MonsterMakers fields:
  - `input_goods_tags_carryover`, `tools_weights`, `secondary_applied_skills`, `destabilizer_skills`,
    `value_added_shares`, `quantity`, `raw_material_density`, `workshop_task_slots`, `workshop_task_tags`, `shelf_life`.
- Keep field names aligned with Django to simplify porting formulas.
- Add any missing enums/skill mappings needed to interpret the tech tree.
- Add data-driven monster types (e.g., `data/monster_types.json`) and load at runtime.

### Phase 2: Item Lineage + Value/Weight (High) [DONE]
- Add item metadata fields for lineage:
  - `carried_over_tags`, `raw_materials`, `raw_material_max_depth`, `shares`.
- Implement `calculate_weight` equivalent:
  - Raw materials use `raw_material_density * storage_volume`.
  - Refined goods use average density of raw materials in lineage.
- Implement `calculate_value` equivalent:
  - Raw materials: `base_value * (quality + 0.5) ** 0.5`.
  - Refined goods: `(sum raw base values) * (quality + 0.5) ** (0.5 + 0.5 * max_depth)`.
- Implement `raw_materials_and_max_depth` by walking input lineage.

### Phase 3: Full Crafting Rolls + Skills (High) [DONE]
- Port Django `roll_for_quality` and `roll_for_quantity` logic:
  - Transferable skill count, secondary skill pruning, tool quality weighting, destabilizer sigma, RNG.
- Port `effective_*` monster formulas:
  - `effective_ability`, quality/quantity/time/value modifiers.
- Port full learning + forgetting on craft completion:
  - specific, primary, secondary learning; forgetting accumulation.
- Keep existing autorepeat flow but ensure each craft yields identical gameplay effects to Django batches.

### Phase 4: Share System + Scoring (High) [DONE]
- Implement share accounting identical to Django:
  - Tool shares distributed by tool’s own share distribution and `tools_weights`.
  - Workshop contribution uses weight 8 (as in Django).
  - Producer shares use `value_added_shares`.
  - Carry over all input good shares to output good.
- Delivery scoring uses value-based renown and dropoff tag filtering.
- Add renown floor when applying upkeep: never drop below 200.

### Phase 5: Gathering Spots (High) [DONE]
- Add `gathering_spot` entity type or workshop subtype:
  - Fixed output good type per spot.
  - No inputs; uses crafting duration/skills for harvest.
  - `roll_for_raw_material_type` remains TODO.

### Phase 6: Size Rules + Containers (High/Med) [DONE]
- Item sizes default to 2x1; allow per-item size overrides in metadata.
- Workshop slot rules include max size per slot; enforce on deposit.
- Containers (pushable dispensers/containers) as future-capable entities.

### Phase 7: Wagon Constraints (Med) [DONE]
- Wagons should not be directly pushable unless hitched by the mover.
- Preserve wagon load/unload mechanics and stored-item movement.

### Phase 8: World Data Expansion (Med)
- Multiple zones with towns + wilderness, regional specialization, gathering sites.
- Roads/paths with signposts linking zones.
- Delivery buildings per town, all defined in `data/zones/*.json`.

## Files To Touch (initial)
- `monster_workshop_game/main.py`
- `data/tech_tree/good_types.json`
- `data/monster_types.json` (new)
- `data/zones/*.json`
- `data/workshops.json` or embed in zones (optional)

## Notes / TODOs
- `roll_for_raw_material_type` remains TODO (fixed output for now).
- Tool durability per type remains TODO (use 100 default).
- Equipment system deferred.
