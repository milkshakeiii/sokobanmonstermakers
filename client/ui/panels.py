"""UI panels for monster info and context display."""

from typing import Any, Dict, List, Optional

from config import (
    Color,
    PANEL_WIDTH,
    MONSTER_PANEL_HEIGHT,
    CONTEXT_PANEL_HEIGHT,
    QUALITY_MASTERWORK,
    QUALITY_FINE,
    QUALITY_NORMAL,
)


class MonsterPanel:
    """Panel displaying the player's monster information."""

    def __init__(self, window):
        """Initialize the monster panel.

        Args:
            window: pyunicodegame window for this panel
        """
        self.window = window
        self.width = PANEL_WIDTH
        self.height = MONSTER_PANEL_HEIGHT

    def render(self, monster: Optional[Dict], is_recording: bool = False, is_playing: bool = False):
        """Render the monster info panel.

        Args:
            monster: Monster entity data, or None if no monster
            is_recording: Whether recording is active
            is_playing: Whether playback is active
        """
        self._clear()
        self._draw_border()

        if monster is None:
            self._draw_no_monster()
            return

        metadata = monster.get("metadata", {})
        monster_type = metadata.get("monster_type", "unknown").upper()
        name = metadata.get("name", "Unknown")
        stats = metadata.get("stats", {})
        skills = metadata.get("transferable_skills", [])
        current_task = metadata.get("current_task", {})

        y = 1

        # Name and type
        title = f"{monster_type}"
        self.window.put_string(1, y, title, Color.TEXT_HIGHLIGHT)
        y += 1

        name_display = f'"{name}"'
        if len(name_display) > self.width - 2:
            name_display = name_display[: self.width - 5] + '..."'
        self.window.put_string(1, y, name_display, Color.TEXT_PRIMARY)
        y += 2

        # Stats in two columns
        stat_names = ["str", "dex", "con", "int", "wis", "cha"]
        for i in range(0, len(stat_names), 2):
            left_stat = stat_names[i]
            right_stat = stat_names[i + 1] if i + 1 < len(stat_names) else None

            left_val = stats.get(left_stat, 0)
            left_text = f"{left_stat.upper()}: {left_val:2d}"
            self.window.put_string(1, y, left_text, Color.TEXT_SECONDARY)

            if right_stat:
                right_val = stats.get(right_stat, 0)
                right_text = f"{right_stat.upper()}: {right_val:2d}"
                self.window.put_string(12, y, right_text, Color.TEXT_SECONDARY)

            y += 1

        y += 1

        # Skills
        self.window.put_string(1, y, "Skills:", Color.TEXT_MUTED)
        y += 1
        for skill in skills[:3]:
            skill_display = skill[:self.width - 4]
            self.window.put_string(2, y, f"- {skill_display}", Color.TEXT_SECONDARY)
            y += 1

        # Recording/playback status
        y = self.height - 2
        if is_recording:
            # Flashing red indicator
            import time
            char = "O" if int(time.time() * 2) % 2 else "o"
            self.window.put_string(1, y, f"{char} RECORDING", Color.ERROR)
        elif is_playing:
            # Animated playback
            import time
            frames = [">  ", ">> ", ">>>"]
            idx = int(time.time() * 4) % 3
            self.window.put_string(1, y, f"{frames[idx]} PLAYING", Color.SUCCESS)
        else:
            # Show task status
            task_name = current_task.get("task_name", "Idle")
            self.window.put_string(1, y, f"Task: {task_name}", Color.TEXT_MUTED)

    def _clear(self):
        """Clear the panel."""
        for y in range(self.height):
            self.window.put_string(0, y, " " * self.width, Color.TEXT_PRIMARY)

    def _draw_border(self):
        """Draw panel border."""
        # Top
        self.window.put_string(0, 0, "+" + "-" * (self.width - 2) + "+", Color.PANEL_BORDER)
        # Bottom
        self.window.put_string(
            0, self.height - 1, "+" + "-" * (self.width - 2) + "+", Color.PANEL_BORDER
        )
        # Sides
        for y in range(1, self.height - 1):
            self.window.put(0, y, "|", Color.PANEL_BORDER)
            self.window.put(self.width - 1, y, "|", Color.PANEL_BORDER)

    def _draw_no_monster(self):
        """Draw message when no monster is active."""
        y = self.height // 2 - 1
        self.window.put_string(2, y, "No monster active", Color.TEXT_MUTED)
        self.window.put_string(2, y + 1, "Press [N] to spawn", Color.TEXT_SECONDARY)


class ContextPanel:
    """Panel displaying context-sensitive information about nearby entities."""

    def __init__(self, window):
        """Initialize the context panel.

        Args:
            window: pyunicodegame window for this panel
        """
        self.window = window
        self.width = PANEL_WIDTH
        self.height = CONTEXT_PANEL_HEIGHT

    def render(self, entity: Optional[Dict], facing_direction: str = "down"):
        """Render the context panel based on the facing entity.

        Args:
            entity: Entity data the player is facing, or None
            facing_direction: Direction player is facing
        """
        self._clear()
        self._draw_border()

        if entity is None:
            self._draw_empty(facing_direction)
            return

        metadata = entity.get("metadata", {})
        kind = metadata.get("kind", "unknown")

        if kind == "workshop":
            self._render_workshop(entity, metadata)
        elif kind == "gathering_spot":
            self._render_gathering_spot(entity, metadata)
        elif kind == "item":
            self._render_item(entity, metadata)
        elif kind == "wagon":
            self._render_wagon(entity, metadata)
        elif kind == "dispenser":
            self._render_dispenser(entity, metadata)
        elif kind == "container":
            self._render_container(entity, metadata)
        elif kind == "delivery":
            self._render_delivery(entity, metadata)
        elif kind == "signpost":
            self._render_signpost(entity, metadata)
        elif kind == "monster":
            self._render_monster(entity, metadata)
        else:
            self._render_unknown(entity, metadata)

    def _clear(self):
        """Clear the panel."""
        for y in range(self.height):
            self.window.put_string(0, y, " " * self.width, Color.TEXT_PRIMARY)

    def _draw_border(self):
        """Draw panel border."""
        self.window.put_string(0, 0, "+" + "-" * (self.width - 2) + "+", Color.PANEL_BORDER)
        self.window.put_string(
            0, self.height - 1, "+" + "-" * (self.width - 2) + "+", Color.PANEL_BORDER
        )
        for y in range(1, self.height - 1):
            self.window.put(0, y, "|", Color.PANEL_BORDER)
            self.window.put(self.width - 1, y, "|", Color.PANEL_BORDER)

    def _draw_empty(self, direction: str):
        """Draw message when nothing is nearby."""
        y = 3
        self.window.put_string(1, y, "Nothing nearby", Color.TEXT_SECONDARY)

    def _render_workshop(self, entity: Dict, metadata: Dict):
        """Render workshop information."""
        y = 1

        # Title
        workshop_type = metadata.get("workshop_type", "Workshop")
        self.window.put_string(1, y, f"WORKSHOP", Color.TEXT_HIGHLIGHT)
        y += 1
        self.window.put_string(1, y, workshop_type.title(), Color.TEXT_PRIMARY)
        y += 2

        # Check for blocked output first (high priority status)
        if metadata.get("is_blocked"):
            self.window.put_string(1, y, "! BLOCKED !", Color.ERROR)
            y += 1
            blocked_reason = metadata.get("blocked_reason", "Output spot occupied")
            self.window.put_string(1, y, blocked_reason[:self.width - 2], Color.TEXT_MUTED)
            y += 1
            pending = metadata.get("pending_outputs", [])
            if pending:
                self.window.put_string(1, y, f"Pending: {len(pending)} item(s)", Color.WARNING)
                y += 1
            y += 1

        # Recipe
        recipe = metadata.get("selected_recipe_id")
        if recipe:
            self.window.put_string(1, y, f"Recipe: {recipe}", Color.TEXT_SECONDARY)
            y += 1

            # Crafting progress
            if metadata.get("is_crafting"):
                started = metadata.get("crafting_started_tick", 0)
                duration = metadata.get("crafting_duration", 100)
                # We don't have current tick, so show "In Progress"
                self.window.put_string(1, y, "Status: Crafting...", Color.SUCCESS)
                y += 1
            else:
                # Check for missing inputs
                missing_inputs = metadata.get("missing_inputs", [])
                missing_tools = metadata.get("missing_tools", [])

                if missing_inputs or missing_tools:
                    self.window.put_string(1, y, "Status: Waiting", Color.WARNING)
                    y += 2

                    if missing_inputs:
                        self.window.put_string(1, y, "Needs:", Color.TEXT_MUTED)
                        y += 1
                        for inp in missing_inputs[:3]:
                            text = f"  - {inp}"[:self.width - 3]
                            self.window.put_string(1, y, text, Color.ERROR)
                            y += 1

                    if missing_tools:
                        self.window.put_string(1, y, "Tools:", Color.TEXT_MUTED)
                        y += 1
                        for tool in missing_tools[:3]:
                            text = f"  - {tool}"[:self.width - 3]
                            self.window.put_string(1, y, text, Color.ERROR)
                            y += 1
                else:
                    self.window.put_string(1, y, "Status: Ready", Color.SUCCESS)
                    y += 1
        else:
            self.window.put_string(1, y, "No recipe selected", Color.TEXT_MUTED)
            y += 1

        # Controls hint
        y = self.height - 3
        self.window.put_string(1, y, "[C] Select Recipe", Color.TEXT_HIGHLIGHT)

    def _render_gathering_spot(self, entity: Dict, metadata: Dict):
        """Render gathering spot information."""
        y = 1

        self.window.put_string(1, y, "GATHERING SPOT", Color.TEXT_HIGHLIGHT)
        y += 2

        good_type = metadata.get("gathering_good_type") or metadata.get("gathered_good_type", "Unknown")
        self.window.put_string(1, y, f"Produces:", Color.TEXT_MUTED)
        y += 1
        self.window.put_string(2, y, good_type, Color.TEXT_PRIMARY)
        y += 2

        if metadata.get("is_crafting"):
            self.window.put_string(1, y, "Status: Gathering...", Color.SUCCESS)
        else:
            self.window.put_string(1, y, "Status: Idle", Color.TEXT_SECONDARY)

        y = self.height - 3
        self.window.put_string(1, y, "[C] Start Gathering", Color.TEXT_HIGHLIGHT)

    def _render_item(self, entity: Dict, metadata: Dict):
        """Render item information."""
        y = 1

        self.window.put_string(1, y, "ITEM", Color.TEXT_HIGHLIGHT)
        y += 1

        good_type = metadata.get("good_type", "Unknown")
        # Truncate if needed
        if len(good_type) > self.width - 2:
            good_type = good_type[: self.width - 5] + "..."
        self.window.put_string(1, y, good_type, Color.TEXT_PRIMARY)
        y += 2

        # Quality
        quality = metadata.get("quality", 50)
        quality_name, quality_color = self._get_quality_display(quality)
        self.window.put_string(1, y, f"Quality: {quality:.0f}", Color.TEXT_SECONDARY)
        self.window.put_string(11, y, f"({quality_name})", quality_color)
        y += 2

        # Tags
        tags = metadata.get("type_tags", [])
        if tags:
            self.window.put_string(1, y, "Tags:", Color.TEXT_MUTED)
            y += 1
            tag_str = ", ".join(tags[:3])
            if len(tag_str) > self.width - 3:
                tag_str = tag_str[: self.width - 6] + "..."
            self.window.put_string(2, y, tag_str, Color.TEXT_SECONDARY)
            y += 2

        # Hint
        y = self.height - 3
        self.window.put_string(1, y, "Push with movement", Color.TEXT_MUTED)

    def _render_wagon(self, entity: Dict, metadata: Dict):
        """Render wagon information."""
        y = 1

        self.window.put_string(1, y, "WAGON", Color.TEXT_HIGHLIGHT)
        y += 2

        loaded_items = metadata.get("loaded_item_ids", [])
        capacity = metadata.get("capacity", 100)

        self.window.put_string(1, y, f"Loaded: {len(loaded_items)}/{capacity}", Color.TEXT_SECONDARY)
        y += 2

        if loaded_items:
            self.window.put_string(1, y, "Contents:", Color.TEXT_MUTED)
            y += 1
            # We'd need item details to show names
            for i, _ in enumerate(loaded_items[:5]):
                self.window.put_string(2, y, f"- Item {i + 1}", Color.TEXT_SECONDARY)
                y += 1

        # Hitched status
        hitched_by = metadata.get("hitched_by")
        y = self.height - 5
        if hitched_by:
            self.window.put_string(1, y, "Status: Hitched", Color.SUCCESS)
        else:
            self.window.put_string(1, y, "Status: Unhitched", Color.TEXT_MUTED)

        # Controls
        y = self.height - 3
        self.window.put_string(1, y, "[H] Hitch/Unhitch", Color.TEXT_HIGHLIGHT)
        if loaded_items:
            self.window.put_string(1, y + 1, "[U] Unload", Color.TEXT_HIGHLIGHT)

    def _render_dispenser(self, entity: Dict, metadata: Dict):
        """Render dispenser information."""
        y = 1

        self.window.put_string(1, y, "DISPENSER", Color.TEXT_HIGHLIGHT)
        y += 2

        good_type = metadata.get("stored_good_type", "Unknown")
        self.window.put_string(1, y, f"Stores: {good_type}", Color.TEXT_PRIMARY)
        y += 1

        capacity = metadata.get("capacity", 10)
        stored = len(metadata.get("stored_item_ids", []))
        self.window.put_string(1, y, f"Items: {stored}/{capacity}", Color.TEXT_SECONDARY)

    def _render_container(self, entity: Dict, metadata: Dict):
        """Render container information."""
        y = 1

        self.window.put_string(1, y, "CONTAINER", Color.TEXT_HIGHLIGHT)
        y += 2

        good_type = metadata.get("stored_good_type", "Various")
        self.window.put_string(1, y, f"Stores: {good_type}", Color.TEXT_PRIMARY)
        y += 1

        capacity = metadata.get("capacity", 10)
        stored = len(metadata.get("stored_item_ids", []))
        self.window.put_string(1, y, f"Items: {stored}/{capacity}", Color.TEXT_SECONDARY)
        y += 2

        # Show top item if any
        top_item = metadata.get("top_item_name")
        if top_item:
            self.window.put_string(1, y, "Next: ", Color.TEXT_MUTED)
            self.window.put_string(7, y, top_item[:self.width - 9], Color.TEXT_PRIMARY)
            y += 1

        # Controls hint
        y = self.height - 3
        self.window.put_string(1, y, "[E] Dispense item", Color.TEXT_HIGHLIGHT)

    def _render_delivery(self, entity: Dict, metadata: Dict):
        """Render delivery zone information."""
        y = 1

        self.window.put_string(1, y, "DELIVERY ZONE", Color.TEXT_HIGHLIGHT)
        y += 2

        self.window.put_string(1, y, "Push items here to", Color.TEXT_SECONDARY)
        y += 1
        self.window.put_string(1, y, "complete deliveries", Color.TEXT_SECONDARY)

    def _render_signpost(self, entity: Dict, metadata: Dict):
        """Render signpost information."""
        y = 1

        self.window.put_string(1, y, "SIGNPOST", Color.TEXT_HIGHLIGHT)
        y += 2

        destination = metadata.get("destination_name", "Unknown")
        self.window.put_string(1, y, f"To: {destination}", Color.TEXT_PRIMARY)
        y += 2

        self.window.put_string(1, y, "[Space] Travel", Color.TEXT_HIGHLIGHT)

    def _render_monster(self, entity: Dict, metadata: Dict):
        """Render other monster information."""
        y = 1

        monster_type = metadata.get("monster_type", "unknown").upper()
        name = metadata.get("name", "Unknown")

        self.window.put_string(1, y, monster_type, Color.TEXT_HIGHLIGHT)
        y += 1
        self.window.put_string(1, y, f'"{name}"', Color.TEXT_PRIMARY)

    def _render_unknown(self, entity: Dict, metadata: Dict):
        """Render unknown entity information."""
        y = 1

        kind = metadata.get("kind", "unknown")
        self.window.put_string(1, y, kind.upper(), Color.TEXT_HIGHLIGHT)

    def _get_quality_display(self, quality: float) -> tuple:
        """Get quality name and color."""
        if quality >= QUALITY_MASTERWORK:
            return "Masterwork", Color.ITEM_SILK
        elif quality >= QUALITY_FINE:
            return "Fine", Color.ITEM_METAL
        elif quality >= QUALITY_NORMAL:
            return "Normal", Color.TEXT_SECONDARY
        else:
            return "Poor", Color.TEXT_MUTED
