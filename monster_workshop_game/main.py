"""Monster Workshop game module for gridtickmultiplayer."""

from __future__ import annotations

import json
import logging
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
KIND_DISPENSER = "dispenser"
KIND_WAGON = "wagon"
KIND_TERRAIN = "terrain_block"
KIND_SIGNPOST = "signpost"
KIND_DELIVERY = "delivery"

BLOCKING_KINDS = {
    KIND_MONSTER,
    KIND_ITEM,
    KIND_WORKSHOP,
    KIND_DISPENSER,
    KIND_WAGON,
    KIND_TERRAIN,
    KIND_DELIVERY,
}

PUSHABLE_KINDS = {
    KIND_ITEM,
    KIND_WAGON,
}

DIR_TO_DELTA = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}

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

TRANSFERABLE_SKILLS = [
    "Weaving",
    "Dyeing",
    "Pottery",
    "Smithing",
    "Carpentry",
    "Cooking",
    "Mining",
    "Farming",
    "Fishing",
    "Hunting",
    "Tailoring",
    "Leatherworking",
    "Glassblowing",
    "Jewelcrafting",
    "Alchemy",
    "Brewing",
    "Masonry",
    "Woodcutting",
]


class MonsterWorkshopGame:
    """Gridtickmultiplayer module for Monster Workshop."""

    def __init__(self) -> None:
        self._zone_defs = self._load_zone_defs()
        self._zone_id_to_def: dict[UUID, dict[str, Any]] = {}
        self._zone_sizes: dict[UUID, tuple[int, int]] = {}
        self._initialized_zones: set[UUID] = set()
        self._good_types = self._load_good_types()

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
        definition = DEFAULT_MONSTER_TYPES.get(monster_type)

        if definition is None:
            return None, {
                "type": "error",
                "message": f"Unknown monster type: {monster_type}",
                "target_player_id": str(intent.player_id),
            }

        transferable_requested = intent.data.get("transferable_skills") or []
        transferable_skills: list[str] = []
        if transferable_requested:
            if not isinstance(transferable_requested, list):
                return None, {
                    "type": "error",
                    "message": "Transferable skills must be a list",
                    "target_player_id": str(intent.player_id),
                }
            skill_lookup = {skill.lower(): skill for skill in TRANSFERABLE_SKILLS}
            invalid_skills = []
            for skill in transferable_requested:
                if not skill:
                    continue
                key = str(skill).strip().lower()
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

            if len(transferable_skills) > 3:
                return None, {
                    "type": "error",
                    "message": "Cannot select more than 3 transferable skills",
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
        if transferable_skills:
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
        if workshop is None or self._entity_kind(workshop) != KIND_WORKSHOP:
            return

        recipe_entry = self._get_recipe_entry(recipe_id)
        if recipe_entry is None:
            events.append({
                "type": "error",
                "message": "Unknown recipe",
                "target_player_id": str(intent.player_id),
            })
            return

        metadata = dict(workshop.metadata_ or {})
        workshop_type = metadata.get("workshop_type", "general")
        requires_workshop = recipe_entry.get("requires_workshop")
        if requires_workshop and requires_workshop != workshop_type:
            events.append({
                "type": "error",
                "message": f"Recipe requires {requires_workshop}",
                "target_player_id": str(intent.player_id),
            })
            return

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
            if self._entity_kind(workshop) != KIND_WORKSHOP:
                continue

            metadata = dict(workshop.metadata_ or {})
            recipe_entry = None
            recipe_name = metadata.get("selected_recipe_name") or metadata.get("selected_recipe_id")
            if recipe_name:
                recipe_entry = self._get_recipe_entry(recipe_name)

            input_items, tool_items = self._get_workshop_items(entities, workshop)
            missing_inputs, missing_tools = ([], [])
            if recipe_entry:
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
            output_create = self._create_output_item(workshop, recipe_entry, crafter, tool_items)
            if output_create is not None:
                creates.append(output_create)

            depleted_tools = self._consume_tool_durability(tool_items, updates, deletes)
            consumed_inputs = self._consume_input_items(input_items, deletes)

            skill_gain = self._apply_skill_gain(crafter, recipe_entry, updates)
            if skill_gain:
                metadata["last_skill_gained"] = skill_gain

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

    def _get_wagon_capacity(self, wagon: Entity) -> int:
        metadata = wagon.metadata_ or {}
        capacity = metadata.get("capacity")
        if capacity is not None:
            try:
                return int(capacity)
            except (TypeError, ValueError):
                pass
        width, height = self._entity_size(wagon)
        return max(1, width * height)

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
        loaded_items = self._get_wagon_items(entities, wagon)
        capacity = self._get_wagon_capacity(wagon)
        if len(loaded_items) >= capacity:
            events.append({
                "type": "wagon_full",
                "wagon_id": str(wagon.id),
            })
            return False

        if transporter is not None:
            self._mark_last_transporter(item, transporter, updates)

        item_metadata = dict(item.metadata_ or {})
        item_metadata["is_stored"] = True
        item_metadata["container_id"] = str(wagon.id)
        item_metadata["stored_role"] = "wagon"
        item_metadata["stored_offset"] = {"x": slot_x - wagon.x, "y": slot_y - wagon.y}

        self._apply_move(item, slot_x, slot_y, updates)
        self._apply_metadata(item, item_metadata, updates)

        wagon_metadata = dict(wagon.metadata_ or {})
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
        wagon = next((e for e in entities if e.id == hitched_id), None)
        if wagon is None or self._entity_kind(wagon) != KIND_WAGON:
            return
        self._apply_wagon_move(wagon, old_x, old_y, entities, updates)

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
            durability = metadata.get("durability", 1)
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
        key = good_type.replace("_", " ").strip()
        entry = self._good_types.get(key)
        if entry:
            return [str(tag).lower() for tag in entry.get("type_tags") or []]
        tags = []
        if good_type:
            tags.extend(good_type.replace("_", " ").split())
            tags.append(good_type)
        return tags

    def _calculate_crafting_duration(
        self,
        recipe: dict[str, Any],
        monster: Entity | None,
    ) -> int:
        base_duration = int(recipe.get("production_time", 60))
        if monster is None:
            return max(1, base_duration)
        stats = (monster.metadata_ or {}).get("stats") or {}
        dex = int(stats.get("dex", 10))
        int_stat = int(stats.get("int", 10))
        dex_bonus = max(0, dex - 10) * 0.02
        int_bonus = max(0, int_stat - 10) * 0.01
        total_reduction = min(0.5, dex_bonus + int_bonus)
        duration = int(base_duration * (1 - total_reduction))
        return max(1, duration)

    def _get_monster_by_id(self, entities: list[Entity], monster_id: Any) -> Entity | None:
        if not monster_id:
            return None
        for entity in entities:
            if self._entity_kind(entity) != KIND_MONSTER:
                continue
            if str(entity.id) == str(monster_id):
                return entity
        return None

    def _create_output_item(
        self,
        workshop: Entity,
        recipe: dict[str, Any],
        crafter: Entity | None,
        tools: list[Entity],
    ) -> EntityCreate | None:
        output_x = workshop.x + self._entity_size(workshop)[0] - 2
        output_y = workshop.y + self._entity_size(workshop)[1] - 2
        if output_x < 0 or output_y < 0:
            return None

        quality = 50
        if crafter is not None:
            stats = (crafter.metadata_ or {}).get("stats") or {}
            wis = int(stats.get("wis", 10))
            quality = min(100, 50 + max(0, wis - 10) * 2)

        name = recipe.get("name") or "Item"
        good_type = str(name).lower().replace(" ", "_")

        tool_creators = []
        for tool in tools:
            tool_metadata = tool.metadata_ or {}
            creator_id = tool_metadata.get("producer_player_id") or tool_metadata.get("creator_player_id")
            if creator_id and creator_id not in tool_creators:
                tool_creators.append(creator_id)

        return EntityCreate(
            x=output_x,
            y=output_y,
            width=1,
            height=1,
            metadata={
                "kind": KIND_ITEM,
                "name": name,
                "good_type": good_type,
                "quality": quality,
                "crafted_at": datetime.utcnow().isoformat(),
                "producer_monster_id": str(crafter.id) if crafter else None,
                "producer_player_id": str(crafter.owner_id) if crafter else None,
                "tool_creator_player_ids": tool_creators,
                "last_transporter_monster_id": str(crafter.id) if crafter else None,
                "last_transporter_player_id": str(crafter.owner_id) if crafter else None,
            },
        )

    def _consume_tool_durability(
        self,
        tools: list[Entity],
        updates: list[EntityUpdate],
        deletes: list[UUID],
    ) -> list[str]:
        depleted: list[str] = []
        for tool in tools:
            metadata = dict(tool.metadata_ or {})
            durability = metadata.get("durability")
            if durability is None:
                durability = 10
            try:
                durability = int(durability) - 1
            except (TypeError, ValueError):
                durability = 0
            metadata["durability"] = durability
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
        updates: list[EntityUpdate],
    ) -> dict[str, Any] | None:
        if monster is None:
            return None
        primary_skill = recipe.get("primary_applied_skill")
        if not primary_skill:
            return None

        metadata = dict(monster.metadata_ or {})
        skills = dict(metadata.get("skills") or {})
        applied = dict(skills.get("applied") or {})
        last_used = dict(skills.get("last_used") or {})

        current_level = float(applied.get(primary_skill, 0.0))
        stats = metadata.get("stats") or {}
        int_stat = int(stats.get("int", 10))
        int_bonus = max(0.0, (int_stat - 10) / 100)
        gain = 0.01 + int_bonus
        new_level = min(1.0, current_level + gain)
        applied[primary_skill] = round(new_level, 3)
        last_used[primary_skill] = datetime.utcnow().isoformat()

        skills["applied"] = applied
        skills["last_used"] = last_used
        metadata["skills"] = skills
        self._apply_metadata(monster, metadata, updates)

        return {
            "skill": primary_skill,
            "gain": round(gain, 3),
            "new_level": round(new_level, 3),
        }

    def _process_monster_economy(
        self,
        entities: list[Entity],
        updates: list[EntityUpdate],
        creates: list[EntityCreate],
        events: list[dict[str, Any]],
        tick_number: int,
    ) -> None:
        apply_decay = tick_number % SKILL_DECAY_INTERVAL_TICKS == 0
        for monster in entities:
            if self._entity_kind(monster) != KIND_MONSTER:
                continue
            if apply_decay:
                self._apply_skill_decay(monster, updates)
            self._process_upkeep(monster, entities, updates, creates, events)

    def _apply_skill_decay(self, monster: Entity, updates: list[EntityUpdate]) -> None:
        metadata = dict(monster.metadata_ or {})
        skills = dict(metadata.get("skills") or {})
        applied = dict(skills.get("applied") or {})
        if not applied:
            return

        last_used = dict(skills.get("last_used") or {})
        last_decay = dict(skills.get("last_decay_at") or {})
        created_at = self._parse_datetime(metadata.get("created_at")) or datetime.utcnow()
        now = datetime.utcnow()

        stats = metadata.get("stats") or {}
        wis = int(stats.get("wis", 10))
        wis_modifier = 1.0 - (wis - 10) * 0.1
        wis_modifier = max(0.1, min(2.0, wis_modifier))

        changed = False
        for skill_name, skill_level in applied.items():
            try:
                level = float(skill_level)
            except (TypeError, ValueError):
                level = 0.0

            last_used_dt = self._parse_datetime(last_used.get(skill_name)) or created_at
            last_decay_dt = self._parse_datetime(last_decay.get(skill_name))
            decay_start = last_used_dt
            if last_decay_dt and last_decay_dt > decay_start:
                decay_start = last_decay_dt

            if decay_start >= now:
                continue

            real_seconds = (now - decay_start).total_seconds()
            game_seconds = real_seconds * GAME_TIME_MULTIPLIER
            game_days = game_seconds / (24 * 60 * 60)
            decay_amount = 0.001 * game_days * wis_modifier

            new_level = max(0.0, level - decay_amount)
            new_level = round(new_level, 3)
            if new_level != level:
                applied[skill_name] = new_level
                last_decay[skill_name] = now.isoformat()
                changed = True

        if changed:
            skills["applied"] = applied
            skills["last_decay_at"] = last_decay
            metadata["skills"] = skills
            self._apply_metadata(monster, metadata, updates)

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
        upkeep_cost = int(DEFAULT_MONSTER_TYPES.get(monster_type, {}).get("cost", 50))
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
        if good_type:
            key = str(good_type).lower().replace("_", " ").strip()
            entry = self._good_types.get(key)
            if entry and "storage_volume" in entry:
                try:
                    return int(entry["storage_volume"])
                except (TypeError, ValueError):
                    return 1
        return 1

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

    def _parse_datetime(self, value: str) -> datetime | None:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
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
            if self._slot_occupied(entities, target_workshop, new_x, new_y):
                return False
            self._mark_last_transporter(pushed, mover, updates)
            if not self._deposit_into_workshop(
                item=pushed,
                workshop=target_workshop,
                slot_x=new_x,
                slot_y=new_y,
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
            self._deliver_item(
                item=pushed,
                delivery=target_delivery,
                transporter=mover,
                entities=entities,
                creates=creates or [],
                deletes=deletes,
                updates=updates,
                events=events,
            )
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

    def _slot_occupied(self, entities: list[Entity], workshop: Entity, x: int, y: int) -> bool:
        for entity in entities:
            if self._entity_kind(entity) != KIND_ITEM:
                continue
            metadata = entity.metadata_ or {}
            if not metadata.get("is_stored"):
                continue
            if metadata.get("container_id") != str(workshop.id):
                continue
            slot = metadata.get("stored_slot") or {}
            if slot.get("x") == x and slot.get("y") == y:
                return True
        return False

    def _deposit_into_workshop(
        self,
        item: Entity,
        workshop: Entity,
        slot_x: int,
        slot_y: int,
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
    ) -> bool:
        item_metadata = dict(item.metadata_ or {})
        workshop_metadata = dict(workshop.metadata_ or {})

        is_tool = self._is_tool_item(item_metadata)
        is_tool_slot = self._is_workshop_tool_slot(workshop, slot_x, slot_y)
        role = "tool" if is_tool and is_tool_slot else "input"

        if role == "tool":
            durability = item_metadata.get("durability", 10)
            max_durability = item_metadata.get("max_durability", durability)
            item_metadata["durability"] = durability
            item_metadata["max_durability"] = max_durability
            item_metadata["tool_tags"] = self._get_tool_tags(item_metadata)

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
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
    ) -> bool:
        item_metadata = dict(item.metadata_ or {})
        dispenser_metadata = dict(dispenser.metadata_ or {})

        item_type = item_metadata.get("good_type")
        stored_type = dispenser_metadata.get("stored_good_type")
        if stored_type and item_type and stored_type != item_type:
            return False

        if not stored_type and item_type:
            dispenser_metadata["stored_good_type"] = item_type

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
    ) -> None:
        item_metadata = item.metadata_ or {}
        delivery_metadata = dict(delivery.metadata_ or {})
        quality = int(item_metadata.get("quality", 1))
        base_renown = quality * 10

        transporter_stats = (transporter.metadata_ or {}).get("stats") or {}
        cha = int(transporter_stats.get("cha", 10))
        cha_bonus = max(0, cha - 10) * 0.05
        base_renown = int(base_renown * (1 + cha_bonus))

        contributors: dict[str, dict[str, Any]] = {}

        producer_id = item_metadata.get("producer_player_id")
        if producer_id:
            contributors.setdefault(str(producer_id), {"types": [], "shares": 0})
            contributors[str(producer_id)]["types"].append("producer")
            contributors[str(producer_id)]["shares"] += 1

        tool_creators = item_metadata.get("tool_creator_player_ids") or []
        for creator_id in tool_creators:
            if not creator_id:
                continue
            contributors.setdefault(str(creator_id), {"types": [], "shares": 0})
            if "tool_creator" not in contributors[str(creator_id)]["types"]:
                contributors[str(creator_id)]["types"].append("tool_creator")
            contributors[str(creator_id)]["shares"] += 1

        transporter_id = transporter.owner_id
        if transporter_id:
            contributors.setdefault(str(transporter_id), {"types": [], "shares": 0})
            contributors[str(transporter_id)]["types"].append("transporter")
            contributors[str(transporter_id)]["shares"] += 1

        total_shares = sum(info["shares"] for info in contributors.values()) or 1
        renown_per_share = base_renown / total_shares
        share_distribution = []

        for player_id, info in contributors.items():
            renown_gain = int(renown_per_share * info["shares"])
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
                "shares": info["shares"],
                "renown": renown_gain,
                "types": info["types"],
            })

        delivered = list(delivery_metadata.get("delivered_items") or [])
        delivered.append({
            "good_type": item_metadata.get("good_type"),
            "quality": quality,
            "timestamp": datetime.utcnow().isoformat(),
            "renown": base_renown,
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
            "renown": base_renown,
            "contributors": share_distribution,
        })

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

    def _entity_size(self, entity: Entity) -> tuple[int, int]:
        width = entity.width if entity.width and entity.width > 0 else 1
        height = entity.height if entity.height and entity.height > 0 else 1
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
        if kind == KIND_WORKSHOP and "blocks_movement" not in metadata:
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

    def _fake_entity(self, x: int, y: int) -> Entity:
        fake = Entity(zone_id=UUID(int=0), x=x, y=y, width=1, height=1)
        fake.metadata_ = {}
        return fake


game_module = MonsterWorkshopGame()
