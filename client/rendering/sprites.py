"""Sprite factory for creating and managing game sprites."""

import sys
import os
from typing import Any, Dict, Optional, Tuple, Union

# Add pyunicodegame to path
sys.path.insert(0, os.path.expanduser("~/Documents/github/pyunicodegame/src"))

import pyunicodegame

from config import SPRITE_LERP_SPEED
from rendering.sprite_catalog import get_sprite_def, get_item_pixel_sprite_name
from rendering.pixel_sprite_loader import get_loader as get_pixel_loader


class SpriteFactory:
    """Factory for creating sprites from entity data."""

    def __init__(self, game_window, player_id: Optional[str] = None):
        """Initialize the sprite factory.

        Args:
            game_window: The pyunicodegame window to add sprites to
            player_id: The current player's ID
        """
        self.game_window = game_window
        self.player_id = player_id

        # Sprite storage: entity_id -> sprite (can be Sprite or PixelSprite)
        self.sprites: Dict[str, Union[pyunicodegame.Sprite, pyunicodegame.PixelSprite]] = {}

        # Track entity metadata for update detection
        self._entity_cache: Dict[str, Dict] = {}

        # Initialize pixel sprite loader
        self._pixel_loader = get_pixel_loader()

    def set_player_id(self, player_id: str):
        """Set the player ID for ownership detection."""
        self.player_id = player_id

    def create_sprite(
        self,
        entity: Dict[str, Any],
    ) -> Union[pyunicodegame.Sprite, pyunicodegame.PixelSprite]:
        """Create a sprite for an entity.

        Args:
            entity: Entity data dict from server

        Returns:
            The created sprite (unicode or pixel)
        """
        eid = entity["id"]
        metadata = entity.get("metadata", {})
        kind = metadata.get("kind")

        # Check if this is an item with a pixel sprite
        if kind == "item":
            sprite = self._try_create_pixel_sprite(entity)
            if sprite is not None:
                self.sprites[eid] = sprite
                self._entity_cache[eid] = self._cache_key(entity)
                self.game_window.add_sprite(sprite)
                return sprite

        # Fall back to Unicode sprite
        pattern, color = get_sprite_def(entity, self.player_id)

        sprite = pyunicodegame.create_sprite(
            pattern,
            x=entity["x"],
            y=entity["y"],
            fg=color,
            lerp_speed=SPRITE_LERP_SPEED,
        )

        self.sprites[eid] = sprite
        self._entity_cache[eid] = self._cache_key(entity)
        self.game_window.add_sprite(sprite)

        return sprite

    def _try_create_pixel_sprite(
        self,
        entity: Dict[str, Any],
    ) -> Optional[pyunicodegame.PixelSprite]:
        """Try to create a pixel sprite for an item entity.

        Args:
            entity: Entity data dict

        Returns:
            PixelSprite if available, None otherwise
        """
        metadata = entity.get("metadata", {})
        good_type = metadata.get("good_type", "")

        # Check if pixel sprite exists for this good_type
        sprite_name = get_item_pixel_sprite_name(metadata)
        if sprite_name is None:
            return None

        # Get effective_color from metadata (for color inheritance)
        effective_color = metadata.get("effective_color")
        if effective_color is not None and isinstance(effective_color, (list, tuple)):
            effective_color = tuple(effective_color[:3])
        else:
            effective_color = None

        # Get the sprite surface
        surface = self._pixel_loader.get_sprite_surface(sprite_name, effective_color)
        if surface is None:
            return None

        # Get cell dimensions
        cell_width, cell_height = self.game_window.cell_size

        # Validate surface dimensions (must be multiples of cell size)
        surf_width, surf_height = surface.get_size()
        if surf_width % cell_width != 0 or surf_height % cell_height != 0:
            # Surface doesn't align with cell grid, fall back to Unicode
            return None

        # Create PixelFrame and PixelSprite
        frame = pyunicodegame.PixelFrame(surface, cell_width, cell_height)
        sprite = pyunicodegame.PixelSprite([frame])
        sprite.x = entity["x"]
        sprite.y = entity["y"]
        sprite._teleport_pending = True
        sprite.lerp_speed = SPRITE_LERP_SPEED

        return sprite

    def update_sprite(self, entity: Dict[str, Any]) -> Optional[pyunicodegame.Sprite]:
        """Update a sprite's position and appearance.

        Args:
            entity: Updated entity data

        Returns:
            The updated sprite, or None if not found
        """
        eid = entity["id"]
        sprite = self.sprites.get(eid)

        if sprite is None:
            return None

        # Update position (lerped automatically)
        if sprite.x != entity["x"] or sprite.y != entity["y"]:
            sprite.move_to(entity["x"], entity["y"])

        # Check if appearance needs updating
        old_cache = self._entity_cache.get(eid)
        new_cache = self._cache_key(entity)

        if old_cache != new_cache:
            # Recreate sprite with new appearance
            self.remove_sprite(eid)
            return self.create_sprite(entity)

        return sprite

    def remove_sprite(self, entity_id: str):
        """Remove a sprite.

        Args:
            entity_id: ID of the entity whose sprite to remove
        """
        sprite = self.sprites.pop(entity_id, None)
        if sprite:
            self.game_window.remove_sprite(sprite)
        self._entity_cache.pop(entity_id, None)

    def get_sprite(self, entity_id: str) -> Optional[pyunicodegame.Sprite]:
        """Get a sprite by entity ID."""
        return self.sprites.get(entity_id)

    def clear_all(self):
        """Remove all sprites."""
        for eid in list(self.sprites.keys()):
            self.remove_sprite(eid)

    def _is_phased_out(self, entity: Dict) -> bool:
        """Check if entity is a phased-out monster (uncontrolled and not autorepeating).

        Phased-out monsters owned by the player should not be rendered.
        """
        metadata = entity.get("metadata", {})
        if metadata.get("kind") != "monster":
            return False
        # Only check for our own monsters
        if entity.get("owner_id") != self.player_id:
            return False
        if metadata.get("controlled", True):
            return False
        current_task = metadata.get("current_task", {})
        return not current_task.get("is_playing", False)

    def sync_entities(
        self,
        added_ids: set,
        updated_ids: set,
        removed_ids: set,
        entities: Dict[str, Dict],
    ):
        """Sync sprites with entity changes.

        Args:
            added_ids: Set of newly added entity IDs
            updated_ids: Set of updated entity IDs
            removed_ids: Set of removed entity IDs
            entities: Current entity data dict (id -> entity)
        """
        # Remove old sprites
        for eid in removed_ids:
            self.remove_sprite(eid)

        # Update existing sprites (or remove if now phased out)
        for eid in updated_ids:
            if eid in entities:
                entity = entities[eid]
                if self._is_phased_out(entity):
                    self.remove_sprite(eid)
                else:
                    self.update_sprite(entity)

        # Create new sprites (skip phased-out monsters)
        for eid in added_ids:
            if eid in entities:
                entity = entities[eid]
                if not self._is_phased_out(entity):
                    self.create_sprite(entity)

    def _cache_key(self, entity: Dict) -> Dict:
        """Create a cache key for entity appearance.

        Used to detect when a sprite needs to be recreated.
        """
        metadata = entity.get("metadata", {})

        # Extract effective_color as tuple for hashability
        effective_color = metadata.get("effective_color")
        if effective_color is not None and isinstance(effective_color, (list, tuple)):
            effective_color = tuple(effective_color[:3])
        else:
            effective_color = None

        return {
            "owner_id": entity.get("owner_id"),
            "kind": metadata.get("kind"),
            "monster_type": metadata.get("monster_type"),
            "good_type": metadata.get("good_type"),
            "is_crafting": metadata.get("is_crafting"),
            "loaded_item_ids": len(metadata.get("loaded_item_ids", [])) > 0,
            "effective_color": effective_color,
        }


class LightManager:
    """Manager for dynamic lights in the game."""

    def __init__(self, game_window, enabled: bool = True):
        """Initialize the light manager.

        Args:
            game_window: The pyunicodegame window
            enabled: Whether lighting system is enabled
        """
        self.game_window = game_window
        self.enabled = enabled

        # Light storage
        self.lights: Dict[str, Any] = {}  # entity_id -> light
        self.player_light: Optional[Any] = None

    def create_player_torch(self, sprite) -> Any:
        """Create the player's torch light.

        Args:
            sprite: The player monster sprite to follow

        Returns:
            The created light, or None if lighting is disabled
        """
        if not self.enabled:
            return None

        from config import LIGHT_CONFIGS

        config = LIGHT_CONFIGS["player_torch"]

        self.player_light = pyunicodegame.create_light(
            x=sprite.x,
            y=sprite.y,
            radius=config.radius,
            color=config.color,
            intensity=config.intensity,
            falloff=config.falloff,
            casts_shadows=config.casts_shadows,
            follow_sprite=sprite,
        )

        self.game_window.add_light(self.player_light)
        return self.player_light

    def create_entity_light(self, entity_id: str, entity: Dict, sprite=None) -> Optional[Any]:
        """Create a light for an entity if appropriate.

        Args:
            entity_id: Entity ID
            entity: Entity data
            sprite: Optional sprite to follow

        Returns:
            The created light, or None if lighting is disabled
        """
        if not self.enabled:
            return None

        from config import LIGHT_CONFIGS

        metadata = entity.get("metadata", {})
        kind = metadata.get("kind")

        # Determine light type
        config_key = None

        if kind == "workshop" and metadata.get("is_crafting"):
            config_key = "workshop_active"
        elif kind == "gathering_spot":
            config_key = "gathering_spot"
        elif kind == "signpost":
            config_key = "signpost"
        elif kind == "commune":
            config_key = "commune"

        if config_key is None:
            return None

        config = LIGHT_CONFIGS[config_key]

        # Calculate center position for multi-cell entities
        width = entity.get("width", 1)
        height = entity.get("height", 1)
        center_x = entity["x"] + width / 2
        center_y = entity["y"] + height / 2

        light = pyunicodegame.create_light(
            x=center_x,
            y=center_y,
            radius=config.radius,
            color=config.color,
            intensity=config.intensity,
            falloff=config.falloff,
            casts_shadows=config.casts_shadows,
        )

        self.lights[entity_id] = light
        self.game_window.add_light(light)
        return light

    def remove_entity_light(self, entity_id: str):
        """Remove a light for an entity."""
        light = self.lights.pop(entity_id, None)
        if light:
            self.game_window.remove_light(light)

    def update_entity_light(self, entity_id: str, entity: Dict):
        """Update light for an entity (e.g., workshop started/stopped crafting)."""
        metadata = entity.get("metadata", {})
        kind = metadata.get("kind")

        has_light = entity_id in self.lights

        # Check if entity should have a light
        should_have_light = False
        if kind == "workshop" and metadata.get("is_crafting"):
            should_have_light = True
        elif kind in ("gathering_spot", "signpost", "commune"):
            should_have_light = True

        # Add or remove light as needed
        if should_have_light and not has_light:
            self.create_entity_light(entity_id, entity)
        elif not should_have_light and has_light:
            self.remove_entity_light(entity_id)

    def clear_all(self):
        """Remove all lights."""
        for eid in list(self.lights.keys()):
            self.remove_entity_light(eid)

        if self.player_light:
            self.game_window.remove_light(self.player_light)
            self.player_light = None
