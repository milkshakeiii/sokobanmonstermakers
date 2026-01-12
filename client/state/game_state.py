"""Game state management and entity tracking."""

from typing import Any, Dict, List, Optional, Set, Tuple

from config import DIRECTION_DELTAS


class GameState:
    """Manages the local game state synchronized from the server."""

    def __init__(self):
        # Entity storage: id -> entity data
        self.entities: Dict[str, Dict[str, Any]] = {}

        # Player info
        self.player_id: Optional[str] = None
        self.local_monster_id: Optional[str] = None

        # Player monster facing direction (for context panel)
        self.facing_direction: str = "down"

        # Spatial index for quick lookups
        self._position_index: Dict[Tuple[int, int], Set[str]] = {}

        # Tutorial tracking
        self.shown_hints: Set[str] = set()
        self.player_has_pushed: bool = False
        self.player_has_recorded: bool = False

    def set_player_id(self, player_id: str):
        """Set the player's ID."""
        self.player_id = player_id

    def update_facing(self, direction: str):
        """Update the direction the player monster is facing."""
        if direction in DIRECTION_DELTAS:
            self.facing_direction = direction

    def sync_entities(self, server_entities: List[Dict[str, Any]]) -> Tuple[Set[str], Set[str], Set[str]]:
        """Synchronize local entities with server state.

        Args:
            server_entities: List of entity data from server.

        Returns:
            Tuple of (added_ids, updated_ids, removed_ids)
        """
        server_ids = set()
        added_ids = set()
        updated_ids = set()

        for entity_data in server_entities:
            eid = entity_data["id"]
            server_ids.add(eid)

            # Check if this is our monster
            if self._is_player_monster(entity_data):
                self.local_monster_id = eid

            if eid in self.entities:
                # Check for changes
                old_data = self.entities[eid]
                if self._entity_changed(old_data, entity_data):
                    updated_ids.add(eid)
                    # Update spatial index if position changed
                    if old_data["x"] != entity_data["x"] or old_data["y"] != entity_data["y"]:
                        self._remove_from_position_index(eid, old_data["x"], old_data["y"])
                        self._add_to_position_index(eid, entity_data["x"], entity_data["y"])
            else:
                # New entity
                added_ids.add(eid)
                self._add_to_position_index(eid, entity_data["x"], entity_data["y"])

            self.entities[eid] = entity_data

        # Find removed entities
        current_ids = set(self.entities.keys())
        removed_ids = current_ids - server_ids

        for eid in removed_ids:
            old_data = self.entities[eid]
            self._remove_from_position_index(eid, old_data["x"], old_data["y"])
            del self.entities[eid]

        # Clear local monster if it was removed
        if self.local_monster_id in removed_ids:
            self.local_monster_id = None

        return added_ids, updated_ids, removed_ids

    def _is_player_monster(self, entity_data: Dict) -> bool:
        """Check if an entity is the player's actively controlled monster."""
        if entity_data.get("owner_id") != self.player_id:
            return False
        metadata = entity_data.get("metadata", {})
        if metadata.get("monster_type") is None:
            return False
        # Only match controlled monsters (not phased-out ones)
        return metadata.get("controlled", True)

    def is_phased_out(self, entity_data: Dict) -> bool:
        """Check if a monster is phased out (uncontrolled and not autorepeating).

        Only applies to player's own monsters.
        """
        if entity_data.get("owner_id") != self.player_id:
            return False
        metadata = entity_data.get("metadata", {})
        if metadata.get("kind") != "monster":
            return False
        if metadata.get("controlled", True):
            return False
        current_task = metadata.get("current_task", {})
        return not current_task.get("is_playing", False)

    def _entity_changed(self, old: Dict, new: Dict) -> bool:
        """Check if entity data has meaningfully changed."""
        # Position change
        if old["x"] != new["x"] or old["y"] != new["y"]:
            return True
        # Metadata change (for crafting state, etc.)
        if old.get("metadata") != new.get("metadata"):
            return True
        return False

    def _add_to_position_index(self, eid: str, x: int, y: int):
        """Add entity to spatial index."""
        # Add to all cells the entity occupies
        entity = self.entities.get(eid) or {"width": 1, "height": 1}
        width = entity.get("width", 1)
        height = entity.get("height", 1)

        for dx in range(width):
            for dy in range(height):
                pos = (x + dx, y + dy)
                if pos not in self._position_index:
                    self._position_index[pos] = set()
                self._position_index[pos].add(eid)

    def _remove_from_position_index(self, eid: str, x: int, y: int):
        """Remove entity from spatial index."""
        entity = self.entities.get(eid) or {"width": 1, "height": 1}
        width = entity.get("width", 1)
        height = entity.get("height", 1)

        for dx in range(width):
            for dy in range(height):
                pos = (x + dx, y + dy)
                if pos in self._position_index:
                    self._position_index[pos].discard(eid)
                    if not self._position_index[pos]:
                        del self._position_index[pos]

    def get_entity(self, eid: str) -> Optional[Dict]:
        """Get entity data by ID."""
        return self.entities.get(eid)

    def get_player_monster(self) -> Optional[Dict]:
        """Get the player's monster entity."""
        if self.local_monster_id:
            return self.entities.get(self.local_monster_id)
        return None

    def get_entities_at(self, x: int, y: int) -> List[Dict]:
        """Get all entities occupying a position."""
        pos = (x, y)
        if pos not in self._position_index:
            return []
        return [self.entities[eid] for eid in self._position_index[pos] if eid in self.entities]

    def get_adjacent_entities(self, x: int, y: int, include_diagonals: bool = False) -> List[Dict]:
        """Get all entities adjacent to a position.

        Args:
            x, y: Center position
            include_diagonals: Whether to include diagonal neighbors

        Returns:
            List of adjacent entity data dicts
        """
        adjacent = []
        directions = [(-1, 0), (1, 0), (0, -1), (0, 1)]
        if include_diagonals:
            directions.extend([(-1, -1), (1, -1), (-1, 1), (1, 1)])

        seen_ids = set()
        for dx, dy in directions:
            for entity in self.get_entities_at(x + dx, y + dy):
                if entity["id"] not in seen_ids:
                    adjacent.append(entity)
                    seen_ids.add(entity["id"])

        return adjacent

    def get_nearby_entity(self) -> Optional[Dict]:
        """Get a nearby entity for the context panel.

        First checks the facing direction, then checks all adjacent cells
        if nothing is in the facing direction.

        Returns:
            Entity data dict, or None if nothing nearby.
        """
        monster = self.get_player_monster()
        if not monster:
            return None

        # Priority order for entity kinds
        priority = ["workshop", "gathering_spot", "wagon", "item", "dispenser", "delivery", "signpost", "monster"]

        def pick_best(entities: list) -> Optional[Dict]:
            """Pick the highest priority entity from a list."""
            # Filter out the player's own monster
            entities = [e for e in entities if e["id"] != self.local_monster_id]
            if not entities:
                return None
            for kind in priority:
                for entity in entities:
                    if entity.get("metadata", {}).get("kind") == kind:
                        return entity
            return entities[0]

        # First, check the facing direction
        dx, dy = DIRECTION_DELTAS.get(self.facing_direction, (0, 0))
        target_x = monster["x"] + dx
        target_y = monster["y"] + dy
        facing_entities = self.get_entities_at(target_x, target_y)
        result = pick_best(facing_entities)
        if result:
            return result

        # If nothing in facing direction, check all adjacent cells
        adjacent = self.get_adjacent_entities(monster["x"], monster["y"])
        return pick_best(adjacent)

    def get_facing_entity(self) -> Optional[Dict]:
        """Alias for get_nearby_entity for backwards compatibility."""
        return self.get_nearby_entity()

    def get_entities_by_kind(self, kind: str) -> List[Dict]:
        """Get all entities of a specific kind."""
        return [
            e for e in self.entities.values()
            if e.get("metadata", {}).get("kind") == kind
        ]

    def get_workshops(self) -> List[Dict]:
        """Get all workshop entities."""
        return self.get_entities_by_kind("workshop")

    def get_gathering_spots(self) -> List[Dict]:
        """Get all gathering spot entities."""
        return self.get_entities_by_kind("gathering_spot")

    def get_adjacent_workshop(self) -> Optional[Dict]:
        """Get a workshop adjacent to the player monster."""
        monster = self.get_player_monster()
        if not monster:
            return None

        for entity in self.get_adjacent_entities(monster["x"], monster["y"]):
            if entity.get("metadata", {}).get("kind") in ("workshop", "gathering_spot"):
                return entity

        return None

    def get_adjacent_wagon(self) -> Optional[Dict]:
        """Get a wagon adjacent to the player monster."""
        monster = self.get_player_monster()
        if not monster:
            return None

        for entity in self.get_adjacent_entities(monster["x"], monster["y"]):
            if entity.get("metadata", {}).get("kind") == "wagon":
                return entity

        return None

    def is_monster_hitched(self) -> bool:
        """Check if the player's monster is hitched to a wagon."""
        monster = self.get_player_monster()
        if not monster:
            return False

        current_task = monster.get("metadata", {}).get("current_task", {})
        return current_task.get("hitched_wagon_id") is not None

    def is_monster_recording(self) -> bool:
        """Check if the player's monster is recording."""
        monster = self.get_player_monster()
        if not monster:
            return False

        current_task = monster.get("metadata", {}).get("current_task", {})
        return current_task.get("is_recording", False)

    def is_monster_playing(self) -> bool:
        """Check if the player's monster is playing back a recording."""
        monster = self.get_player_monster()
        if not monster:
            return False

        current_task = monster.get("metadata", {}).get("current_task", {})
        return current_task.get("is_playing", False)
