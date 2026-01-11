"""Monster Workshop game module for gridtickmultiplayer."""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from grid_backend.game_logic.protocol import (
    FrameworkAPI,
    Intent,
    TickResult,
    EntityCreate,
    EntityUpdate,
)
from grid_backend.models.entity import Entity

logger = logging.getLogger(__name__)

KIND_WORLD = "world_marker"
KIND_COMMUNE = "commune"
KIND_MONSTER = "monster"
KIND_ITEM = "item"
KIND_WORKSHOP = "workshop"
KIND_GATHERING = "gathering_spot"
KIND_DISPENSER = "dispenser"
KIND_WAGON = "wagon"
KIND_TERRAIN = "terrain_block"
KIND_SIGNPOST = "signpost"
KIND_DELIVERY = "delivery"

BLOCKING_KINDS = {
    KIND_MONSTER,
    KIND_ITEM,
    KIND_WORKSHOP,
    KIND_GATHERING,
    KIND_DISPENSER,
    KIND_WAGON,
    KIND_TERRAIN,
    KIND_DELIVERY,
}

PUSHABLE_KINDS = {
    KIND_ITEM,
}

DIR_TO_DELTA = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}

ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")
DEFAULT_ITEM_SIZE = (2, 1)
DEFAULT_CONTAINER_CAPACITY = 20

GAME_TIME_MULTIPLIER = 30
UPKEEP_CYCLE_DAYS = 28
STARTING_RENOWN = 1000
SKILL_DECAY_INTERVAL_TICKS = 60

DEFAULT_MONSTER_TYPES = {
    "cyclops": {
        "name": "Cyclops",
        "cost": 100,
        "stats": {"str": 18, "dex": 10, "con": 16, "int": 8, "wis": 10, "cha": 8},
        "body_cap": 100,
        "mind_cap": 100,
    },
    "elf": {
        "name": "Elf",
        "cost": 150,
        "stats": {"str": 8, "dex": 16, "con": 10, "int": 18, "wis": 12, "cha": 10},
        "body_cap": 50,
        "mind_cap": 150,
    },
    "goblin": {
        "name": "Goblin",
        "cost": 50,
        "stats": {"str": 8, "dex": 18, "con": 10, "int": 10, "wis": 8, "cha": 16},
        "body_cap": 150,
        "mind_cap": 50,
    },
    "orc": {
        "name": "Orc",
        "cost": 2000,
        "stats": {"str": 16, "dex": 10, "con": 18, "int": 8, "wis": 10, "cha": 8},
        "body_cap": 150,
        "mind_cap": 50,
    },
    "troll": {
        "name": "Troll",
        "cost": 1,
        "stats": {"str": 12, "dex": 8, "con": 14, "int": 8, "wis": 10, "cha": 8},
        "body_cap": 1500,
        "mind_cap": 1500,
    },
}

DEFAULT_TRANSFERABLE_SKILLS = [
    "mathematics",
    "science",
    "engineering",
    "writing",
    "visual_art",
    "music",
    "handcrafts",
    "athletics",
    "outdoorsmonstership",
    "social",
]

DEFAULT_APPLIED_SKILLS = [
    "hauling",
    "wagon_driving",
    "sericulture",
    "spinning",
    "weaving",
    "harvesting",
    "textiles",
    "threshing",
    "gathering",
    "dyeing",
    "prospecting",
    "chemistry",
    "milling",
    "confectionery",
    "firing",
    "pottery",
    "painting",
    "casting",
    "stone_carving",
    "carpentry",
    "blacksmithing",
]


class MonsterWorkshopGame:
    """Gridtickmultiplayer module for Monster Workshop."""

    def __init__(self) -> None:
        self._zone_defs = self._load_zone_defs()
        self._zone_id_to_def: dict[UUID, dict[str, Any]] = {}
        self._zone_sizes: dict[UUID, tuple[int, int]] = {}
        self._initialized_zones: set[UUID] = set()
        self._good_types = self._load_good_types()
        self._monster_types = self._load_monster_types()
        self._skill_defs = self._load_skill_defs()
        self._transferable_skills = self._skill_defs.get("transferable_skills", DEFAULT_TRANSFERABLE_SKILLS)

    async def on_init(self, framework: FrameworkAPI) -> None:
        """Ensure zones exist and map IDs to definitions."""
        if not self._zone_defs:
            self._zone_defs = [self._default_zone_def()]

        for zone_def in self._zone_defs:
            name = zone_def.get("name", "Starting Village")
            width = int(zone_def.get("width", 100))
            height = int(zone_def.get("height", 100))

            zone = await framework.get_zone_by_name(name)
            if zone is None:
                zone = await framework.create_zone(
                    name=name,
                    width=width,
                    height=height,
                    metadata={"source": "monster_workshop"},
                )
                logger.info("Created zone '%s' (%s)", name, zone.id)
            else:
                logger.info("Using existing zone '%s' (%s)", name, zone.id)

            self._zone_id_to_def[zone.id] = zone_def
            self._zone_sizes[zone.id] = (zone.width, zone.height)

        logger.info("Monster Workshop module initialized")

    def on_tick(
        self,
        zone_id: UUID,
        entities: list[Entity],
        intents: list[Intent],
        tick_number: int,
    ) -> TickResult:
        creates: list[EntityCreate] = []
        updates: list[EntityUpdate] = []
        deletes: list[UUID] = []
        events: list[dict[str, Any]] = []
        active_pushes: dict[UUID, UUID] = {}
        touched_dispensers: set[UUID] = set()

        zone_def = self._zone_id_to_def.get(zone_id)
        zone_width, zone_height = self._zone_sizes.get(zone_id, (100, 100))

        if zone_id not in self._initialized_zones:
            if not self._find_world_marker(entities):
                creates.extend(self._bootstrap_zone(zone_def, zone_width, zone_height))
            self._initialized_zones.add(zone_id)

        entity_map = {entity.id: entity for entity in entities}

        for intent in intents:
            action = intent.data.get("action")

            if action in ("move", "push"):
                self._handle_move(
                    intent=intent,
                    entities=entities,
                    entity_map=entity_map,
                    creates=creates,
                    updates=updates,
                    events=events,
                    deletes=deletes,
                    zone_width=zone_width,
                    zone_height=zone_height,
                    zone_def=zone_def,
                    active_pushes=active_pushes,
                    touched_dispensers=touched_dispensers,
                )

            elif action == "spawn_monster":
                create, event = self._handle_spawn_monster(
                    intent=intent,
                    entities=entities,
                    zone_def=zone_def,
                    zone_width=zone_width,
                    zone_height=zone_height,
                    creates=creates,
                    updates=updates,
                )
                if create is not None:
                    creates.append(create)
                if event is not None:
                    events.append(event)

            elif action == "owner_disconnect":
                self._handle_owner_disconnect(
                    intent=intent,
                    entities=entities,
                    updates=updates,
                    events=events,
                )

            elif action == "recording_start":
                self._handle_recording_start(intent, entity_map, updates, events)

            elif action == "recording_stop":
                self._handle_recording_stop(intent, entity_map, updates, events)

            elif action == "autorepeat_start":
                self._handle_autorepeat_start(intent, entity_map, updates, events)

            elif action == "autorepeat_stop":
                self._handle_autorepeat_stop(intent, entity_map, updates, events)

            elif action == "select_recipe":
                self._handle_select_recipe(intent, entity_map, updates, events, tick_number, entities)

            elif action == "interact":
                self._handle_interact(intent, entities, entity_map, events)

            elif action == "hitch_wagon":
                self._handle_hitch_wagon(intent, entities, entity_map, updates, events)

            elif action == "unhitch_wagon":
                self._handle_unhitch_wagon(intent, entities, entity_map, updates, events)

            elif action == "unload_wagon":
                self._handle_unload_wagon(
                    intent=intent,
                    entities=entities,
                    entity_map=entity_map,
                    updates=updates,
                    events=events,
                    zone_width=zone_width,
                    zone_height=zone_height,
                    zone_def=zone_def,
                )

            else:
                if action:
                    events.append({
                        "type": "warning",
                        "message": f"Unsupported action: {action}",
                        "target_player_id": str(intent.player_id),
                    })

        self._process_autorepeat(
            entities=entities,
            creates=creates,
            updates=updates,
            events=events,
            zone_width=zone_width,
            zone_height=zone_height,
            zone_def=zone_def,
            deletes=deletes,
            active_pushes=active_pushes,
            touched_dispensers=touched_dispensers,
        )

        self._process_crafting(
            entities=entities,
            updates=updates,
            creates=creates,
            deletes=deletes,
            events=events,
            tick_number=tick_number,
            zone_def=zone_def,
        )

        self._process_monster_economy(
            entities=entities,
            updates=updates,
            creates=creates,
            events=events,
            tick_number=tick_number,
        )

        if active_pushes:
            self._clear_active_pushes(active_pushes, entity_map, updates)

        if touched_dispensers:
            self._sync_dispensers(touched_dispensers, entities, updates)

        extras: dict[str, Any] = {}
        if events:
            extras["events"] = events

        return TickResult(
            entity_creates=creates,
            entity_updates=updates,
            entity_deletes=deletes,
            extras=extras,
        )

    def get_player_state(
        self,
        zone_id: UUID,
        player_id: UUID,
        full_state: dict[str, Any],
    ) -> dict[str, Any]:
        player_state = dict(full_state)
        events = full_state.get("events", [])
        if events:
            filtered = []
            for event in events:
                target = event.get("target_player_id")
                if target and target != str(player_id):
                    continue
                filtered.append(event)
            player_state["events"] = filtered
        player_state["viewer_id"] = str(player_id)
        return player_state

    def _handle_move(
        self,
        intent: Intent,
        entities: list[Entity],
        entity_map: dict[UUID, Entity],
        creates: list[EntityCreate],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
        deletes: list[UUID],
        zone_width: int,
        zone_height: int,
        zone_def: dict[str, Any] | None,
        active_pushes: dict[UUID, UUID],
        touched_dispensers: set[UUID],
    ) -> None:
        entity_id = self._parse_entity_id(intent.data.get("entity_id"))
        if entity_id is None:
            return

        entity = entity_map.get(entity_id)
        if entity is None:
            return

        if entity.owner_id != intent.player_id:
            return

        if self._entity_kind(entity) != KIND_MONSTER:
            return

        dx, dy = self._intent_to_delta(intent.data)
        if dx == 0 and dy == 0:
            return

        new_x = entity.x + dx
        new_y = entity.y + dy

        if not self._is_in_bounds(new_x, new_y, entity, zone_width, zone_height):
            return

        if self._is_terrain_blocked(zone_def, new_x, new_y):
            return

        blocker = self._find_blocker(entities, entity, new_x, new_y)
        if blocker is None:
            old_x, old_y = entity.x, entity.y
            self._apply_move(entity, new_x, new_y, updates)
            self._maybe_move_hitched_wagon(entity, old_x, old_y, entities, updates)
            self._record_action(entity, "move", dx, dy, updates)
            return

        if self._entity_kind(blocker) not in PUSHABLE_KINDS:
            return

        if blocker.metadata_ and blocker.metadata_.get("is_stored"):
            return

        if self._is_being_pushed_by_other(blocker, entity.id):
            events.append({
                "type": "blocked",
                "message": "Item is already being pushed",
                "target_player_id": str(intent.player_id),
            })
            return

        can_push, reason = self._can_monster_push(entity, blocker)
        if not can_push:
            events.append({
                "type": "blocked",
                "message": reason,
                "target_player_id": str(intent.player_id),
            })
            return

        self._mark_active_push(blocker, entity.id, updates, active_pushes)

        if not self._attempt_push(
            entities=entities,
            mover=entity,
            pushed=blocker,
            dx=dx,
            dy=dy,
            creates=creates,
            updates=updates,
            deletes=deletes,
            zone_width=zone_width,
            zone_height=zone_height,
            zone_def=zone_def,
            events=events,
            touched_dispensers=touched_dispensers,
        ):
            self._clear_active_push(blocker, updates, active_pushes)
            return

        self._clear_active_push(blocker, updates, active_pushes)
        self._record_action(entity, "push", dx, dy, updates)
        events.append({
            "type": "push",
            "entity_id": str(blocker.id),
            "target_player_id": str(intent.player_id),
        })

    def _handle_spawn_monster(
        self,
        intent: Intent,
        entities: list[Entity],
        zone_def: dict[str, Any] | None,
        zone_width: int,
        zone_height: int,
        creates: list[EntityCreate],
        updates: list[EntityUpdate],
    ) -> tuple[EntityCreate | None, dict[str, Any] | None]:
        monster_type = (intent.data.get("monster_type") or "goblin").lower()
        name = intent.data.get("name") or "Monster"
        definition = self._monster_types.get(monster_type)

        if definition is None:
            return None, {
                "type": "error",
                "message": f"Unknown monster type: {monster_type}",
                "target_player_id": str(intent.player_id),
            }

        transferable_requested = intent.data.get("transferable_skills")
        if not isinstance(transferable_requested, list):
            return None, {
                "type": "error",
                "message": "Transferable skills must be a list",
                "target_player_id": str(intent.player_id),
            }
        if len(transferable_requested) != 3:
            return None, {
                "type": "error",
                "message": "Must select exactly 3 transferable skills",
                "target_player_id": str(intent.player_id),
            }
        skill_lookup = {
            str(skill).strip().lower().replace(" ", "_"): str(skill)
            for skill in self._transferable_skills
        }
        invalid_skills = []
        transferable_skills: list[str] = []
        for skill in transferable_requested:
            if not skill:
                invalid_skills.append(str(skill))
                continue
            key = str(skill).strip().lower().replace(" ", "_")
            if key in skill_lookup:
                transferable_skills.append(skill_lookup[key])
            else:
                invalid_skills.append(str(skill))

        if invalid_skills:
            return None, {
                "type": "error",
                "message": f"Invalid transferable skills: {', '.join(invalid_skills)}",
                "target_player_id": str(intent.player_id),
            }

        if len({skill.lower() for skill in transferable_skills}) != len(transferable_skills):
            return None, {
                "type": "error",
                "message": "Duplicate transferable skills selected",
                "target_player_id": str(intent.player_id),
            }

        commune = self._ensure_commune(
            entities=entities,
            creates=creates,
            owner_id=intent.player_id,
        )
        commune_metadata = self._get_commune_metadata(commune)
        cost = int(definition.get("cost", 0))
        adjusted_cost = self._get_adjusted_cost(cost, commune_metadata)
        renown = int(commune_metadata.get("renown", STARTING_RENOWN))

        if renown < adjusted_cost:
            return None, {
                "type": "error",
                "message": f"Not enough renown ({renown} < {adjusted_cost})",
                "target_player_id": str(intent.player_id),
            }

        commune_metadata["renown"] = renown - adjusted_cost
        commune_metadata["total_renown_spent"] = int(commune_metadata.get("total_renown_spent", 0)) + adjusted_cost
        self._set_commune_metadata(commune, commune_metadata, updates)

        spawn_x, spawn_y = self._choose_spawn_point(entities, zone_def, zone_width, zone_height)
        metadata = self._build_monster_metadata(name, monster_type, definition)
        metadata["skills"]["transferable"] = transferable_skills

        return (
            EntityCreate(
                x=spawn_x,
                y=spawn_y,
                width=1,
                height=1,
                owner_id=intent.player_id,
                metadata=metadata,
            ),
            {
                "type": "spawned",
                "message": f"Spawned {name}",
                "target_player_id": str(intent.player_id),
            },
        )

    def _handle_owner_disconnect(
        self,
        intent: Intent,
        entities: list[Entity],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
    ) -> None:
        player_id_str = intent.data.get("player_id")
        player_id = self._parse_entity_id(player_id_str)
        if player_id is None:
            return

        for entity in entities:
            if entity.owner_id == player_id and self._entity_kind(entity) == KIND_MONSTER:
                metadata = dict(entity.metadata_ or {})
                metadata["online"] = False
                self._apply_metadata(entity, metadata, updates)

        events.append({
            "type": "disconnect",
            "message": "Player disconnected",
            "target_player_id": str(player_id),
        })

    def _handle_recording_start(
        self,
        intent: Intent,
        entity_map: dict[UUID, Entity],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
    ) -> None:
        monster = self._get_owned_monster(intent, entity_map)
        if monster is None:
            return

        metadata = dict(monster.metadata_ or {})
        current_task = dict(metadata.get("current_task") or {})
        current_task["is_recording"] = True
        current_task["is_playing"] = False
        current_task["actions"] = []
        metadata["current_task"] = current_task
        self._apply_metadata(monster, metadata, updates)
        events.append({
            "type": "recording_started",
            "target_player_id": str(intent.player_id),
        })

    def _handle_recording_stop(
        self,
        intent: Intent,
        entity_map: dict[UUID, Entity],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
    ) -> None:
        monster = self._get_owned_monster(intent, entity_map)
        if monster is None:
            return

        metadata = dict(monster.metadata_ or {})
        current_task = dict(metadata.get("current_task") or {})
        current_task["is_recording"] = False
        metadata["current_task"] = current_task
        self._apply_metadata(monster, metadata, updates)
        events.append({
            "type": "recording_stopped",
            "target_player_id": str(intent.player_id),
        })

    def _handle_autorepeat_start(
        self,
        intent: Intent,
        entity_map: dict[UUID, Entity],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
    ) -> None:
        monster = self._get_owned_monster(intent, entity_map)
        if monster is None:
            return

        metadata = dict(monster.metadata_ or {})
        current_task = dict(metadata.get("current_task") or {})
        actions = current_task.get("actions") or []
        if not actions:
            events.append({
                "type": "error",
                "message": "No recorded actions to replay",
                "target_player_id": str(intent.player_id),
            })
            return

        current_task["is_playing"] = True
        current_task["is_recording"] = False
        current_task["play_index"] = 0
        metadata["current_task"] = current_task
        self._apply_metadata(monster, metadata, updates)
        events.append({
            "type": "autorepeat_started",
            "target_player_id": str(intent.player_id),
        })

    def _handle_autorepeat_stop(
        self,
        intent: Intent,
        entity_map: dict[UUID, Entity],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
    ) -> None:
        monster = self._get_owned_monster(intent, entity_map)
        if monster is None:
            return

        metadata = dict(monster.metadata_ or {})
        current_task = dict(metadata.get("current_task") or {})
        current_task["is_playing"] = False
        metadata["current_task"] = current_task
        self._apply_metadata(monster, metadata, updates)
        events.append({
            "type": "autorepeat_stopped",
            "target_player_id": str(intent.player_id),
        })

    def _handle_select_recipe(
        self,
        intent: Intent,
        entity_map: dict[UUID, Entity],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
        tick_number: int,
        entities: list[Entity],
    ) -> None:
        workshop_id = self._parse_entity_id(intent.data.get("workshop_id"))
        if workshop_id is None:
            return

        recipe_id = intent.data.get("recipe_id")
        workshop = entity_map.get(workshop_id)
        if workshop is None or self._entity_kind(workshop) not in (KIND_WORKSHOP, KIND_GATHERING):
            return

        metadata = dict(workshop.metadata_ or {})
        gathering_good = metadata.get("gathering_good_type")
        if gathering_good:
            if recipe_id and self._normalize_good_type_key(recipe_id) != self._normalize_good_type_key(gathering_good):
                events.append({
                    "type": "error",
                    "message": f"Gathering spot is locked to {gathering_good}",
                    "target_player_id": str(intent.player_id),
                })
                return
            recipe_id = gathering_good

        recipe_entry = self._get_recipe_entry(recipe_id)
        if recipe_entry is None:
            events.append({
                "type": "error",
                "message": "Unknown recipe",
                "target_player_id": str(intent.player_id),
            })
            return

        is_gathering = self._is_gathering_spot(workshop)
        if is_gathering and not self._is_raw_material_entry(recipe_entry):
            events.append({
                "type": "error",
                "message": "Gathering spots can only produce raw materials",
                "target_player_id": str(intent.player_id),
            })
            return

        workshop_type = metadata.get("workshop_type", "general")
        requires_workshop = recipe_entry.get("requires_workshop")
        if isinstance(requires_workshop, str):
            if requires_workshop != workshop_type:
                events.append({
                    "type": "error",
                    "message": f"Recipe requires {requires_workshop}",
                    "target_player_id": str(intent.player_id),
                })
                return
        elif requires_workshop and self._entity_kind(workshop) not in (KIND_WORKSHOP, KIND_GATHERING):
            events.append({
                "type": "error",
                "message": "Recipe requires a workshop",
                "target_player_id": str(intent.player_id),
            })
            return

        if is_gathering:
            input_items = []
            tool_items = self._get_gathering_tools(entities, workshop)
            _, missing_tools = self._find_missing_requirements(recipe_entry, [], tool_items)
            missing_inputs = []
        else:
            input_items, tool_items = self._get_workshop_items(entities, workshop)
            missing_inputs, missing_tools = self._find_missing_requirements(
                recipe_entry,
                input_items,
                tool_items,
            )

        metadata["selected_recipe_id"] = recipe_entry.get("name")
        metadata["selected_recipe_name"] = recipe_entry.get("name")
        metadata["missing_inputs"] = missing_inputs
        metadata["missing_tools"] = missing_tools

        crafter = self._get_owned_monster(intent, entity_map)
        if crafter is not None:
            metadata["crafter_monster_id"] = str(crafter.id)

        can_craft = not missing_inputs and not missing_tools
        if can_craft:
            duration = self._calculate_crafting_duration(recipe_entry, crafter)
            metadata["is_crafting"] = True
            metadata["crafting_started_tick"] = tick_number
            metadata["crafting_duration"] = duration
            metadata["base_duration"] = recipe_entry.get("production_time", duration)
            metadata["primary_applied_skill"] = recipe_entry.get("primary_applied_skill")
            events.append({
                "type": "crafting_started",
                "workshop_id": str(workshop.id),
                "recipe_name": recipe_entry.get("name"),
                "target_player_id": str(intent.player_id),
            })
        else:
            metadata["is_crafting"] = False
            metadata.pop("crafting_started_tick", None)
            events.append({
                "type": "crafting_blocked",
                "workshop_id": str(workshop.id),
                "missing_inputs": missing_inputs,
                "missing_tools": missing_tools,
                "target_player_id": str(intent.player_id),
            })

        self._apply_metadata(workshop, metadata, updates)

    def _handle_interact(
        self,
        intent: Intent,
        entities: list[Entity],
        entity_map: dict[UUID, Entity],
        events: list[dict[str, Any]],
    ) -> None:
        monster = self._get_owned_monster(intent, entity_map)
        if monster is None:
            return

        target = None
        target_id = self._parse_entity_id(intent.data.get("entity_id"))
        if target_id:
            target = entity_map.get(target_id)
        if target is None:
            target = self._find_adjacent_entity(monster, entities)

        if target is None:
            events.append({
                "type": "message",
                "message": "Nothing to interact with",
                "target_player_id": str(intent.player_id),
            })
            return

        events.append({
            "type": "interact",
            "entity_id": str(target.id),
            "target_player_id": str(intent.player_id),
        })

    def _handle_hitch_wagon(
        self,
        intent: Intent,
        entities: list[Entity],
        entity_map: dict[UUID, Entity],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
    ) -> None:
        monster = self._get_owned_monster(intent, entity_map)
        if monster is None:
            return

        metadata = dict(monster.metadata_ or {})
        current_task = dict(metadata.get("current_task") or {})
        if current_task.get("hitched_wagon_id"):
            events.append({
                "type": "error",
                "message": "Monster is already hitched to a wagon",
                "target_player_id": str(intent.player_id),
            })
            return

        wagon = self._find_adjacent_wagon(monster, entities)
        if wagon is None:
            events.append({
                "type": "error",
                "message": "No wagon adjacent to monster",
                "target_player_id": str(intent.player_id),
            })
            return

        wagon_metadata = dict(wagon.metadata_ or {})
        hitched_by = wagon_metadata.get("hitched_by")
        if hitched_by and hitched_by != str(monster.id):
            events.append({
                "type": "error",
                "message": "Wagon is already hitched",
                "target_player_id": str(intent.player_id),
            })
            return

        current_task["hitched_wagon_id"] = str(wagon.id)
        metadata["current_task"] = current_task
        self._apply_metadata(monster, metadata, updates)

        wagon_metadata["hitched_by"] = str(monster.id)
        self._apply_metadata(wagon, wagon_metadata, updates)

        events.append({
            "type": "wagon_hitched",
            "wagon_id": str(wagon.id),
            "target_player_id": str(intent.player_id),
        })

    def _handle_unhitch_wagon(
        self,
        intent: Intent,
        entities: list[Entity],
        entity_map: dict[UUID, Entity],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
    ) -> None:
        monster = self._get_owned_monster(intent, entity_map)
        if monster is None:
            return

        metadata = dict(monster.metadata_ or {})
        current_task = dict(metadata.get("current_task") or {})
        hitched_id = self._parse_entity_id(current_task.get("hitched_wagon_id"))
        if hitched_id is None:
            events.append({
                "type": "error",
                "message": "Monster is not hitched to any wagon",
                "target_player_id": str(intent.player_id),
            })
            return

        wagon = next((e for e in entities if e.id == hitched_id), None)
        if wagon is not None and self._entity_kind(wagon) == KIND_WAGON:
            wagon_metadata = dict(wagon.metadata_ or {})
            if wagon_metadata.get("hitched_by") == str(monster.id):
                wagon_metadata.pop("hitched_by", None)
                self._apply_metadata(wagon, wagon_metadata, updates)

        current_task.pop("hitched_wagon_id", None)
        metadata["current_task"] = current_task
        self._apply_metadata(monster, metadata, updates)

        events.append({
            "type": "wagon_unhitched",
            "target_player_id": str(intent.player_id),
        })

    def _handle_unload_wagon(
        self,
        intent: Intent,
        entities: list[Entity],
        entity_map: dict[UUID, Entity],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
        zone_width: int,
        zone_height: int,
        zone_def: dict[str, Any] | None,
    ) -> None:
        monster = self._get_owned_monster(intent, entity_map)
        if monster is None:
            return

        metadata = dict(monster.metadata_ or {})
        current_task = dict(metadata.get("current_task") or {})
        hitched_id = self._parse_entity_id(current_task.get("hitched_wagon_id"))
        if hitched_id is None:
            events.append({
                "type": "error",
                "message": "Monster is not hitched to any wagon",
                "target_player_id": str(intent.player_id),
            })
            return

        wagon = next((e for e in entities if e.id == hitched_id), None)
        if wagon is None or self._entity_kind(wagon) != KIND_WAGON:
            events.append({
                "type": "error",
                "message": "Hitched wagon not found",
                "target_player_id": str(intent.player_id),
            })
            return

        stored_items = self._get_wagon_items(entities, wagon)
        if not stored_items:
            events.append({
                "type": "error",
                "message": "Wagon has no items to unload",
                "target_player_id": str(intent.player_id),
            })
            return

        unload_cell = self._find_unload_cell(wagon, entities, zone_width, zone_height, zone_def)
        if unload_cell is None:
            events.append({
                "type": "error",
                "message": "No space to unload wagon",
                "target_player_id": str(intent.player_id),
            })
            return

        item = stored_items[0]
        item_metadata = dict(item.metadata_ or {})
        item_metadata["is_stored"] = False
        item_metadata.pop("container_id", None)
        item_metadata.pop("stored_offset", None)
        item_metadata.pop("stored_role", None)

        unload_x, unload_y = unload_cell
        self._apply_move(item, unload_x, unload_y, updates)
        self._apply_metadata(item, item_metadata, updates)

        wagon_metadata = dict(wagon.metadata_ or {})
        loaded_ids = list(wagon_metadata.get("loaded_item_ids") or [])
        item_id = str(item.id)
        if item_id in loaded_ids:
            loaded_ids = [entry for entry in loaded_ids if entry != item_id]
        wagon_metadata["loaded_item_ids"] = loaded_ids
        wagon_metadata["loaded_item_count"] = len(loaded_ids)
        self._apply_metadata(wagon, wagon_metadata, updates)

        events.append({
            "type": "wagon_unloaded",
            "wagon_id": str(wagon.id),
            "entity_id": item_id,
            "target_player_id": str(intent.player_id),
        })

    def _process_autorepeat(
        self,
        entities: list[Entity],
        creates: list[EntityCreate],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
        zone_width: int,
        zone_height: int,
        zone_def: dict[str, Any] | None,
        deletes: list[UUID],
        active_pushes: dict[UUID, UUID],
        touched_dispensers: set[UUID],
    ) -> None:
        for monster in entities:
            if self._entity_kind(monster) != KIND_MONSTER:
                continue
            current_task = (monster.metadata_ or {}).get("current_task") or {}
            if not current_task.get("is_playing"):
                continue

            actions = current_task.get("actions") or []
            if not actions:
                current_task["is_playing"] = False
                metadata = dict(monster.metadata_ or {})
                metadata["current_task"] = current_task
                self._apply_metadata(monster, metadata, updates)
                continue

            index = int(current_task.get("play_index") or 0)
            if index >= len(actions):
                index = 0

            action = actions[index]
            action_type = action.get("action") if isinstance(action, dict) else None
            dx, dy = self._intent_to_delta(action)
            if dx != 0 or dy != 0:
                new_x = monster.x + dx
                new_y = monster.y + dy
                if not self._is_in_bounds(new_x, new_y, monster, zone_width, zone_height):
                    self._stop_autorepeat(monster, updates)
                    continue
                if self._is_terrain_blocked(zone_def, new_x, new_y):
                    self._stop_autorepeat(monster, updates)
                    continue

                blocker = self._find_blocker(entities, monster, new_x, new_y)
                if action_type == "push":
                    if blocker is None:
                        self._stop_autorepeat(monster, updates)
                        continue
                    if self._entity_kind(blocker) not in PUSHABLE_KINDS:
                        self._stop_autorepeat(monster, updates)
                        continue
                    if blocker.metadata_ and blocker.metadata_.get("is_stored"):
                        self._stop_autorepeat(monster, updates)
                        continue
                    can_push, _ = self._can_monster_push(monster, blocker)
                    if not can_push:
                        self._stop_autorepeat(monster, updates)
                        continue

                    self._mark_active_push(blocker, monster.id, updates, active_pushes)
                    if not self._attempt_push(
                        entities=entities,
                        mover=monster,
                        pushed=blocker,
                        dx=dx,
                        dy=dy,
                        creates=creates,
                        updates=updates,
                        deletes=deletes,
                        zone_width=zone_width,
                        zone_height=zone_height,
                        zone_def=zone_def,
                        events=events,
                        touched_dispensers=touched_dispensers,
                    ):
                        self._clear_active_push(blocker, updates, active_pushes)
                        self._stop_autorepeat(monster, updates)
                        continue
                    self._clear_active_push(blocker, updates, active_pushes)
                else:
                    if blocker is None:
                        old_x, old_y = monster.x, monster.y
                        self._apply_move(monster, new_x, new_y, updates)
                        self._maybe_move_hitched_wagon(monster, old_x, old_y, entities, updates)
                    else:
                        self._stop_autorepeat(monster, updates)
                        continue

            current_task["play_index"] = (index + 1) % max(len(actions), 1)
            metadata = dict(monster.metadata_ or {})
            metadata["current_task"] = current_task
            self._apply_metadata(monster, metadata, updates)
            events.append({
                "type": "autorepeat_step",
                "target_player_id": str(monster.owner_id) if monster.owner_id else None,
            })

    def _process_crafting(
        self,
        entities: list[Entity],
        updates: list[EntityUpdate],
        creates: list[EntityCreate],
        deletes: list[UUID],
        events: list[dict[str, Any]],
        tick_number: int,
        zone_def: dict[str, Any] | None,
    ) -> None:
        for workshop in entities:
            if self._entity_kind(workshop) not in (KIND_WORKSHOP, KIND_GATHERING):
                continue

            metadata = dict(workshop.metadata_ or {})
            is_gathering = self._is_gathering_spot(workshop)
            recipe_entry = None
            recipe_name = metadata.get("selected_recipe_name") or metadata.get("selected_recipe_id")
            if is_gathering:
                gathering_good = metadata.get("gathering_good_type")
                if gathering_good:
                    recipe_name = gathering_good
            if recipe_name:
                recipe_entry = self._get_recipe_entry(recipe_name)
                if is_gathering and recipe_entry:
                    metadata.setdefault("selected_recipe_name", recipe_entry.get("name"))
                    metadata.setdefault("selected_recipe_id", recipe_entry.get("name"))

            if is_gathering:
                input_items = []
                tool_items = self._get_gathering_tools(entities, workshop)
            else:
                input_items, tool_items = self._get_workshop_items(entities, workshop)
            missing_inputs, missing_tools = ([], [])
            if recipe_entry:
                if is_gathering:
                    _, missing_tools = self._find_missing_requirements(
                        recipe_entry,
                        [],
                        tool_items,
                    )
                    missing_inputs = []
                else:
                    missing_inputs, missing_tools = self._find_missing_requirements(
                        recipe_entry,
                        input_items,
                        tool_items,
                    )
                metadata["missing_inputs"] = missing_inputs
                metadata["missing_tools"] = missing_tools

            if not metadata.get("is_crafting"):
                if recipe_entry and not missing_inputs and not missing_tools:
                    duration = self._calculate_crafting_duration(
                        recipe_entry,
                        self._get_monster_by_id(entities, metadata.get("crafter_monster_id")),
                    )
                    metadata["is_crafting"] = True
                    metadata["crafting_started_tick"] = tick_number
                    metadata["crafting_duration"] = duration
                    metadata["base_duration"] = recipe_entry.get("production_time", duration)
                    self._apply_metadata(workshop, metadata, updates)
                continue

            started_tick = metadata.get("crafting_started_tick")
            try:
                duration = int(metadata.get("crafting_duration", 60))
            except (TypeError, ValueError):
                duration = 60
            if started_tick is None:
                metadata["is_crafting"] = False
                self._apply_metadata(workshop, metadata, updates)
                continue
            try:
                started_tick = int(started_tick)
            except (TypeError, ValueError):
                metadata["is_crafting"] = False
                self._apply_metadata(workshop, metadata, updates)
                continue

            elapsed = tick_number - started_tick
            if elapsed < duration:
                self._apply_metadata(workshop, metadata, updates)
                continue

            if recipe_entry is None:
                metadata["is_crafting"] = False
                self._apply_metadata(workshop, metadata, updates)
                continue

            crafter = self._get_monster_by_id(entities, metadata.get("crafter_monster_id"))
            self._apply_skill_gain(crafter, recipe_entry, duration, updates)
            output_creates, output_quantity = self._create_output_items(
                entities,
                workshop,
                recipe_entry,
                crafter,
                tool_items,
                input_items,
                updates,
            )
            if output_creates:
                creates.extend(output_creates)

            depleted_tools = self._consume_tool_durability(
                tool_items,
                recipe_entry,
                output_quantity,
                updates,
                deletes,
            )
            consumed_inputs = self._consume_input_items(input_items, deletes)
            if depleted_tools:
                metadata["last_depleted_tools"] = depleted_tools

            metadata["is_crafting"] = False
            metadata["crafting_completed_tick"] = tick_number
            metadata["input_item_ids"] = []
            metadata["tool_item_ids"] = [
                str(tool.id)
                for tool in tool_items
                if tool.id not in deletes
            ]

            self._apply_metadata(workshop, metadata, updates)

            events.append({
                "type": "crafting_complete",
                "workshop_id": str(workshop.id),
                "recipe_name": recipe_entry.get("name"),
                "consumed_inputs": consumed_inputs,
            })

    def _apply_move(
        self,
        entity: Entity,
        new_x: int,
        new_y: int,
        updates: list[EntityUpdate],
    ) -> None:
        entity.x = new_x
        entity.y = new_y
        updates.append(EntityUpdate(id=entity.id, x=new_x, y=new_y))

    def _apply_metadata(
        self,
        entity: Entity,
        metadata: dict[str, Any],
        updates: list[EntityUpdate],
    ) -> None:
        entity.metadata_ = metadata
        updates.append(EntityUpdate(id=entity.id, metadata=metadata))

    def _apply_wagon_move(
        self,
        wagon: Entity,
        new_x: int,
        new_y: int,
        entities: list[Entity],
        updates: list[EntityUpdate],
    ) -> None:
        old_x, old_y = wagon.x, wagon.y
        self._apply_move(wagon, new_x, new_y, updates)
        self._move_wagon_contents(wagon, old_x, old_y, new_x, new_y, entities, updates)

    def _move_wagon_contents(
        self,
        wagon: Entity,
        old_x: int,
        old_y: int,
        new_x: int,
        new_y: int,
        entities: list[Entity],
        updates: list[EntityUpdate],
    ) -> None:
        for item in entities:
            if self._entity_kind(item) != KIND_ITEM:
                continue
            metadata = item.metadata_ or {}
            if not metadata.get("is_stored"):
                continue
            if metadata.get("container_id") != str(wagon.id):
                continue
            offset = metadata.get("stored_offset")
            if not isinstance(offset, dict):
                offset = {"x": item.x - old_x, "y": item.y - old_y}
                metadata = dict(metadata)
                metadata["stored_offset"] = offset
                self._apply_metadata(item, metadata, updates)

            try:
                dx = int(offset.get("x", 0))
                dy = int(offset.get("y", 0))
            except (TypeError, ValueError):
                dx = 0
                dy = 0
            self._apply_move(item, new_x + dx, new_y + dy, updates)

    def _get_container_capacity(self, container: Entity) -> int:
        metadata = container.metadata_ or {}
        capacity = metadata.get("capacity")
        if capacity is None:
            return DEFAULT_CONTAINER_CAPACITY
        try:
            return max(1, int(capacity))
        except (TypeError, ValueError):
            return DEFAULT_CONTAINER_CAPACITY

    def _get_item_container_units(self, item: Entity) -> int:
        # TODO: use item size/weight/materials + container quality for capacity costs.
        return 1

    def _get_container_used_units(self, entities: list[Entity], container: Entity) -> int:
        used = 0
        for entity in entities:
            if self._entity_kind(entity) != KIND_ITEM:
                continue
            metadata = entity.metadata_ or {}
            if not metadata.get("is_stored"):
                continue
            if metadata.get("container_id") != str(container.id):
                continue
            used += self._get_item_container_units(entity)
        return used

    def _container_accepts_item(
        self,
        container: Entity,
        item: Entity,
        entities: list[Entity],
    ) -> bool:
        metadata = container.metadata_ or {}
        stored_type = self._normalize_good_type_key(metadata.get("stored_good_type"))
        item_type = self._normalize_good_type_key((item.metadata_ or {}).get("good_type"))
        if stored_type and item_type and stored_type != item_type:
            return False
        capacity = self._get_container_capacity(container)
        used = self._get_container_used_units(entities, container)
        units = self._get_item_container_units(item)
        return used + units <= capacity

    def _get_wagon_capacity(self, wagon: Entity) -> int:
        return self._get_container_capacity(wagon)

    def _get_wagon_items(self, entities: list[Entity], wagon: Entity) -> list[Entity]:
        items: list[Entity] = []
        for entity in entities:
            if self._entity_kind(entity) != KIND_ITEM:
                continue
            metadata = entity.metadata_ or {}
            if not metadata.get("is_stored"):
                continue
            if metadata.get("container_id") != str(wagon.id):
                continue
            items.append(entity)
        return items

    def _load_item_into_wagon(
        self,
        item: Entity,
        wagon: Entity,
        slot_x: int,
        slot_y: int,
        entities: list[Entity],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
        transporter: Entity | None = None,
    ) -> bool:
        wagon_metadata = dict(wagon.metadata_ or {})
        item_metadata = dict(item.metadata_ or {})
        stored_type = self._normalize_good_type_key(wagon_metadata.get("stored_good_type"))
        item_type = self._normalize_good_type_key(item_metadata.get("good_type"))
        if stored_type and item_type and stored_type != item_type:
            events.append({
                "type": "wagon_reject",
                "wagon_id": str(wagon.id),
                "reason": "type_mismatch",
            })
            return False
        capacity = self._get_wagon_capacity(wagon)
        used_units = self._get_container_used_units(entities, wagon)
        item_units = self._get_item_container_units(item)
        if used_units + item_units > capacity:
            events.append({
                "type": "wagon_full",
                "wagon_id": str(wagon.id),
            })
            return False

        if transporter is not None:
            self._mark_last_transporter(item, transporter, updates)

        if stored_type:
            wagon_metadata["stored_good_type"] = stored_type
            self._apply_metadata(wagon, wagon_metadata, updates)
        elif item_type:
            wagon_metadata["stored_good_type"] = item_type
            self._apply_metadata(wagon, wagon_metadata, updates)

        self._ensure_item_size_metadata(item_metadata)
        item_metadata["is_stored"] = True
        item_metadata["container_id"] = str(wagon.id)
        item_metadata["stored_role"] = "wagon"
        item_metadata["stored_offset"] = {"x": slot_x - wagon.x, "y": slot_y - wagon.y}

        self._apply_move(item, slot_x, slot_y, updates)
        self._apply_metadata(item, item_metadata, updates)

        loaded_ids = list(wagon_metadata.get("loaded_item_ids") or [])
        item_id = str(item.id)
        if item_id not in loaded_ids:
            loaded_ids.append(item_id)
        wagon_metadata["loaded_item_ids"] = loaded_ids
        wagon_metadata["loaded_item_count"] = len(loaded_ids)
        self._apply_metadata(wagon, wagon_metadata, updates)

        events.append({
            "type": "wagon_loaded",
            "wagon_id": str(wagon.id),
            "entity_id": item_id,
        })
        return True

    def _find_adjacent_wagon(self, monster: Entity, entities: list[Entity]) -> Entity | None:
        adjacent_cells = [
            (monster.x + dx, monster.y + dy)
            for dx, dy in DIR_TO_DELTA.values()
        ]
        for wagon in entities:
            if self._entity_kind(wagon) != KIND_WAGON:
                continue
            wx, wy, ww, wh = self._entity_rect(wagon)
            for ax, ay in adjacent_cells:
                if self._rects_overlap(ax, ay, 1, 1, wx, wy, ww, wh):
                    return wagon
        return None

    def _find_unload_cell(
        self,
        wagon: Entity,
        entities: list[Entity],
        zone_width: int,
        zone_height: int,
        zone_def: dict[str, Any] | None,
    ) -> tuple[int, int] | None:
        wx, wy, ww, wh = self._entity_rect(wagon)
        for x in range(wx - 1, wx + ww + 1):
            for y in range(wy - 1, wy + wh + 1):
                if wx <= x < wx + ww and wy <= y < wy + wh:
                    continue
                if x < 0 or y < 0 or x >= zone_width or y >= zone_height:
                    continue
                if self._is_terrain_blocked(zone_def, x, y):
                    continue
                blocker = self._find_blocker(entities, self._fake_entity(x, y), x, y)
                if blocker is not None:
                    continue
                return (x, y)
        return None

    def _maybe_move_hitched_wagon(
        self,
        monster: Entity,
        old_x: int,
        old_y: int,
        entities: list[Entity],
        updates: list[EntityUpdate],
    ) -> None:
        current_task = (monster.metadata_ or {}).get("current_task") or {}
        hitched_id = self._parse_entity_id(current_task.get("hitched_wagon_id"))
        if hitched_id is None:
            return
        head = next((e for e in entities if e.id == hitched_id), None)
        if head is None or self._entity_kind(head) != KIND_WAGON:
            return
        # TODO: enforce strength/weight limits for pulling wagon chains.
        chain = self._get_wagon_chain(head, entities)
        prev_x, prev_y = old_x, old_y
        for wagon in chain:
            wagon_old_x, wagon_old_y = wagon.x, wagon.y
            self._apply_wagon_move(wagon, prev_x, prev_y, entities, updates)
            prev_x, prev_y = wagon_old_x, wagon_old_y

    def _get_wagon_chain(self, head: Entity, entities: list[Entity]) -> list[Entity]:
        chain: list[Entity] = []
        seen: set[UUID] = set()
        current = head
        while current and current.id not in seen:
            chain.append(current)
            seen.add(current.id)
            next_id = self._parse_entity_id((current.metadata_ or {}).get("next_wagon_id"))
            if next_id is None:
                break
            current = next((e for e in entities if e.id == next_id), None)
        return chain

    def _record_action(
        self,
        monster: Entity,
        action: str,
        dx: int,
        dy: int,
        updates: list[EntityUpdate],
    ) -> None:
        metadata = dict(monster.metadata_ or {})
        current_task = dict(metadata.get("current_task") or {})
        if not current_task.get("is_recording"):
            return
        actions = list(current_task.get("actions") or [])
        actions.append({"action": action, "dx": dx, "dy": dy})
        current_task["actions"] = actions
        metadata["current_task"] = current_task
        self._apply_metadata(monster, metadata, updates)

    def _stop_autorepeat(self, monster: Entity, updates: list[EntityUpdate]) -> None:
        metadata = dict(monster.metadata_ or {})
        current_task = dict(metadata.get("current_task") or {})
        current_task["is_playing"] = False
        metadata["current_task"] = current_task
        self._apply_metadata(monster, metadata, updates)

    def _get_recipe_entry(self, recipe_id: Any) -> dict[str, Any] | None:
        if recipe_id is None:
            return None
        key = str(recipe_id).strip().lower()
        if key in self._good_types:
            return self._good_types[key]
        # Try to normalize spaces/underscores
        key = key.replace("_", " ").strip().lower()
        return self._good_types.get(key)

    def _get_workshop_items(
        self,
        entities: list[Entity],
        workshop: Entity,
    ) -> tuple[list[Entity], list[Entity]]:
        inputs: list[Entity] = []
        tools: list[Entity] = []
        for entity in entities:
            if self._entity_kind(entity) != KIND_ITEM:
                continue
            metadata = entity.metadata_ or {}
            if metadata.get("container_id") != str(workshop.id):
                continue
            if not metadata.get("is_stored"):
                continue
            role = metadata.get("stored_role")
            if role == "tool":
                tools.append(entity)
            else:
                inputs.append(entity)
        return inputs, tools

    def _get_gathering_tools(
        self,
        entities: list[Entity],
        workshop: Entity,
    ) -> list[Entity]:
        tools: list[Entity] = []
        for entity in entities:
            if self._entity_kind(entity) != KIND_ITEM:
                continue
            metadata = entity.metadata_ or {}
            if metadata.get("container_id") != str(workshop.id):
                continue
            if not metadata.get("is_stored"):
                continue
            if metadata.get("stored_role") == "tool":
                tools.append(entity)
        return tools

    def _find_missing_requirements(
        self,
        recipe: dict[str, Any],
        input_items: list[Entity],
        tool_items: list[Entity],
    ) -> tuple[list[list[str]], list[str]]:
        required_tags = recipe.get("input_goods_tags_required") or []
        missing_inputs: list[list[str]] = []
        for tag_group in required_tags:
            tags = [str(tag).lower() for tag in tag_group]
            if not self._has_item_with_tags(input_items, tags):
                missing_inputs.append(tags)

        required_tools = recipe.get("tools_required_tags") or []
        missing_tools: list[str] = []
        for required in required_tools:
            required_tag = str(required).lower()
            if not self._has_tool_with_tag(tool_items, required_tag):
                missing_tools.append(required_tag)

        return missing_inputs, missing_tools

    def _has_item_with_tags(self, items: list[Entity], tags: list[str]) -> bool:
        for item in items:
            item_tags = self._get_item_tags(item.metadata_ or {})
            if all(tag in item_tags for tag in tags):
                return True
        return False

    def _has_tool_with_tag(self, tools: list[Entity], required_tag: str) -> bool:
        for tool in tools:
            metadata = tool.metadata_ or {}
            durability = metadata.get("durability")
            if durability is None:
                durability = metadata.get("max_durability")
                if durability is None:
                    durability = self._get_item_max_durability(metadata)
            try:
                durability = int(durability)
            except (TypeError, ValueError):
                durability = 0
            if durability <= 0:
                continue
            tool_tags = self._get_tool_tags(metadata)
            if required_tag in [tag.lower() for tag in tool_tags]:
                return True
        return False

    def _get_item_tags(self, metadata: dict[str, Any]) -> list[str]:
        good_type = str(metadata.get("good_type", "")).strip().lower()
        entry = self._get_good_type_entry(good_type)
        tags: list[str] = []
        if entry:
            tags.extend([str(tag).lower() for tag in entry.get("type_tags") or []])
        elif good_type:
            for part in good_type.replace("_", " ").split():
                if part:
                    tags.append(part)
            if good_type not in tags:
                tags.append(good_type)
        carried = metadata.get("carried_over_tags") or []
        for tag in carried:
            if not tag:
                continue
            tag_value = str(tag).lower()
            if tag_value not in tags:
                tags.append(tag_value)
        return tags

    def _get_good_type_entry(self, good_type: str | None) -> dict[str, Any] | None:
        if not good_type:
            return None
        key = str(good_type).strip().lower().replace("_", " ")
        entry = self._good_types.get(key)
        if entry:
            return entry
        return self._good_types.get(str(good_type).strip().lower())

    def _normalize_skill_key(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip().lower().replace(" ", "_")

    def _normalize_good_type_key(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip().lower().replace(" ", "_")

    def _get_good_type_size(self, entry: dict[str, Any]) -> tuple[int, int]:
        size = entry.get("size")
        if isinstance(size, (list, tuple)) and len(size) >= 2:
            try:
                width = int(size[0])
            except (TypeError, ValueError):
                width = DEFAULT_ITEM_SIZE[0]
            try:
                height = int(size[1])
            except (TypeError, ValueError):
                height = DEFAULT_ITEM_SIZE[1]
            return max(1, width), max(1, height)
        return DEFAULT_ITEM_SIZE

    def _get_item_size_from_metadata(self, metadata: dict[str, Any]) -> tuple[int, int]:
        size = metadata.get("size")
        if isinstance(size, (list, tuple)) and len(size) >= 2:
            try:
                width = int(size[0])
            except (TypeError, ValueError):
                width = DEFAULT_ITEM_SIZE[0]
            try:
                height = int(size[1])
            except (TypeError, ValueError):
                height = DEFAULT_ITEM_SIZE[1]
            return max(1, width), max(1, height)
        entry = self._get_good_type_entry(metadata.get("good_type"))
        if entry:
            return self._get_good_type_size(entry)
        return DEFAULT_ITEM_SIZE

    def _ensure_item_size_metadata(self, metadata: dict[str, Any]) -> None:
        if "size" in metadata:
            return
        entry = self._get_good_type_entry(metadata.get("good_type"))
        if entry:
            width, height = self._get_good_type_size(entry)
            metadata["size"] = [width, height]

    def _is_raw_material_entry(self, entry: dict[str, Any]) -> bool:
        return entry.get("raw_material_base_value") is not None

    def _is_workshop_entry(self, entry: dict[str, Any]) -> bool:
        return entry.get("workshop_task_slots") is not None or entry.get("workshop_task_tags") is not None

    def _get_monster_stat(self, monster: Entity | None, stat_key: str, default: int = 10) -> int:
        if monster is None:
            return default
        stats = (monster.metadata_ or {}).get("stats") or {}
        try:
            return int(stats.get(stat_key, default))
        except (TypeError, ValueError):
            return default

    def _get_monster_age_bonus_real(self, monster: Entity | None) -> int:
        if monster is None:
            return 0
        created_at = (monster.metadata_ or {}).get("created_at")
        if not created_at:
            return 0
        created_dt = self._parse_datetime(created_at)
        if created_dt is None:
            return 0
        age_seconds = (datetime.utcnow() - created_dt).total_seconds()
        if age_seconds >= 60 * 24 * 60 * 60:
            return 2
        if age_seconds >= 30 * 24 * 60 * 60:
            return 1
        return 0

    def _effective_ability(self, monster: Entity | None, ability_index: int) -> int:
        if monster is None:
            return 10
        try:
            ability_index = int(ability_index)
        except (TypeError, ValueError):
            ability_index = 0
        index = max(0, min(ability_index, len(ABILITY_KEYS) - 1))
        base = self._get_monster_stat(monster, ABILITY_KEYS[index], 10)
        return base + self._get_monster_age_bonus_real(monster)

    def _effective_quality(self, monster: Entity | None, unmodified_quality: float, recipe: dict[str, Any]) -> float:
        if monster is None:
            return unmodified_quality
        wisdom_plus_strength = self._effective_ability(monster, 4) + (self._effective_ability(monster, 0) * 0.25)
        distance_from_perfect = max(1 - unmodified_quality, 0)
        result = unmodified_quality + (wisdom_plus_strength / 25 * distance_from_perfect * 0.25)
        return result

    def _effective_quantity(self, monster: Entity | None, unmodified_quantity: float, recipe: dict[str, Any]) -> float:
        if monster is None:
            return unmodified_quantity
        result = unmodified_quantity
        strength_multiplier = (self._effective_ability(monster, 0) - 10) / 10
        result += round(unmodified_quantity * strength_multiplier)
        dex_multiplier = (self._effective_ability(monster, 1) - 10) / 10
        result += round(unmodified_quantity * dex_multiplier * 0.25)
        return max(result, 1)

    def _effective_production_time(self, monster: Entity | None, base_duration: float, recipe: dict[str, Any]) -> float:
        if monster is None:
            return base_duration
        result = base_duration
        dex = self._effective_ability(monster, 1)
        int_stat = self._effective_ability(monster, 3)
        if dex > 0:
            result *= 10 / dex
        result *= 30 / (20 + int_stat)
        return result

    def _get_skill_maps(self, monster: Entity | None) -> tuple[dict[str, Any], dict[str, Any], float, list[str]]:
        if monster is None:
            return {}, {}, 0.0, []
        metadata = monster.metadata_ or {}
        skills = metadata.get("skills") or {}
        applied = dict(skills.get("applied") or {})
        specific = dict(skills.get("specific") or {})
        transferable = list(skills.get("transferable") or [])
        try:
            total_forgotten = float(metadata.get("total_forgotten", 0.0))
        except (TypeError, ValueError):
            total_forgotten = 0.0
        return applied, specific, total_forgotten, transferable

    def _get_skill_total_learned(self, total_forgotten: float, skills_map: dict[str, Any], key: str) -> float:
        if key not in skills_map:
            return total_forgotten
        try:
            value = float(skills_map.get(key, total_forgotten))
        except (TypeError, ValueError):
            value = total_forgotten
        if value < total_forgotten:
            value = total_forgotten
        return value

    def _get_skill_value(self, monster: Entity | None, key: str, kind: str) -> float:
        if monster is None or not key:
            return 0.0
        metadata = monster.metadata_ or {}
        skills = metadata.get("skills") or {}
        try:
            total_forgotten = float(metadata.get("total_forgotten", 0.0))
        except (TypeError, ValueError):
            total_forgotten = 0.0
        map_for_kind = skills.get(kind) or {}
        total_learned = self._get_skill_total_learned(total_forgotten, map_for_kind, key)
        return max(0.0, total_learned - total_forgotten)

    def _get_item_quality(self, item: Entity | None) -> float:
        if item is None:
            return 1.0
        metadata = item.metadata_ or {}
        quality = metadata.get("quality", 1.0)
        normalized = self._normalize_quality(quality)
        return max(0.0, normalized)

    def _matching_transferable_skills_count(self, recipe: dict[str, Any], monster: Entity | None) -> int:
        if monster is None:
            return 0
        recipe_skills = recipe.get("transferable_skills") or []
        recipe_skills = {self._normalize_skill_key(skill) for skill in recipe_skills if skill}
        _, _, _, transferable = self._get_skill_maps(monster)
        monster_skills = {self._normalize_skill_key(skill) for skill in transferable if skill}
        return len(recipe_skills.intersection(monster_skills))

    def _weighted_secondary_skills_average(self, recipe: dict[str, Any], monster: Entity | None, transferable_skills_count: int) -> float:
        if monster is None:
            return 1.0
        secondary_skills = recipe.get("secondary_applied_skills") or []
        if not secondary_skills:
            return 1.0
        values = []
        for skill in secondary_skills:
            key = self._normalize_skill_key(skill)
            if not key:
                continue
            values.append(self._get_skill_value(monster, key, "applied"))
        values.sort()
        values = values[transferable_skills_count:]
        if not values:
            return 1.0
        return sum(values) / len(values)

    def _weighted_tool_qualities_average(
        self,
        recipe: dict[str, Any],
        tools: list[Entity],
        transferable_skills_count: int,
    ) -> float:
        if not tools:
            return 1.0
        tool_weights = list(recipe.get("tools_weights") or [])
        qualities: list[float] = []
        for index, tool in enumerate(tools):
            quality = self._get_item_quality(tool)
            try:
                weight = int(tool_weights[index])
            except (TypeError, ValueError, IndexError):
                weight = 1
            if weight < 1:
                weight = 1
            qualities.extend([quality] * weight)
        qualities.sort()
        drop_count = transferable_skills_count * 2
        if drop_count:
            qualities = qualities[drop_count:]
        if not qualities:
            return 1.0
        return sum(qualities) / len(qualities)

    def _roll_for_quality(
        self,
        recipe: dict[str, Any],
        monster: Entity | None,
        input_items: list[Entity],
        tool_items: list[Entity],
    ) -> float:
        if not input_items:
            average_of_input_qualities = 1.0
        else:
            average_of_input_qualities = sum(self._get_item_quality(item) for item in input_items) / len(input_items)

        transferable_skills_count = self._matching_transferable_skills_count(recipe, monster)
        secondary_skills_average = self._weighted_secondary_skills_average(recipe, monster, transferable_skills_count)
        tool_qualities_average = self._weighted_tool_qualities_average(recipe, tool_items, transferable_skills_count)

        if not recipe.get("has_quality", True):
            return (average_of_input_qualities + tool_qualities_average) / 2

        primary_skill = self._get_skill_value(monster, self._normalize_skill_key(recipe.get("primary_applied_skill")), "applied")
        specific_skill = self._get_skill_value(monster, self._normalize_good_type_key(recipe.get("name")), "specific")

        try:
            relevant_index = int(recipe.get("relevant_ability_score", 0))
        except (TypeError, ValueError):
            relevant_index = 0
        relevant_ability_score = self._effective_ability(monster, relevant_index)
        try:
            difficulty_rating = int(recipe.get("difficulty_rating", 1))
        except (TypeError, ValueError):
            difficulty_rating = 1
        difficulty_rating = difficulty_rating or 1
        ability_factor = min(1.2, (relevant_ability_score / difficulty_rating))

        mu = average_of_input_qualities * primary_skill * secondary_skills_average
        mu += tool_qualities_average * specific_skill * ability_factor

        destabilizer = recipe.get("destabilizer_skills") or []
        if destabilizer:
            values = [
                self._get_skill_value(monster, self._normalize_skill_key(skill), "applied")
                for skill in destabilizer
            ]
            destabilizer_average = sum(values) / len(values)
        else:
            destabilizer_average = 0.0

        sigma = 0.1 + (destabilizer_average / 10)
        result = random.gauss(0, 1) * sigma + mu
        result = max(0.0, result)
        return self._effective_quality(monster, result, recipe)

    def _roll_for_quantity(
        self,
        recipe: dict[str, Any],
        monster: Entity | None,
        input_items: list[Entity],
        tool_items: list[Entity],
    ) -> int:
        try:
            mu = float(recipe.get("quantity", 1))
        except (TypeError, ValueError):
            mu = 1.0

        if monster is None:
            return max(1, int(round(mu)))

        try:
            relevant_index = int(recipe.get("relevant_ability_score", 0))
        except (TypeError, ValueError):
            relevant_index = 0
        relevant_ability_score = self._effective_ability(monster, relevant_index)
        primary_skill = self._get_skill_value(monster, self._normalize_skill_key(recipe.get("primary_applied_skill")), "applied")
        specific_skill = self._get_skill_value(monster, self._normalize_good_type_key(recipe.get("name")), "specific")

        transferable_skills_count = self._matching_transferable_skills_count(recipe, monster)
        tool_qualities_average = self._weighted_tool_qualities_average(recipe, tool_items, transferable_skills_count)
        secondary_skills_average = self._weighted_secondary_skills_average(recipe, monster, transferable_skills_count)

        sigma = mu * 0.05 * relevant_ability_score * primary_skill * specific_skill
        sigma *= tool_qualities_average * secondary_skills_average

        result = abs(random.gauss(0, 1) * sigma) + mu
        result = self._effective_quantity(monster, result, recipe)
        return max(1, int(round(result)))

    def _roll_for_raw_material_type(self, recipe: dict[str, Any], monster: Entity | None) -> dict[str, Any]:
        # TODO: match Django roll_for_raw_material_type once defined.
        return recipe

    def _effective_specific_learning(
        self,
        monster: Entity | None,
        starting_value: float,
        task: dict[str, Any],
        primary_skill_value: float,
    ) -> float:
        if monster is None:
            return 0.0
        duration = int(task.get("duration", 0) or 0)
        if duration <= 0:
            return 0.0
        int_stat = self._effective_ability(monster, 3)
        con_stat = self._effective_ability(monster, 2)
        ability_factor = ((int_stat * 0.8) + (con_stat * 0.2)) / 20
        result = 0.0
        for _ in range(duration // 10):
            remaining_distance = 1 - starting_value - result
            result += 0.002 * remaining_distance * ability_factor * primary_skill_value
        return result

    def _effective_primary_learning(
        self,
        monster: Entity | None,
        starting_value: float,
        task: dict[str, Any],
    ) -> float:
        if monster is None:
            return 0.0
        duration = int(task.get("duration", 0) or 0)
        if duration <= 0:
            return 0.0
        int_stat = self._effective_ability(monster, 3)
        con_stat = self._effective_ability(monster, 2)
        ability_factor = ((int_stat * 0.8) + (con_stat * 0.2)) / 20

        output_good = task.get("output_good_type") or {}
        primary_key = self._normalize_skill_key(output_good.get("primary_applied_skill"))
        relevant_map = self._skill_defs.get("relevant_transferable_skills") or {}
        relevant_transferable = {
            self._normalize_skill_key(skill) for skill in relevant_map.get(primary_key, [])
        }
        _, _, _, transferable = self._get_skill_maps(monster)
        transferable_set = {self._normalize_skill_key(skill) for skill in transferable}
        transferable_factor = 1 + (len(relevant_transferable.intersection(transferable_set)) / 4)

        result = 0.0
        for _ in range(duration // 10):
            remaining_distance = 1 - starting_value - result
            result += 0.001 * remaining_distance * ability_factor * transferable_factor
        return result

    def _effective_secondary_learning(
        self,
        monster: Entity | None,
        starting_value: float,
        task: dict[str, Any],
    ) -> float:
        if monster is None:
            return 0.0
        duration = int(task.get("duration", 0) or 0)
        if duration <= 0:
            return 0.0
        int_stat = self._effective_ability(monster, 3)
        con_stat = self._effective_ability(monster, 2)
        ability_factor = ((int_stat * 0.8) + (con_stat * 0.2)) / 20
        result = 0.0
        for _ in range(duration // 10):
            remaining_distance = 1 - starting_value - result
            result += 0.0005 * remaining_distance * ability_factor
        return result

    def _effective_forgetting(
        self,
        monster: Entity | None,
        starting_value: float,
        task: dict[str, Any],
    ) -> float:
        if monster is None:
            return 0.0
        duration = int(task.get("duration", 0) or 0)
        if duration <= 0:
            return 0.0
        wis_stat = self._effective_ability(monster, 4)
        ability_factor = 1 - (wis_stat / 20) * 0.25
        result = 0.0
        for _ in range(duration // 10):
            result += 0.0001 * ability_factor
        return result

    def _match_input_items(
        self,
        input_items: list[Entity],
        required_tags: list[list[str]],
    ) -> list[Entity | None]:
        remaining = list(input_items)
        matched: list[Entity | None] = []
        for tag_group in required_tags:
            group = [str(tag).lower() for tag in tag_group]
            found = None
            for item in remaining:
                tags = self._get_item_tags(item.metadata_ or {})
                if all(tag in tags for tag in group):
                    found = item
                    break
            matched.append(found)
            if found is not None:
                remaining.remove(found)
        return matched

    def _calculate_carried_over_tags(
        self,
        recipe_entry: dict[str, Any],
        input_items: list[Entity],
    ) -> list[str]:
        carryover = recipe_entry.get("input_goods_tags_carryover") or []
        required = recipe_entry.get("input_goods_tags_required") or []
        if not carryover or not input_items:
            return []
        matched = self._match_input_items(input_items, required)
        carried: set[str] = set()
        for index, carry_tags in enumerate(carryover):
            if index >= len(matched):
                break
            item = matched[index]
            if item is None:
                continue
            item_tags = self._get_item_tags(item.metadata_ or {})
            for tag in carry_tags:
                tag_value = str(tag).lower()
                if tag_value in item_tags:
                    carried.add(tag_value)
        return sorted(carried)

    def _calculate_raw_material_lineage(
        self,
        recipe_entry: dict[str, Any],
        input_items: list[Entity],
    ) -> tuple[list[dict[str, Any]], int]:
        if self._is_raw_material_entry(recipe_entry):
            return [self._raw_material_entry(recipe_entry)], 0
        if not input_items:
            return [], 0

        raw_materials: list[dict[str, Any]] = []
        refined_depths: list[int] = []
        has_refined_input = False

        for item in input_items:
            entry = self._get_good_type_entry((item.metadata_ or {}).get("good_type"))
            is_raw = entry is not None and self._is_raw_material_entry(entry)
            if not is_raw:
                has_refined_input = True
            item_materials, item_depth = self._get_item_raw_materials(item)
            raw_materials.extend(item_materials)
            if not is_raw:
                refined_depths.append(item_depth)

        if not has_refined_input:
            return raw_materials, 0
        max_depth = max(refined_depths) if refined_depths else 0
        return raw_materials, max_depth + 1

    def _raw_material_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "good_type": entry.get("name"),
            "base_value": entry.get("raw_material_base_value", 0),
            "density": entry.get("raw_material_density", 0),
        }

    def _get_item_raw_materials(self, item: Entity) -> tuple[list[dict[str, Any]], int]:
        metadata = item.metadata_ or {}
        stored = metadata.get("raw_materials")
        if isinstance(stored, list) and stored:
            try:
                depth = int(metadata.get("raw_material_max_depth", 0))
            except (TypeError, ValueError):
                depth = 0
            return stored, depth

        entry = self._get_good_type_entry(metadata.get("good_type"))
        if entry and self._is_raw_material_entry(entry):
            return [self._raw_material_entry(entry)], 0

        return [], 0

    def _calculate_item_weight(self, entry: dict[str, Any], metadata: dict[str, Any]) -> int:
        if self._is_workshop_entry(entry):
            return 100000
        storage_volume = entry.get("storage_volume", 1)
        try:
            storage_volume = float(storage_volume)
        except (TypeError, ValueError):
            storage_volume = 1
        if self._is_raw_material_entry(entry):
            density = entry.get("raw_material_density")
            try:
                density = float(density)
            except (TypeError, ValueError):
                density = None
            if density is not None:
                return max(1, int(round(density * storage_volume)))
        raw_materials = metadata.get("raw_materials") or []
        densities = [
            float(material.get("density"))
            for material in raw_materials
            if material and material.get("density") is not None
        ]
        if densities:
            avg_density = sum(densities) / len(densities)
            return max(1, int(round(avg_density * storage_volume)))
        return max(1, int(round(storage_volume)))

    def _calculate_item_value(
        self,
        entry: dict[str, Any],
        raw_materials: list[dict[str, Any]],
        max_depth: int,
        quality: float,
        crafter: Entity | None,
    ) -> int:
        normalized_quality = self._normalize_quality(quality)
        base_value = entry.get("raw_material_base_value")
        if base_value is not None:
            try:
                base_value = float(base_value)
            except (TypeError, ValueError):
                base_value = 0
            value = base_value * (normalized_quality + 0.5) ** 0.5
            return int(value)

        raw_value = 0.0
        for material in raw_materials:
            if not material:
                continue
            try:
                raw_value += float(material.get("base_value", 0))
            except (TypeError, ValueError):
                continue
        if raw_value <= 0:
            return 0
        exponent = 0.5 + 0.5 * max_depth
        value = round(raw_value * (normalized_quality + 0.5) ** exponent)
        return int(self._apply_value_modifier(value, crafter))

    def _normalize_quality(self, quality: float) -> float:
        try:
            value = float(quality)
        except (TypeError, ValueError):
            return 0.0
        if value > 5.0:
            return value / 100.0
        return value

    def _apply_value_modifier(self, value: float, crafter: Entity | None) -> float:
        if crafter is None:
            return value
        stats = (crafter.metadata_ or {}).get("stats") or {}
        try:
            cha = int(stats.get("cha", 10))
        except (TypeError, ValueError):
            cha = 10
        return value * (10 + (cha / 2)) / 10

    def _calculate_crafting_duration(
        self,
        recipe: dict[str, Any],
        monster: Entity | None,
    ) -> int:
        try:
            base_duration = int(recipe.get("production_time", 60))
        except (TypeError, ValueError):
            base_duration = 60
        duration = self._effective_production_time(monster, base_duration, recipe)
        try:
            duration_int = int(duration)
        except (TypeError, ValueError):
            duration_int = base_duration
        return max(1, duration_int)

    def _get_monster_by_id(self, entities: list[Entity], monster_id: Any) -> Entity | None:
        if not monster_id:
            return None
        for entity in entities:
            if self._entity_kind(entity) != KIND_MONSTER:
                continue
            if str(entity.id) == str(monster_id):
                return entity
        return None

    def _get_workshop_output_anchor(self, workshop: Entity) -> tuple[int, int]:
        width, height = self._entity_size(workshop)
        return workshop.x + width - 2, workshop.y + height - 2

    def _get_workshop_output_position(
        self,
        workshop: Entity,
        item_width: int,
        item_height: int,
    ) -> tuple[int, int] | None:
        anchor_x, anchor_y = self._get_workshop_output_anchor(workshop)
        min_x, min_y, max_x, max_y = self._get_workshop_interior_bounds(workshop)
        output_x = anchor_x - (item_width - 1)
        output_y = anchor_y - (item_height - 1)
        if output_x < min_x or output_y < min_y:
            return None
        if output_x + item_width - 1 > max_x or output_y + item_height - 1 > max_y:
            return None
        return output_x, output_y

    def _create_output_items(
        self,
        entities: list[Entity],
        workshop: Entity,
        recipe: dict[str, Any],
        crafter: Entity | None,
        tools: list[Entity],
        input_items: list[Entity],
        updates: list[EntityUpdate],
    ) -> tuple[list[EntityCreate], int]:
        anchor_x, anchor_y = self._get_workshop_output_anchor(workshop)
        if anchor_x < 0 or anchor_y < 0:
            return [], 0

        try:
            fixed_quantity = bool(recipe.get("is_fixed_quantity"))
        except (TypeError, ValueError):
            fixed_quantity = False
        if fixed_quantity:
            try:
                output_quantity = int(recipe.get("quantity", 1))
            except (TypeError, ValueError):
                output_quantity = 1
        else:
            output_quantity = self._roll_for_quantity(recipe, crafter, input_items, tools)

        if output_quantity < 1:
            output_quantity = 1

        carried_over_tags = self._calculate_carried_over_tags(
            recipe,
            input_items,
        )

        tool_creators = []
        for tool in tools:
            tool_metadata = tool.metadata_ or {}
            creator_id = tool_metadata.get("producer_player_id") or tool_metadata.get("creator_player_id")
            if creator_id and creator_id not in tool_creators:
                tool_creators.append(creator_id)

        container = self._find_entity_at_kind(entities, KIND_DISPENSER, anchor_x, anchor_y)
        container_metadata = dict(container.metadata_ or {}) if container else None
        container_capacity = self._get_container_capacity(container) if container else 0
        used_units = self._get_container_used_units(entities, container) if container else 0
        stored_type = self._normalize_good_type_key(
            container_metadata.get("stored_good_type") if container_metadata else None
        )
        if container_metadata is not None and stored_type:
            container_metadata["stored_good_type"] = stored_type

        creates: list[EntityCreate] = []
        for _ in range(output_quantity):
            output_entry = recipe
            if self._is_raw_material_entry(recipe):
                output_entry = self._roll_for_raw_material_type(recipe, crafter)
            quality = self._roll_for_quality(output_entry, crafter, input_items, tools)
            width, height = self._get_good_type_size(output_entry)
            output_pos = self._get_workshop_output_position(workshop, width, height)
            if output_pos is None:
                continue
            output_x, output_y = output_pos
            raw_materials, max_depth = self._calculate_raw_material_lineage(
                output_entry,
                input_items,
            )
            weight = self._calculate_item_weight(output_entry, {
                "raw_materials": raw_materials,
                "raw_material_max_depth": max_depth,
            })
            value = self._calculate_item_value(
                output_entry,
                raw_materials,
                max_depth,
                quality,
                crafter,
            )
            shares = self._build_output_shares(
                recipe,
                crafter,
                tools,
                input_items,
                workshop,
            )
            store_in_container = False
            output_type = self._normalize_good_type_key(output_entry.get("name"))
            if container_metadata is not None:
                if stored_type and output_type and stored_type != output_type:
                    store_in_container = False
                else:
                    # TODO: replace item_units once container capacity is material/quality-aware.
                    item_units = 1
                    if used_units + item_units <= container_capacity:
                        store_in_container = True
                        used_units += item_units
                        if not stored_type and output_type:
                            stored_type = output_type
                            container_metadata["stored_good_type"] = output_type

            output_create = self._create_output_item(
                output_x,
                output_y,
                output_entry,
                crafter,
                width,
                height,
                quality,
                weight,
                value,
                carried_over_tags,
                raw_materials,
                max_depth,
                tool_creators,
                shares,
                store_in_container,
                container.id if store_in_container and container else None,
                {"x": anchor_x, "y": anchor_y} if store_in_container else None,
            )
            if output_create is not None:
                creates.append(output_create)

        if container is not None and container_metadata is not None:
            self._apply_metadata(container, container_metadata, updates)

        return creates, output_quantity

    def _create_output_item(
        self,
        output_x: int,
        output_y: int,
        output_entry: dict[str, Any],
        crafter: Entity | None,
        width: int,
        height: int,
        quality: float,
        weight: int,
        value: int,
        carried_over_tags: list[str],
        raw_materials: list[dict[str, Any]],
        max_depth: int,
        tool_creators: list[str],
        shares: list[dict[str, Any]],
        store_in_container: bool,
        container_id: UUID | None,
        stored_slot: dict[str, int] | None,
    ) -> EntityCreate | None:
        name = output_entry.get("name") or "Item"
        good_type = self._normalize_good_type_key(name)
        return EntityCreate(
            x=output_x,
            y=output_y,
            width=width,
            height=height,
            metadata={
                "kind": KIND_ITEM,
                "name": name,
                "good_type": good_type,
                "size": [width, height],
                "quality": quality,
                "weight": weight,
                "value": value,
                "carried_over_tags": carried_over_tags,
                "raw_materials": raw_materials,
                "raw_material_max_depth": max_depth,
                "crafted_at": datetime.utcnow().isoformat(),
                "producer_monster_id": str(crafter.id) if crafter else None,
                "producer_player_id": str(crafter.owner_id) if crafter else None,
                "tool_creator_player_ids": tool_creators,
                "shares": shares,
                "is_stored": bool(store_in_container),
                "container_id": str(container_id) if container_id else None,
                "stored_slot": stored_slot if store_in_container else None,
                "last_transporter_monster_id": str(crafter.id) if crafter else None,
                "last_transporter_player_id": str(crafter.owner_id) if crafter else None,
            },
        )

    def _get_item_shares(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        shares = metadata.get("shares") or []
        normalized: list[dict[str, Any]] = []
        if isinstance(shares, list):
            for share in shares:
                if not isinstance(share, dict):
                    continue
                monster_id = share.get("monster_id") or share.get("monster")
                player_id = share.get("player_id") or share.get("owner_id")
                description = share.get("description") or ""
                try:
                    count = float(share.get("count", 0))
                except (TypeError, ValueError):
                    count = 0
                if count <= 0:
                    continue
                normalized.append({
                    "monster_id": str(monster_id) if monster_id else None,
                    "player_id": str(player_id) if player_id else None,
                    "count": count,
                    "description": str(description),
                })
        if normalized:
            return normalized

        producer_monster_id = metadata.get("producer_monster_id")
        producer_player_id = metadata.get("producer_player_id")
        if producer_monster_id or producer_player_id:
            normalized.append({
                "monster_id": str(producer_monster_id) if producer_monster_id else None,
                "player_id": str(producer_player_id) if producer_player_id else None,
                "count": 1.0,
                "description": f"Produced {metadata.get('name') or metadata.get('good_type') or 'Item'}",
            })
        return normalized

    def _append_share(
        self,
        shares: list[dict[str, Any]],
        monster_id: str | None,
        player_id: str | None,
        count: float,
        description: str,
    ) -> None:
        if count <= 0 or not (monster_id or player_id):
            return
        for share in shares:
            if share.get("monster_id") == monster_id and share.get("player_id") == player_id and share.get("description") == description:
                share["count"] += count
                return
        shares.append({
            "monster_id": monster_id,
            "player_id": player_id,
            "count": count,
            "description": description,
        })

    def _build_output_shares(
        self,
        recipe: dict[str, Any],
        crafter: Entity | None,
        tools: list[Entity],
        input_items: list[Entity],
        workshop: Entity | None,
    ) -> list[dict[str, Any]]:
        shares: list[dict[str, Any]] = []

        for item in input_items:
            item_shares = self._get_item_shares(item.metadata_ or {})
            for share in item_shares:
                self._append_share(
                    shares,
                    share.get("monster_id"),
                    share.get("player_id"),
                    share.get("count", 0),
                    share.get("description", ""),
                )

        tool_weights = list(recipe.get("tools_weights") or [])
        for index, tool in enumerate(tools):
            tool_metadata = tool.metadata_ or {}
            tool_name = tool_metadata.get("name") or tool_metadata.get("good_type") or "tool"
            tool_shares = self._get_item_shares(tool_metadata)
            if not tool_shares:
                continue
            contributors: dict[tuple[str | None, str | None], float] = {}
            for share in tool_shares:
                key = (share.get("monster_id"), share.get("player_id"))
                contributors[key] = contributors.get(key, 0.0) + float(share.get("count", 0))
            tool_total = sum(contributors.values())
            if tool_total <= 0:
                continue
            weight = 1
            if index < len(tool_weights):
                try:
                    weight = int(tool_weights[index])
                except (TypeError, ValueError):
                    weight = 1
            if weight < 1:
                weight = 1
            for (monster_id, player_id), count in contributors.items():
                awarded = weight * count / tool_total
                self._append_share(
                    shares,
                    monster_id,
                    player_id,
                    awarded,
                    f"Contributed to {tool_name}",
                )

        if workshop is not None:
            workshop_metadata = workshop.metadata_ or {}
            workshop_name = workshop_metadata.get("name") or workshop_metadata.get("workshop_type") or "workshop"
            workshop_shares = self._get_item_shares(workshop_metadata)
            if workshop_shares:
                contributors: dict[tuple[str | None, str | None], float] = {}
                for share in workshop_shares:
                    key = (share.get("monster_id"), share.get("player_id"))
                    contributors[key] = contributors.get(key, 0.0) + float(share.get("count", 0))
                workshop_total = sum(contributors.values())
                if workshop_total > 0:
                    for (monster_id, player_id), count in contributors.items():
                        awarded = 8 * count / workshop_total
                        self._append_share(
                            shares,
                            monster_id,
                            player_id,
                            awarded,
                            f"Contributed to {workshop_name}",
                        )

        if crafter is not None:
            try:
                value_added = int(recipe.get("value_added_shares", 0))
            except (TypeError, ValueError):
                value_added = 0
            if value_added > 0:
                self._append_share(
                    shares,
                    str(crafter.id),
                    str(crafter.owner_id) if crafter.owner_id else None,
                    value_added,
                    f"Produced {recipe.get('name') or 'Item'}",
                )

        return shares

    def _consume_tool_durability(
        self,
        tools: list[Entity],
        recipe: dict[str, Any],
        quantity: int,
        updates: list[EntityUpdate],
        deletes: list[UUID],
    ) -> list[str]:
        depleted: list[str] = []
        tool_weights = list(recipe.get("tools_weights") or [])
        if quantity < 1:
            quantity = 1
        for index, tool in enumerate(tools):
            metadata = dict(tool.metadata_ or {})
            max_durability = metadata.get("max_durability")
            if max_durability is None:
                max_durability = self._get_item_max_durability(metadata)
            try:
                max_durability = int(max_durability)
            except (TypeError, ValueError):
                max_durability = 100

            durability = metadata.get("durability")
            if durability is None:
                durability = max_durability
            try:
                durability = int(durability)
            except (TypeError, ValueError):
                durability = max_durability

            weight = 1
            if tool_weights and index < len(tool_weights):
                try:
                    weight = int(tool_weights[index])
                except (TypeError, ValueError):
                    weight = 1
            if weight < 1:
                weight = 1

            durability -= weight * quantity
            metadata["durability"] = durability
            metadata["max_durability"] = max_durability
            if durability <= 0:
                deletes.append(tool.id)
                depleted.append(metadata.get("name") or metadata.get("good_type") or "tool")
            else:
                self._apply_metadata(tool, metadata, updates)
        return depleted

    def _consume_input_items(self, inputs: list[Entity], deletes: list[UUID]) -> list[str]:
        consumed: list[str] = []
        for item in inputs:
            metadata = item.metadata_ or {}
            consumed.append(metadata.get("name") or metadata.get("good_type") or "item")
            deletes.append(item.id)
        return consumed

    def _apply_skill_gain(
        self,
        monster: Entity | None,
        recipe: dict[str, Any],
        duration: int,
        updates: list[EntityUpdate],
    ) -> dict[str, Any] | None:
        if monster is None:
            return None
        if duration <= 0:
            return None

        metadata = dict(monster.metadata_ or {})
        skills = dict(metadata.get("skills") or {})
        applied = dict(skills.get("applied") or {})
        specific = dict(skills.get("specific") or {})

        applied_key = self._normalize_skill_key(recipe.get("primary_applied_skill"))
        specific_key = self._normalize_good_type_key(recipe.get("name"))
        if not applied_key or not specific_key:
            return None
        secondary_keys = [
            key for key in (
                self._normalize_skill_key(skill)
                for skill in (recipe.get("secondary_applied_skills") or [])
            )
            if key
        ]

        try:
            total_forgotten = float(metadata.get("total_forgotten", 0.0))
        except (TypeError, ValueError):
            total_forgotten = 0.0

        applied_total = self._get_skill_total_learned(total_forgotten, applied, applied_key)
        specific_total = self._get_skill_total_learned(total_forgotten, specific, specific_key)
        secondary_totals = {
            key: self._get_skill_total_learned(total_forgotten, applied, key)
            for key in secondary_keys
        }

        applied_value = max(0.0, applied_total - total_forgotten)
        specific_value = max(0.0, specific_total - total_forgotten)
        secondary_values = {
            key: max(0.0, total - total_forgotten)
            for key, total in secondary_totals.items()
        }

        task = {
            "duration": duration,
            "output_good_type": recipe,
        }

        specific_gain = self._effective_specific_learning(monster, specific_value, task, applied_value)
        primary_gain = self._effective_primary_learning(monster, applied_value, task)
        secondary_gains = {
            key: self._effective_secondary_learning(monster, value, task)
            for key, value in secondary_values.items()
        }
        forgetting_gain = self._effective_forgetting(monster, total_forgotten, task)

        applied[applied_key] = applied_total + primary_gain
        specific[specific_key] = specific_total + specific_gain
        for key, gain in secondary_gains.items():
            applied[key] = secondary_totals[key] + gain

        total_forgotten += forgetting_gain
        for key in list(applied.keys()):
            applied[key] = max(applied[key], total_forgotten)
        for key in list(specific.keys()):
            specific[key] = max(specific[key], total_forgotten)

        skills["applied"] = applied
        skills["specific"] = specific
        metadata["skills"] = skills
        metadata["total_forgotten"] = total_forgotten
        self._apply_metadata(monster, metadata, updates)

        return {
            "specific_skill": specific_key,
            "specific_gain": round(specific_gain, 6),
            "primary_skill": applied_key,
            "primary_gain": round(primary_gain, 6),
            "secondary_gains": {key: round(gain, 6) for key, gain in secondary_gains.items()},
            "forgetting": round(forgetting_gain, 6),
        }

    def _process_monster_economy(
        self,
        entities: list[Entity],
        updates: list[EntityUpdate],
        creates: list[EntityCreate],
        events: list[dict[str, Any]],
        tick_number: int,
    ) -> None:
        for monster in entities:
            if self._entity_kind(monster) != KIND_MONSTER:
                continue
            self._process_upkeep(monster, entities, updates, creates, events)

    def _process_upkeep(
        self,
        monster: Entity,
        entities: list[Entity],
        updates: list[EntityUpdate],
        creates: list[EntityCreate],
        events: list[dict[str, Any]],
    ) -> None:
        if monster.owner_id is None:
            return

        metadata = dict(monster.metadata_ or {})
        last_paid = self._parse_datetime(metadata.get("last_upkeep_paid"))
        if last_paid is None:
            last_paid = self._parse_datetime(metadata.get("created_at"))
        if last_paid is None:
            return

        now = datetime.utcnow()
        real_seconds = (now - last_paid).total_seconds()
        game_seconds = real_seconds * GAME_TIME_MULTIPLIER
        game_days = game_seconds / (24 * 60 * 60)

        if game_days < UPKEEP_CYCLE_DAYS:
            updated = False
            if "upkeep_overdue" in metadata:
                metadata.pop("upkeep_overdue", None)
                updated = True
            if "upkeep_overdue_since" in metadata:
                metadata.pop("upkeep_overdue_since", None)
                updated = True
            if "upkeep_required" in metadata:
                metadata.pop("upkeep_required", None)
                updated = True
            if updated:
                self._apply_metadata(monster, metadata, updates)
            return

        monster_type = str(metadata.get("monster_type", "")).lower()
        upkeep_cost = int(self._monster_types.get(monster_type, {}).get("cost", 50))
        if upkeep_cost <= 0:
            return

        commune = self._ensure_commune(entities, creates, monster.owner_id)
        if commune is None:
            return
        commune_metadata = self._get_commune_metadata(commune)
        renown = int(commune_metadata.get("renown", STARTING_RENOWN))

        if renown < upkeep_cost:
            updated = False
            if not metadata.get("upkeep_overdue"):
                metadata["upkeep_overdue"] = True
                metadata["upkeep_overdue_since"] = metadata.get("upkeep_overdue_since") or now.isoformat()
                updated = True
            if metadata.get("upkeep_required") != upkeep_cost:
                metadata["upkeep_required"] = upkeep_cost
                updated = True
            if updated:
                self._apply_metadata(monster, metadata, updates)
            return

        commune_metadata["renown"] = renown - upkeep_cost
        self._set_commune_metadata(commune, commune_metadata, updates)

        metadata["last_upkeep_paid"] = now.isoformat()
        metadata.pop("upkeep_overdue", None)
        metadata.pop("upkeep_overdue_since", None)
        metadata.pop("upkeep_required", None)
        self._apply_metadata(monster, metadata, updates)

    def _ensure_commune(
        self,
        entities: list[Entity],
        creates: list[EntityCreate],
        owner_id: UUID | None,
    ) -> Entity | EntityCreate | None:
        if owner_id is None:
            return None

        commune = self._find_commune_entity(entities, owner_id)
        if commune is not None:
            return commune

        pending = self._find_commune_create(creates, owner_id)
        if pending is not None:
            return pending

        commune_create = EntityCreate(
            x=0,
            y=0,
            width=0,
            height=0,
            owner_id=owner_id,
            metadata={
                "kind": KIND_COMMUNE,
                "renown": STARTING_RENOWN,
                "total_renown_spent": 0,
            },
        )
        creates.append(commune_create)
        return commune_create

    def _find_commune_entity(self, entities: list[Entity], owner_id: UUID) -> Entity | None:
        for entity in entities:
            if self._entity_kind(entity) != KIND_COMMUNE:
                continue
            if entity.owner_id == owner_id:
                return entity
        return None

    def _find_commune_create(
        self,
        creates: list[EntityCreate],
        owner_id: UUID,
    ) -> EntityCreate | None:
        for create in creates:
            if getattr(create, "owner_id", None) != owner_id:
                continue
            metadata = getattr(create, "metadata", None) or {}
            if metadata.get("kind") == KIND_COMMUNE:
                return create
        return None

    def _get_commune_metadata(self, commune: Entity | EntityCreate | None) -> dict[str, Any]:
        if commune is None:
            return {"kind": KIND_COMMUNE, "renown": STARTING_RENOWN, "total_renown_spent": 0}
        metadata = {}
        if hasattr(commune, "metadata_"):
            metadata = dict(commune.metadata_ or {})
        elif hasattr(commune, "metadata"):
            metadata = dict(getattr(commune, "metadata", None) or {})
        if "renown" not in metadata:
            metadata["renown"] = STARTING_RENOWN
        if "total_renown_spent" not in metadata:
            metadata["total_renown_spent"] = 0
        metadata["kind"] = KIND_COMMUNE
        return metadata

    def _set_commune_metadata(
        self,
        commune: Entity | EntityCreate | None,
        metadata: dict[str, Any],
        updates: list[EntityUpdate],
    ) -> None:
        if commune is None:
            return
        metadata.setdefault("kind", KIND_COMMUNE)
        if hasattr(commune, "metadata_"):
            self._apply_metadata(commune, metadata, updates)
        elif hasattr(commune, "metadata"):
            commune.metadata = metadata

    def _credit_renown(
        self,
        entities: list[Entity],
        creates: list[EntityCreate],
        updates: list[EntityUpdate],
        owner_id: UUID | str | None,
        amount: int,
    ) -> None:
        if amount <= 0 or owner_id is None:
            return
        owner_uuid = owner_id if isinstance(owner_id, UUID) else self._parse_entity_id(owner_id)
        if owner_uuid is None:
            return
        commune = self._ensure_commune(entities, creates, owner_uuid)
        if commune is None:
            return
        commune_metadata = self._get_commune_metadata(commune)
        renown = int(commune_metadata.get("renown", STARTING_RENOWN))
        commune_metadata["renown"] = renown + amount
        self._set_commune_metadata(commune, commune_metadata, updates)

    def _get_cost_multiplier(self, total_renown_spent: int) -> float:
        multiplier = 1.0 + (total_renown_spent / 1000) * 0.1
        return min(3.0, multiplier)

    def _get_adjusted_cost(self, base_cost: int, commune_metadata: dict[str, Any]) -> int:
        total_spent = int(commune_metadata.get("total_renown_spent", 0))
        multiplier = self._get_cost_multiplier(total_spent)
        return int(base_cost * multiplier)

    def _mark_last_transporter(
        self,
        item: Entity,
        transporter: Entity,
        updates: list[EntityUpdate],
    ) -> None:
        metadata = dict(item.metadata_ or {})
        metadata["last_transporter_monster_id"] = str(transporter.id)
        if transporter.owner_id is not None:
            metadata["last_transporter_player_id"] = str(transporter.owner_id)
        self._apply_metadata(item, metadata, updates)

    def _is_being_pushed_by_other(self, entity: Entity, pusher_id: UUID) -> bool:
        metadata = entity.metadata_ or {}
        current = metadata.get("being_pushed_by")
        if current is None:
            return False
        return str(current) != str(pusher_id)

    def _mark_active_push(
        self,
        entity: Entity,
        pusher_id: UUID,
        updates: list[EntityUpdate],
        active_pushes: dict[UUID, UUID],
    ) -> None:
        metadata = dict(entity.metadata_ or {})
        metadata["being_pushed_by"] = str(pusher_id)
        self._apply_metadata(entity, metadata, updates)
        active_pushes[entity.id] = pusher_id

    def _clear_active_push(
        self,
        entity: Entity,
        updates: list[EntityUpdate],
        active_pushes: dict[UUID, UUID],
    ) -> None:
        active_pushes.pop(entity.id, None)
        metadata = dict(entity.metadata_ or {})
        if metadata.pop("being_pushed_by", None) is not None:
            self._apply_metadata(entity, metadata, updates)

    def _clear_active_pushes(
        self,
        active_pushes: dict[UUID, UUID],
        entity_map: dict[UUID, Entity],
        updates: list[EntityUpdate],
    ) -> None:
        for entity_id in list(active_pushes.keys()):
            entity = entity_map.get(entity_id)
            if entity is None:
                continue
            self._clear_active_push(entity, updates, active_pushes)

    def _can_monster_push(self, monster: Entity, item: Entity) -> tuple[bool, str]:
        item_weight = self._get_item_weight(item)
        capacity = self._get_monster_capacity(monster)
        if item_weight > capacity:
            return False, f"Item weight ({item_weight}) exceeds capacity ({capacity})"
        return True, ""

    def _get_item_weight(self, item: Entity) -> int:
        metadata = item.metadata_ or {}
        if "weight" in metadata:
            try:
                return int(metadata["weight"])
            except (TypeError, ValueError):
                return 1
        if self._entity_kind(item) == KIND_WAGON:
            return 10
        good_type = metadata.get("good_type")
        entry = self._get_good_type_entry(str(good_type) if good_type else None)
        if entry:
            return self._calculate_item_weight(entry, metadata)
        return 1

    def _get_item_max_durability(self, metadata: dict[str, Any]) -> int:
        entry = self._get_good_type_entry(metadata.get("good_type"))
        if entry and self._is_workshop_entry(entry):
            return 1000
        return 100

    def _get_monster_capacity(self, monster: Entity) -> int:
        metadata = monster.metadata_ or {}
        stats = metadata.get("stats") or {}
        try:
            strength = int(stats.get("str", 8))
        except (TypeError, ValueError):
            strength = 8
        return strength + self._get_monster_age_bonus(metadata)

    def _get_monster_age_bonus(self, metadata: dict[str, Any]) -> int:
        created_at = metadata.get("created_at")
        if not created_at:
            return 0
        created_dt = self._parse_datetime(created_at)
        if created_dt is None:
            return 0
        delta = datetime.utcnow() - created_dt
        game_seconds = delta.total_seconds() * 30
        game_days = game_seconds / (24 * 60 * 60)
        if game_days >= 60:
            return 2
        if game_days >= 30:
            return 1
        return 0

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if value is None:
            return None
        try:
            return datetime.fromisoformat(value)
        except (ValueError, TypeError):
            return None

    def _attempt_push(
        self,
        entities: list[Entity],
        mover: Entity,
        pushed: Entity,
        dx: int,
        dy: int,
        updates: list[EntityUpdate],
        deletes: list[UUID],
        zone_width: int,
        zone_height: int,
        zone_def: dict[str, Any] | None,
        events: list[dict[str, Any]],
        touched_dispensers: set[UUID],
        creates: list[EntityCreate] | None = None,
    ) -> bool:
        original_x = pushed.x
        original_y = pushed.y
        old_mover_x = mover.x
        old_mover_y = mover.y
        new_x = pushed.x + dx
        new_y = pushed.y + dy

        if not self._is_in_bounds(new_x, new_y, pushed, zone_width, zone_height):
            return False

        if self._is_terrain_blocked(zone_def, new_x, new_y):
            return False

        source_dispenser = self._find_entity_at_kind(entities, KIND_DISPENSER, original_x, original_y)
        target_workshop = self._find_entity_at_kind(entities, KIND_WORKSHOP, new_x, new_y)
        if target_workshop is None:
            target_workshop = self._find_entity_at_kind(entities, KIND_GATHERING, new_x, new_y)
        target_dispenser = self._find_entity_at_kind(entities, KIND_DISPENSER, new_x, new_y)
        target_delivery = self._find_entity_at_kind(entities, KIND_DELIVERY, new_x, new_y)
        target_wagon = self._find_entity_at_kind(entities, KIND_WAGON, new_x, new_y)

        if target_workshop is not None:
            if not self._is_workshop_interior(target_workshop, new_x, new_y):
                return False
            blocker = self._find_blocker(
                entities,
                pushed,
                new_x,
                new_y,
                ignore_ids={mover.id, pushed.id, target_workshop.id},
            )
            if blocker is not None:
                return False
            self._mark_last_transporter(pushed, mover, updates)
            if not self._deposit_into_workshop(
                item=pushed,
                workshop=target_workshop,
                slot_x=new_x,
                slot_y=new_y,
                entities=entities,
                updates=updates,
                events=events,
            ):
                return False

            self._apply_move(mover, mover.x + dx, mover.y + dy, updates)
            self._maybe_move_hitched_wagon(mover, old_mover_x, old_mover_y, entities, updates)
            if source_dispenser is not None:
                touched_dispensers.add(source_dispenser.id)
            return True

        if target_dispenser is not None:
            blocker = self._find_blocker(
                entities,
                pushed,
                new_x,
                new_y,
                ignore_ids={mover.id, pushed.id, target_dispenser.id},
            )
            if blocker is not None:
                return False
            self._mark_last_transporter(pushed, mover, updates)
            if not self._deposit_into_dispenser(
                item=pushed,
                dispenser=target_dispenser,
                slot_x=new_x,
                slot_y=new_y,
                entities=entities,
                updates=updates,
                events=events,
            ):
                return False

            self._apply_move(mover, mover.x + dx, mover.y + dy, updates)
            self._maybe_move_hitched_wagon(mover, old_mover_x, old_mover_y, entities, updates)
            touched_dispensers.add(target_dispenser.id)
            if source_dispenser is not None:
                touched_dispensers.add(source_dispenser.id)
            return True

        if target_delivery is not None:
            blocker = self._find_blocker(
                entities,
                pushed,
                new_x,
                new_y,
                ignore_ids={mover.id, pushed.id, target_delivery.id},
            )
            if blocker is not None:
                return False
            if not self._deliver_item(
                item=pushed,
                delivery=target_delivery,
                transporter=mover,
                entities=entities,
                creates=creates or [],
                deletes=deletes,
                updates=updates,
                events=events,
            ):
                return False
            self._apply_move(mover, mover.x + dx, mover.y + dy, updates)
            self._maybe_move_hitched_wagon(mover, old_mover_x, old_mover_y, entities, updates)
            if source_dispenser is not None:
                touched_dispensers.add(source_dispenser.id)
            return True

        if target_wagon is not None and self._entity_kind(pushed) == KIND_ITEM:
            blocker = self._find_blocker(
                entities,
                pushed,
                new_x,
                new_y,
                ignore_ids={mover.id, pushed.id, target_wagon.id},
            )
            if blocker is not None:
                return False
            if not self._load_item_into_wagon(
                item=pushed,
                wagon=target_wagon,
                slot_x=new_x,
                slot_y=new_y,
                entities=entities,
                updates=updates,
                events=events,
                transporter=mover,
            ):
                return False
            self._apply_move(mover, mover.x + dx, mover.y + dy, updates)
            self._maybe_move_hitched_wagon(mover, old_mover_x, old_mover_y, entities, updates)
            if source_dispenser is not None:
                touched_dispensers.add(source_dispenser.id)
            return True

        blocker = self._find_blocker(
            entities,
            pushed,
            new_x,
            new_y,
            ignore_ids={mover.id, pushed.id},
        )
        if blocker is not None:
            return False

        if self._entity_kind(pushed) == KIND_WAGON:
            self._apply_wagon_move(pushed, new_x, new_y, entities, updates)
        else:
            self._apply_move(pushed, new_x, new_y, updates)
            self._mark_last_transporter(pushed, mover, updates)
        self._apply_move(mover, mover.x + dx, mover.y + dy, updates)
        self._maybe_move_hitched_wagon(mover, old_mover_x, old_mover_y, entities, updates)
        if source_dispenser is not None:
            touched_dispensers.add(source_dispenser.id)
        return True

    def _is_terrain_blocked(self, zone_def: dict[str, Any] | None, x: int, y: int) -> bool:
        if not zone_def:
            return False
        terrain = zone_def.get("terrain") or {}
        blocked = zone_def.get("blocked") or zone_def.get("blocked_cells") or terrain.get("blocked") or []
        for cell in blocked:
            if isinstance(cell, (list, tuple)) and len(cell) >= 2:
                if cell[0] == x and cell[1] == y:
                    return True
        return False

    def _find_entity_at_kind(
        self,
        entities: list[Entity],
        kind: str,
        x: int,
        y: int,
    ) -> Entity | None:
        for entity in entities:
            if self._entity_kind(entity) != kind:
                continue
            ex, ey, ew, eh = self._entity_rect(entity)
            if self._rects_overlap(x, y, 1, 1, ex, ey, ew, eh):
                return entity
        return None

    def _is_workshop_interior(self, workshop: Entity, x: int, y: int) -> bool:
        width, height = self._entity_size(workshop)
        rel_x = x - workshop.x
        rel_y = y - workshop.y
        if rel_x <= 0 or rel_y <= 0:
            return False
        if rel_x >= width - 1 or rel_y >= height - 1:
            return False
        return True

    def _is_workshop_tool_slot(self, workshop: Entity, x: int, y: int) -> bool:
        if not self._is_workshop_interior(workshop, x, y):
            return False
        rel_x = x - workshop.x
        return rel_x == 1

    def _get_workshop_interior_bounds(self, workshop: Entity) -> tuple[int, int, int, int]:
        wx, wy, ww, wh = self._entity_rect(workshop)
        return wx + 1, wy + 1, wx + ww - 2, wy + wh - 2

    def _get_workshop_recipes(self, workshop: Entity) -> list[dict[str, Any]]:
        if self._is_gathering_spot(workshop):
            gathering_good = (workshop.metadata_ or {}).get("gathering_good_type")
            recipe = self._get_recipe_entry(gathering_good)
            return [recipe] if recipe else []
        # TODO: map workshop types/tags to recipes instead of exposing every workshop recipe.
        return [entry for entry in self._good_types.values() if entry.get("requires_workshop")]

    def _max_size_for_tag_groups(self, tag_groups: list[list[str]]) -> tuple[int, int]:
        max_w, max_h = DEFAULT_ITEM_SIZE
        if not tag_groups:
            return max_w, max_h
        for group in tag_groups:
            required = [str(tag).lower() for tag in group]
            for entry in self._good_types.values():
                tags = [str(tag).lower() for tag in entry.get("type_tags") or []]
                if all(tag in tags for tag in required):
                    width, height = self._get_good_type_size(entry)
                    max_w = max(max_w, width)
                    max_h = max(max_h, height)
        return max_w, max_h

    def _get_workshop_slot_max_size(self, workshop: Entity, role: str) -> tuple[int, int]:
        tag_groups: list[list[str]] = []
        for recipe in self._get_workshop_recipes(workshop):
            if role == "tool":
                tag_groups.extend(recipe.get("tools_required_tags") or [])
            else:
                tag_groups.extend(recipe.get("input_goods_tags_required") or [])
        return self._max_size_for_tag_groups(tag_groups)

    def _get_workshop_slot_role(
        self,
        workshop: Entity,
        item_metadata: dict[str, Any],
        slot_x: int,
        slot_y: int,
    ) -> str:
        is_tool = self._is_tool_item(item_metadata)
        is_tool_slot = self._is_workshop_tool_slot(workshop, slot_x, slot_y)
        return "tool" if is_tool and is_tool_slot else "input"

    def _stored_item_rect(self, item: Entity) -> tuple[int, int, int, int]:
        metadata = item.metadata_ or {}
        slot = metadata.get("stored_slot") or {}
        try:
            x = int(slot.get("x", item.x))
            y = int(slot.get("y", item.y))
        except (TypeError, ValueError):
            x = item.x
            y = item.y
        width, height = self._get_item_size_from_metadata(metadata)
        return x, y, width, height

    def _item_fits_in_workshop(
        self,
        workshop: Entity,
        item: Entity,
        slot_x: int,
        slot_y: int,
        role: str,
        entities: list[Entity],
    ) -> bool:
        item_metadata = item.metadata_ or {}
        width, height = self._get_item_size_from_metadata(item_metadata)
        max_w, max_h = self._get_workshop_slot_max_size(workshop, role)
        if width > max_w or height > max_h:
            return False

        min_x, min_y, max_x, max_y = self._get_workshop_interior_bounds(workshop)
        if slot_x < min_x or slot_y < min_y:
            return False
        if slot_x + width - 1 > max_x or slot_y + height - 1 > max_y:
            return False

        new_rect = (slot_x, slot_y, width, height)
        for entity in entities:
            if self._entity_kind(entity) != KIND_ITEM:
                continue
            metadata = entity.metadata_ or {}
            if not metadata.get("is_stored"):
                continue
            if metadata.get("container_id") != str(workshop.id):
                continue
            ex, ey, ew, eh = self._stored_item_rect(entity)
            if self._rects_overlap(new_rect[0], new_rect[1], new_rect[2], new_rect[3], ex, ey, ew, eh):
                return False
        return True

    def _deposit_into_workshop(
        self,
        item: Entity,
        workshop: Entity,
        slot_x: int,
        slot_y: int,
        entities: list[Entity],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
    ) -> bool:
        item_metadata = dict(item.metadata_ or {})
        workshop_metadata = dict(workshop.metadata_ or {})

        role = self._get_workshop_slot_role(workshop, item_metadata, slot_x, slot_y)

        if self._is_gathering_spot(workshop) and role != "tool":
            return False

        if not self._item_fits_in_workshop(workshop, item, slot_x, slot_y, role, entities):
            return False

        if role == "tool":
            max_durability = item_metadata.get("max_durability")
            if max_durability is None:
                max_durability = self._get_item_max_durability(item_metadata)
            durability = item_metadata.get("durability")
            if durability is None:
                durability = max_durability
            try:
                max_durability = int(max_durability)
            except (TypeError, ValueError):
                max_durability = 100
            try:
                durability = int(durability)
            except (TypeError, ValueError):
                durability = max_durability
            item_metadata["durability"] = durability
            item_metadata["max_durability"] = max_durability
            item_metadata["tool_tags"] = self._get_tool_tags(item_metadata)

        self._ensure_item_size_metadata(item_metadata)
        item_metadata["is_stored"] = True
        item_metadata["container_id"] = str(workshop.id)
        item_metadata["stored_slot"] = {"x": slot_x, "y": slot_y}
        item_metadata["stored_role"] = role

        self._apply_move(item, slot_x, slot_y, updates)
        self._apply_metadata(item, item_metadata, updates)

        key = "tool_item_ids" if role == "tool" else "input_item_ids"
        stored_ids = list(workshop_metadata.get(key) or [])
        stored_ids.append(str(item.id))
        workshop_metadata[key] = stored_ids
        self._apply_metadata(workshop, workshop_metadata, updates)

        events.append({
            "type": "deposit",
            "entity_id": str(item.id),
            "workshop_id": str(workshop.id),
        })
        return True

    def _deposit_into_dispenser(
        self,
        item: Entity,
        dispenser: Entity,
        slot_x: int,
        slot_y: int,
        entities: list[Entity],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
    ) -> bool:
        item_metadata = dict(item.metadata_ or {})
        dispenser_metadata = dict(dispenser.metadata_ or {})

        if not self._container_accepts_item(dispenser, item, entities):
            return False

        item_type = self._normalize_good_type_key(item_metadata.get("good_type"))
        stored_type = self._normalize_good_type_key(dispenser_metadata.get("stored_good_type"))
        if stored_type and item_type and stored_type != item_type:
            return False

        if stored_type:
            dispenser_metadata["stored_good_type"] = stored_type
        elif item_type:
            dispenser_metadata["stored_good_type"] = item_type

        self._ensure_item_size_metadata(item_metadata)
        item_metadata["is_stored"] = True
        item_metadata["container_id"] = str(dispenser.id)
        item_metadata["stored_slot"] = {"x": slot_x, "y": slot_y}

        self._apply_move(item, slot_x, slot_y, updates)
        self._apply_metadata(item, item_metadata, updates)
        self._apply_metadata(dispenser, dispenser_metadata, updates)

        events.append({
            "type": "dispenser_deposit",
            "entity_id": str(item.id),
            "dispenser_id": str(dispenser.id),
        })
        return True

    def _deliver_item(
        self,
        item: Entity,
        delivery: Entity,
        transporter: Entity,
        entities: list[Entity],
        creates: list[EntityCreate],
        deletes: list[UUID],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
    ) -> bool:
        item_metadata = item.metadata_ or {}
        delivery_metadata = dict(delivery.metadata_ or {})
        accepted_tags = delivery_metadata.get("dropoff_accepted_tags") or delivery_metadata.get("accepted_tags")
        if accepted_tags:
            accepted_set = {str(tag).lower() for tag in accepted_tags if tag}
            item_tags = self._get_item_tags(item_metadata)
            if not any(tag in accepted_set for tag in item_tags):
                return False

        value = item_metadata.get("value")
        try:
            value = int(value)
        except (TypeError, ValueError):
            entry = self._get_good_type_entry(item_metadata.get("good_type"))
            if entry:
                raw_materials = item_metadata.get("raw_materials") or []
                max_depth = item_metadata.get("raw_material_max_depth", 0)
                quality = item_metadata.get("quality", 0)
                value = self._calculate_item_value(entry, raw_materials, max_depth, quality, None)
            else:
                value = 0

        shares = self._get_item_shares(item_metadata)
        total_shares = sum(float(share.get("count", 0)) for share in shares)
        if total_shares <= 0:
            total_shares = 1

        share_distribution = []
        for share in shares:
            count = float(share.get("count", 0))
            if count <= 0:
                continue
            player_id = share.get("player_id")
            if not player_id and share.get("monster_id"):
                monster_id = str(share.get("monster_id"))
                for entity in entities:
                    if self._entity_kind(entity) == KIND_MONSTER and str(entity.id) == monster_id:
                        if entity.owner_id is not None:
                            player_id = str(entity.owner_id)
                        break
            if not player_id:
                continue
            renown_gain = int(value * count / total_shares)
            if renown_gain <= 0:
                continue
            self._credit_renown(
                entities=entities,
                creates=creates,
                updates=updates,
                owner_id=player_id,
                amount=renown_gain,
            )
            share_distribution.append({
                "player_id": player_id,
                "monster_id": share.get("monster_id"),
                "shares": count,
                "renown": renown_gain,
                "description": share.get("description"),
            })

        delivered = list(delivery_metadata.get("delivered_items") or [])
        delivered.append({
            "good_type": item_metadata.get("good_type"),
            "timestamp": datetime.utcnow().isoformat(),
            "value": value,
            "contributors": share_distribution,
        })
        delivery_metadata["delivered_items"] = delivered
        delivery_metadata["delivered_count"] = len(delivered)
        delivery_metadata["last_share_distribution"] = share_distribution
        self._apply_metadata(delivery, delivery_metadata, updates)

        deletes.append(item.id)
        events.append({
            "type": "delivery",
            "entity_id": str(item.id),
            "delivery_id": str(delivery.id),
            "value": value,
            "contributors": share_distribution,
        })
        return True

    def _sync_dispensers(
        self,
        dispenser_ids: set[UUID],
        entities: list[Entity],
        updates: list[EntityUpdate],
    ) -> None:
        for dispenser_id in dispenser_ids:
            dispenser = next((e for e in entities if e.id == dispenser_id), None)
            if dispenser is None:
                continue
            stored_items = []
            visible_items = []
            for entity in entities:
                if self._entity_kind(entity) != KIND_ITEM:
                    continue
                metadata = entity.metadata_ or {}
                if metadata.get("container_id") == str(dispenser_id) and metadata.get("is_stored"):
                    stored_items.append(entity)
                elif entity.x == dispenser.x and entity.y == dispenser.y and not metadata.get("is_stored"):
                    visible_items.append(entity)

            if not visible_items and stored_items:
                item = stored_items[0]
                metadata = dict(item.metadata_ or {})
                metadata["is_stored"] = False
                metadata.pop("container_id", None)
                metadata.pop("stored_slot", None)
                self._apply_move(item, dispenser.x, dispenser.y, updates)
                self._apply_metadata(item, metadata, updates)

    def _is_tool_item(self, metadata: dict[str, Any]) -> bool:
        good_type = str(metadata.get("good_type", "")).lower()
        if "tool" in good_type or any(tag in good_type for tag in ("hammer", "tongs", "anvil", "loom")):
            return True
        return bool(metadata.get("is_tool"))

    def _get_tool_tags(self, metadata: dict[str, Any]) -> list[str]:
        tags = list(metadata.get("tool_tags") or [])
        good_type = str(metadata.get("good_type", "")).lower()
        for tag in ("hammer", "tongs", "anvil", "loom"):
            if tag in good_type and tag not in tags:
                tags.append(tag)
        return tags

    def _find_blocker(
        self,
        entities: list[Entity],
        mover: Entity,
        new_x: int,
        new_y: int,
        ignore_ids: set[UUID] | None = None,
    ) -> Entity | None:
        mover_w, mover_h = self._entity_size(mover)
        ignore_ids = ignore_ids or set()
        for entity in entities:
            if entity.id == mover.id or entity.id in ignore_ids:
                continue
            if not self._is_blocking(entity):
                continue
            if self._rects_overlap(new_x, new_y, mover_w, mover_h, *self._entity_rect(entity)):
                return entity
        return None

    def _find_adjacent_entity(self, monster: Entity, entities: list[Entity]) -> Entity | None:
        for dx, dy in DIR_TO_DELTA.values():
            check_x = monster.x + dx
            check_y = monster.y + dy
            for entity in entities:
                if entity.id == monster.id:
                    continue
                if self._rects_overlap(check_x, check_y, 1, 1, *self._entity_rect(entity)):
                    return entity
        return None

    def _entity_kind(self, entity: Entity) -> str | None:
        return (entity.metadata_ or {}).get("kind")

    def _is_gathering_spot(self, entity: Entity) -> bool:
        if self._entity_kind(entity) == KIND_GATHERING:
            return True
        metadata = entity.metadata_ or {}
        return bool(metadata.get("gathering_good_type"))

    def _entity_size(self, entity: Entity) -> tuple[int, int]:
        width = entity.width if entity.width and entity.width > 0 else 1
        height = entity.height if entity.height and entity.height > 0 else 1
        if self._entity_kind(entity) == KIND_ITEM and width == 1 and height == 1:
            width, height = self._get_item_size_from_metadata(entity.metadata_ or {})
        return width, height

    def _entity_rect(self, entity: Entity) -> tuple[int, int, int, int]:
        width, height = self._entity_size(entity)
        return entity.x, entity.y, width, height

    def _is_blocking(self, entity: Entity) -> bool:
        metadata = entity.metadata_ or {}
        if metadata.get("is_stored"):
            return False
        if "blocks_movement" in metadata:
            return bool(metadata.get("blocks_movement"))
        return self._entity_kind(entity) in BLOCKING_KINDS

    def _is_in_bounds(
        self,
        x: int,
        y: int,
        entity: Entity,
        zone_width: int,
        zone_height: int,
    ) -> bool:
        width, height = self._entity_size(entity)
        if x < 0 or y < 0:
            return False
        if x + width > zone_width:
            return False
        if y + height > zone_height:
            return False
        return True

    def _rects_overlap(
        self,
        ax: int,
        ay: int,
        aw: int,
        ah: int,
        bx: int,
        by: int,
        bw: int,
        bh: int,
    ) -> bool:
        return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by

    def _intent_to_delta(self, data: dict[str, Any]) -> tuple[int, int]:
        direction = data.get("direction")
        if direction in DIR_TO_DELTA:
            return DIR_TO_DELTA[direction]
        dx = data.get("dx", 0)
        dy = data.get("dy", 0)
        if not isinstance(dx, int) or not isinstance(dy, int):
            return (0, 0)
        dx = max(-1, min(1, dx))
        dy = max(-1, min(1, dy))
        return (dx, dy)

    def _parse_entity_id(self, value: Any) -> UUID | None:
        if not value:
            return None
        try:
            return UUID(str(value))
        except ValueError:
            return None

    def _get_owned_monster(self, intent: Intent, entity_map: dict[UUID, Entity]) -> Entity | None:
        monster_id = self._parse_entity_id(intent.data.get("monster_id"))
        if monster_id is None:
            monster_id = self._parse_entity_id(intent.data.get("entity_id"))
        if monster_id is None:
            return None
        monster = entity_map.get(monster_id)
        if monster is None:
            return None
        if monster.owner_id != intent.player_id:
            return None
        if self._entity_kind(monster) != KIND_MONSTER:
            return None
        return monster

    def _build_monster_metadata(
        self,
        name: str,
        monster_type: str,
        definition: dict[str, Any],
    ) -> dict[str, Any]:
        stats = definition.get("stats", {})
        return {
            "kind": KIND_MONSTER,
            "name": name,
            "monster_type": monster_type,
            "stats": {
                "str": int(stats.get("str", 8)),
                "dex": int(stats.get("dex", 8)),
                "con": int(stats.get("con", 8)),
                "int": int(stats.get("int", 8)),
                "wis": int(stats.get("wis", 8)),
                "cha": int(stats.get("cha", 8)),
            },
            "body_cap": int(definition.get("body_cap", 100)),
            "mind_cap": int(definition.get("mind_cap", 100)),
            "equipment": {"body": [], "mind": []},
            "skills": {
                "transferable": [],
                "applied": {},
                "specific": {},
                "last_used": {},
                "last_decay_at": {},
            },
            "total_forgotten": 0.0,
            "current_task": {
                "is_recording": False,
                "is_playing": False,
                "actions": [],
                "play_index": 0,
            },
            "online": True,
            "created_at": datetime.utcnow().isoformat(),
        }

    def _choose_spawn_point(
        self,
        entities: list[Entity],
        zone_def: dict[str, Any] | None,
        zone_width: int,
        zone_height: int,
    ) -> tuple[int, int]:
        spawn_points = []
        if zone_def:
            spawn_points = zone_def.get("spawn_points") or []
        if not spawn_points:
            spawn_points = [{"x": 2, "y": 2}]

        for candidate in spawn_points:
            x = int(candidate.get("x", 0))
            y = int(candidate.get("y", 0))
            if 0 <= x < zone_width and 0 <= y < zone_height:
                if self._is_terrain_blocked(zone_def, x, y):
                    continue
                if self._find_blocker(entities, self._fake_entity(x, y), x, y) is None:
                    return x, y

        return (2, 2)

    def _bootstrap_zone(
        self,
        zone_def: dict[str, Any] | None,
        zone_width: int,
        zone_height: int,
    ) -> list[EntityCreate]:
        creates: list[EntityCreate] = []
        zone_name = zone_def.get("name") if zone_def else "Starting Village"

        creates.append(EntityCreate(
            x=0,
            y=0,
            width=0,
            height=0,
            metadata={
                "kind": KIND_WORLD,
                "zone_name": zone_name,
                "width": zone_width,
                "height": zone_height,
            },
        ))

        creates.extend(self._create_boundary_blocks(zone_width, zone_height))

        # Add a test item for pushing
        creates.append(EntityCreate(
            x=5,
            y=5,
            width=1,
            height=1,
            metadata={
                "kind": KIND_ITEM,
                "good_type": "test_item",
                "name": "Test Item",
                "quality": 1.0,
                "weight": 1,
            },
        ))

        static_entities = (zone_def or {}).get("static_entities") or []
        for entry in static_entities:
            create = self._entity_from_def(entry)
            if create is not None:
                creates.append(create)

        return creates

    def _create_boundary_blocks(self, zone_width: int, zone_height: int) -> list[EntityCreate]:
        if zone_width < 2 or zone_height < 2:
            return []
        return [
            EntityCreate(
                x=0,
                y=0,
                width=zone_width,
                height=1,
                metadata={"kind": KIND_TERRAIN},
            ),
            EntityCreate(
                x=0,
                y=zone_height - 1,
                width=zone_width,
                height=1,
                metadata={"kind": KIND_TERRAIN},
            ),
            EntityCreate(
                x=0,
                y=0,
                width=1,
                height=zone_height,
                metadata={"kind": KIND_TERRAIN},
            ),
            EntityCreate(
                x=zone_width - 1,
                y=0,
                width=1,
                height=zone_height,
                metadata={"kind": KIND_TERRAIN},
            ),
        ]

    def _entity_from_def(self, entry: dict[str, Any]) -> EntityCreate | None:
        kind = entry.get("kind")
        if not kind:
            return None
        x = int(entry.get("x", 0))
        y = int(entry.get("y", 0))
        width = int(entry.get("width", 1))
        height = int(entry.get("height", 1))
        metadata = dict(entry.get("metadata") or {})
        metadata["kind"] = kind
        if kind in (KIND_WORKSHOP, KIND_GATHERING) and "blocks_movement" not in metadata:
            metadata["blocks_movement"] = False
        return EntityCreate(
            x=x,
            y=y,
            width=width,
            height=height,
            metadata=metadata,
        )

    def _find_world_marker(self, entities: list[Entity]) -> Entity | None:
        for entity in entities:
            if self._entity_kind(entity) == KIND_WORLD:
                return entity
        return None

    def _load_zone_defs(self) -> list[dict[str, Any]]:
        base_dir = Path(__file__).resolve().parents[1]
        zone_dir = base_dir / "data" / "zones"
        if not zone_dir.exists():
            return []
        zone_defs = []
        for path in sorted(zone_dir.glob("*.json")):
            try:
                zone_defs.append(json.loads(path.read_text()))
            except json.JSONDecodeError:
                logger.warning("Invalid zone definition: %s", path)
        return zone_defs

    def _default_zone_def(self) -> dict[str, Any]:
        return {
            "name": "Starting Village",
            "width": 60,
            "height": 20,
            "spawn_points": [{"x": 3, "y": 3}],
            "static_entities": [],
        }

    def _load_good_types(self) -> dict[str, dict[str, Any]]:
        base_dir = Path(__file__).resolve().parents[1]
        good_types_path = base_dir / "data" / "tech_tree" / "good_types.json"
        if not good_types_path.exists():
            return {}
        try:
            payload = json.loads(good_types_path.read_text())
        except json.JSONDecodeError:
            return {}
        good_types = {}
        for entry in payload.get("good_types", []):
            name = entry.get("name")
            if name:
                good_types[str(name).lower()] = entry
        return good_types

    def _load_monster_types(self) -> dict[str, dict[str, Any]]:
        base_dir = Path(__file__).resolve().parents[1]
        monster_types_path = base_dir / "data" / "monster_types.json"
        if not monster_types_path.exists():
            return dict(DEFAULT_MONSTER_TYPES)
        try:
            payload = json.loads(monster_types_path.read_text())
        except json.JSONDecodeError:
            return dict(DEFAULT_MONSTER_TYPES)
        monster_types = payload.get("monster_types")
        if not isinstance(monster_types, dict):
            return dict(DEFAULT_MONSTER_TYPES)
        resolved: dict[str, dict[str, Any]] = {}
        for key, entry in monster_types.items():
            if not isinstance(entry, dict):
                continue
            resolved[str(key).lower()] = entry
        return resolved or dict(DEFAULT_MONSTER_TYPES)

    def _load_skill_defs(self) -> dict[str, Any]:
        base_dir = Path(__file__).resolve().parents[1]
        skills_path = base_dir / "data" / "skills.json"
        if not skills_path.exists():
            return {
                "transferable_skills": list(DEFAULT_TRANSFERABLE_SKILLS),
                "applied_skills": list(DEFAULT_APPLIED_SKILLS),
                "relevant_transferable_skills": {},
            }
        try:
            payload = json.loads(skills_path.read_text())
        except json.JSONDecodeError:
            return {
                "transferable_skills": list(DEFAULT_TRANSFERABLE_SKILLS),
                "applied_skills": list(DEFAULT_APPLIED_SKILLS),
                "relevant_transferable_skills": {},
            }

        def normalize(value: Any) -> list[str]:
            return [
                str(item).strip().lower().replace(" ", "_")
                for item in (value or [])
                if item
            ]

        transferable = normalize(payload.get("transferable_skills"))
        if not transferable:
            transferable = list(DEFAULT_TRANSFERABLE_SKILLS)
        payload["transferable_skills"] = transferable

        applied = normalize(payload.get("applied_skills"))
        payload["applied_skills"] = applied or list(DEFAULT_APPLIED_SKILLS)

        relevant = payload.get("relevant_transferable_skills") or {}
        normalized_relevant: dict[str, list[str]] = {}
        if isinstance(relevant, dict):
            for key, values in relevant.items():
                if not key:
                    continue
                normalized_relevant[str(key).strip().lower().replace(" ", "_")] = normalize(values)
        payload["relevant_transferable_skills"] = normalized_relevant

        return payload

    def _fake_entity(self, x: int, y: int) -> Entity:
        fake = Entity(zone_id=UUID(int=0), x=x, y=y, width=1, height=1)
        fake.metadata_ = {}
        return fake


game_module = MonsterWorkshopGame()
