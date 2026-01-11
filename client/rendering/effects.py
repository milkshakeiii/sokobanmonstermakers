"""Visual effects and particle systems."""

import sys
import os
from typing import Any, Dict, List, Optional

# Add pyunicodegame to path
sys.path.insert(0, os.path.expanduser("~/Documents/github/pyunicodegame/src"))

import pyunicodegame

from config import Color


class EffectsManager:
    """Manages particle effects and visual feedback."""

    def __init__(self, game_window):
        """Initialize the effects manager.

        Args:
            game_window: pyunicodegame window for effects
        """
        self.game_window = game_window

        # Active emitters by entity ID
        self.crafting_emitters: Dict[str, Any] = {}

        # One-shot effects
        self.active_effects: List[Any] = []

    def create_crafting_effect(self, entity_id: str, entity: Dict) -> Optional[Any]:
        """Create a crafting particle effect for a workshop.

        Args:
            entity_id: Workshop entity ID
            entity: Workshop entity data

        Returns:
            The created emitter, or None
        """
        metadata = entity.get("metadata", {})

        if not metadata.get("is_crafting"):
            return None

        # Already has emitter
        if entity_id in self.crafting_emitters:
            return self.crafting_emitters[entity_id]

        # Calculate center position
        width = entity.get("width", 4)
        height = entity.get("height", 4)
        center_x = entity["x"] + width / 2
        center_y = entity["y"] + height / 2

        # Determine effect type based on workshop
        workshop_type = metadata.get("workshop_type", "").lower()
        primary_skill = metadata.get("primary_applied_skill", "").lower()

        if any(s in (workshop_type, primary_skill) for s in ("smithing", "casting", "blacksmithing")):
            # Orange sparks for metalworking
            emitter = pyunicodegame.create_emitter(
                x=center_x,
                y=center_y - 1,
                chars="*+.",
                colors=[(255, 200, 50), (255, 150, 0), (255, 100, 0)],
                spawn_rate=8,
                speed=3,
                direction=90,  # Upward
                arc=60,
                drag=0.5,
                fade_time=0.8,
                z_index=50,
            )
        elif "dyeing" in (workshop_type, primary_skill):
            # Blue bubbles for dyeing
            emitter = pyunicodegame.create_emitter(
                x=center_x,
                y=center_y,
                chars="~o.",
                colors=[(100, 100, 200), (150, 150, 255), (80, 80, 180)],
                spawn_rate=4,
                speed=1,
                direction=90,
                arc=30,
                drag=0.3,
                fade_time=1.2,
                z_index=50,
            )
        elif any(s in (workshop_type, primary_skill) for s in ("spinning", "weaving", "sericulture")):
            # Light fiber particles for textiles
            emitter = pyunicodegame.create_emitter(
                x=center_x,
                y=center_y,
                chars="~.",
                colors=[(240, 240, 255), (220, 220, 240)],
                spawn_rate=3,
                speed=0.5,
                direction=90,
                arc=120,
                drag=0.2,
                fade_time=1.5,
                z_index=50,
            )
        elif "pottery" in (workshop_type, primary_skill):
            # Brown dust for pottery
            emitter = pyunicodegame.create_emitter(
                x=center_x,
                y=center_y,
                chars=".",
                colors=[(180, 120, 80), (160, 100, 60)],
                spawn_rate=2,
                speed=0.3,
                direction=0,
                arc=360,
                drag=0.4,
                fade_time=1.0,
                z_index=50,
            )
        else:
            # Default subtle sparkle
            emitter = pyunicodegame.create_emitter(
                x=center_x,
                y=center_y,
                chars=".",
                colors=[(200, 200, 200), (180, 180, 180)],
                spawn_rate=2,
                speed=0.5,
                direction=90,
                arc=180,
                drag=0.3,
                fade_time=1.0,
                z_index=50,
            )

        self.crafting_emitters[entity_id] = emitter
        self.game_window.add_emitter(emitter)
        return emitter

    def remove_crafting_effect(self, entity_id: str):
        """Remove a crafting effect.

        Args:
            entity_id: Workshop entity ID
        """
        emitter = self.crafting_emitters.pop(entity_id, None)
        if emitter:
            emitter.stop()
            # Emitter will be auto-removed when particles fade

    def update_crafting_effect(self, entity_id: str, entity: Dict):
        """Update crafting effect based on entity state.

        Args:
            entity_id: Workshop entity ID
            entity: Workshop entity data
        """
        metadata = entity.get("metadata", {})
        is_crafting = metadata.get("is_crafting", False)
        has_emitter = entity_id in self.crafting_emitters

        if is_crafting and not has_emitter:
            self.create_crafting_effect(entity_id, entity)
        elif not is_crafting and has_emitter:
            self.remove_crafting_effect(entity_id)

    def show_blocked_effect(self, x: int, y: int, direction: str):
        """Show a visual effect when movement is blocked.

        Args:
            x, y: Position of the entity that was blocked
            direction: Direction of attempted movement
        """
        # Calculate effect position (slightly in the direction of movement)
        dx, dy = {"up": (0, -0.5), "down": (0, 0.5), "left": (-0.5, 0), "right": (0.5, 0)}.get(
            direction, (0, 0)
        )

        effect = pyunicodegame.create_effect(
            "X",
            x=x + dx,
            y=y + dy,
            fg=(255, 100, 100),
            fade_time=0.3,
            duration=0.3,
            z_index=60,
        )

        self.game_window.add_sprite(effect)
        self.active_effects.append(effect)

    def show_push_effect(self, item_x: int, item_y: int, direction: str):
        """Show a dust trail effect when pushing an item.

        Args:
            item_x, item_y: Position of the pushed item
            direction: Direction of push
        """
        # Calculate opposite direction for particles
        opposite = {"up": 270, "down": 90, "left": 0, "right": 180}.get(direction, 0)

        emitter = pyunicodegame.create_emitter(
            x=item_x,
            y=item_y,
            chars=".",
            colors=[(150, 150, 100), (120, 120, 80)],
            spawn_rate=15,
            speed=2,
            direction=opposite,
            arc=30,
            drag=0.5,
            fade_time=0.3,
            emitter_duration=0.2,
            z_index=40,
        )

        self.game_window.add_emitter(emitter)

    def show_spawn_effect(self, x: int, y: int):
        """Show a sparkle effect when something spawns.

        Args:
            x, y: Spawn position
        """
        emitter = pyunicodegame.create_emitter(
            x=x,
            y=y,
            chars="*+.",
            colors=[(255, 215, 0), (255, 200, 50), (255, 180, 0)],
            spawn_rate=20,
            speed=2,
            direction=0,
            arc=360,
            drag=0.6,
            fade_time=0.5,
            emitter_duration=0.3,
            z_index=60,
        )

        self.game_window.add_emitter(emitter)

    def show_crafting_complete_effect(self, x: int, y: int):
        """Show effect when crafting completes.

        Args:
            x, y: Workshop position
        """
        emitter = pyunicodegame.create_emitter(
            x=x,
            y=y,
            chars="*",
            colors=[(100, 255, 100), (150, 255, 150)],
            spawn_rate=15,
            speed=1.5,
            direction=90,
            arc=120,
            drag=0.4,
            fade_time=0.8,
            emitter_duration=0.4,
            z_index=60,
        )

        self.game_window.add_emitter(emitter)

    def clear_all(self):
        """Remove all effects."""
        for entity_id in list(self.crafting_emitters.keys()):
            self.remove_crafting_effect(entity_id)


def render_progress_bar(window, x: int, y: int, progress: float, width: int = 8):
    """Render a progress bar.

    Args:
        window: pyunicodegame window
        x, y: Position
        progress: Progress value 0.0 to 1.0
        width: Bar width in characters
    """
    filled = int(progress * (width - 2))
    empty = (width - 2) - filled

    bar = "[" + "=" * filled + "-" * empty + "]"
    color = Color.SUCCESS if progress >= 1.0 else Color.WARNING

    window.put_string(x, y, bar, color)
