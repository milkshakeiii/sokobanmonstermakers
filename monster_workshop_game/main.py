"""Monster Workshop game module for gridtickmultiplayer."""

from __future__ import annotations

import json
import logging
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

DEFAULT_MONSTER_TYPES = {
    "goblin": {
        "name": "Goblin",
        "stats": {"str": 6, "dex": 14, "con": 8, "int": 8, "wis": 7, "cha": 10},
        "body_cap": 80,
        "mind_cap": 80,
    },
    "elf": {
        "name": "Elf",
        "stats": {"str": 8, "dex": 12, "con": 8, "int": 14, "wis": 10, "cha": 10},
        "body_cap": 90,
        "mind_cap": 110,
    },
}


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
                    updates=updates,
                    events=events,
                    zone_width=zone_width,
                    zone_height=zone_height,
                )

            elif action == "spawn_monster":
                create, event = self._handle_spawn_monster(
                    intent=intent,
                    entities=entities,
                    zone_def=zone_def,
                    zone_width=zone_width,
                    zone_height=zone_height,
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
                self._handle_select_recipe(intent, entity_map, updates, events)

            elif action == "interact":
                self._handle_interact(intent, entities, entity_map, events)

            else:
                if action:
                    events.append({
                        "type": "warning",
                        "message": f"Unsupported action: {action}",
                        "target_player_id": str(intent.player_id),
                    })

        self._process_autorepeat(
            entities=entities,
            updates=updates,
            events=events,
            zone_width=zone_width,
            zone_height=zone_height,
        )

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
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
        zone_width: int,
        zone_height: int,
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

        blocker = self._find_blocker(entities, entity, new_x, new_y)
        if blocker is None:
            self._apply_move(entity, new_x, new_y, updates)
            self._record_action(entity, "move", dx, dy, updates)
            return

        if self._entity_kind(blocker) not in PUSHABLE_KINDS:
            return

        if blocker.metadata_ and blocker.metadata_.get("is_stored"):
            return

        if not self._attempt_push(
            entities=entities,
            mover=entity,
            pushed=blocker,
            dx=dx,
            dy=dy,
            updates=updates,
            zone_width=zone_width,
            zone_height=zone_height,
        ):
            return

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

        spawn_x, spawn_y = self._choose_spawn_point(entities, zone_def, zone_width, zone_height)
        metadata = self._build_monster_metadata(name, monster_type, definition)

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
    ) -> None:
        workshop_id = self._parse_entity_id(intent.data.get("workshop_id"))
        if workshop_id is None:
            return

        recipe_id = intent.data.get("recipe_id")
        workshop = entity_map.get(workshop_id)
        if workshop is None or self._entity_kind(workshop) != KIND_WORKSHOP:
            return

        metadata = dict(workshop.metadata_ or {})
        metadata["selected_recipe_id"] = recipe_id
        self._apply_metadata(workshop, metadata, updates)
        events.append({
            "type": "recipe_selected",
            "workshop_id": str(workshop.id),
            "target_player_id": str(intent.player_id),
        })

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

    def _process_autorepeat(
        self,
        entities: list[Entity],
        updates: list[EntityUpdate],
        events: list[dict[str, Any]],
        zone_width: int,
        zone_height: int,
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
            dx, dy = self._intent_to_delta(action)
            if dx != 0 or dy != 0:
                new_x = monster.x + dx
                new_y = monster.y + dy
                if self._is_in_bounds(new_x, new_y, monster, zone_width, zone_height):
                    blocker = self._find_blocker(entities, monster, new_x, new_y)
                    if blocker is None:
                        self._apply_move(monster, new_x, new_y, updates)
                    elif self._entity_kind(blocker) in PUSHABLE_KINDS:
                        self._attempt_push(
                            entities=entities,
                            mover=monster,
                            pushed=blocker,
                            dx=dx,
                            dy=dy,
                            updates=updates,
                            zone_width=zone_width,
                            zone_height=zone_height,
                        )

            current_task["play_index"] = (index + 1) % max(len(actions), 1)
            metadata = dict(monster.metadata_ or {})
            metadata["current_task"] = current_task
            self._apply_metadata(monster, metadata, updates)
            events.append({
                "type": "autorepeat_step",
                "target_player_id": str(monster.owner_id) if monster.owner_id else None,
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

    def _attempt_push(
        self,
        entities: list[Entity],
        mover: Entity,
        pushed: Entity,
        dx: int,
        dy: int,
        updates: list[EntityUpdate],
        zone_width: int,
        zone_height: int,
    ) -> bool:
        new_x = pushed.x + dx
        new_y = pushed.y + dy

        if not self._is_in_bounds(new_x, new_y, pushed, zone_width, zone_height):
            return False

        blocker = self._find_blocker(entities, pushed, new_x, new_y, ignore_ids={mover.id, pushed.id})
        if blocker is not None:
            return False

        self._apply_move(pushed, new_x, new_y, updates)
        self._apply_move(mover, mover.x + dx, mover.y + dy, updates)
        return True

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
            "skills": {"transferable": [], "applied": {}},
            "current_task": {
                "is_recording": False,
                "is_playing": False,
                "actions": [],
                "play_index": 0,
            },
            "online": True,
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
                good_types[name] = entry
        return good_types

    def _fake_entity(self, x: int, y: int) -> Entity:
        fake = Entity(zone_id=UUID(int=0), x=x, y=y, width=1, height=1)
        fake.metadata_ = {}
        return fake


game_module = MonsterWorkshopGame()
