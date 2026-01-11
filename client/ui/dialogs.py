"""Dialog rendering for spawn monster and recipe selection."""

from typing import Optional

from config import Color, MONSTER_TYPES, TRANSFERABLE_SKILLS
from input.handlers import SpawnDialogState, RecipeDialogState


class DialogRenderer:
    """Base class for dialog rendering."""

    def __init__(self, window):
        """Initialize the dialog renderer.

        Args:
            window: pyunicodegame window (usually the UI root)
        """
        self.window = window

    def _draw_box(self, x: int, y: int, width: int, height: int, title: str = ""):
        """Draw a dialog box.

        Args:
            x, y: Top-left position
            width, height: Box dimensions
            title: Optional title
        """
        # Top border
        if title:
            padding = (width - len(title) - 2) // 2
            top = "+" + "-" * padding + " " + title + " " + "-" * (width - padding - len(title) - 3) + "+"
        else:
            top = "+" + "-" * (width - 2) + "+"
        self.window.put_string(x, y, top, Color.PANEL_BORDER)

        # Sides
        for row in range(1, height - 1):
            self.window.put(x, y + row, "|", Color.PANEL_BORDER)
            self.window.put(x + width - 1, y + row, "|", Color.PANEL_BORDER)
            # Clear interior
            self.window.put_string(x + 1, y + row, " " * (width - 2), Color.TEXT_PRIMARY)

        # Bottom border
        self.window.put_string(x, y + height - 1, "+" + "-" * (width - 2) + "+", Color.PANEL_BORDER)


class SpawnDialog(DialogRenderer):
    """Dialog for spawning a new monster."""

    WIDTH = 36
    HEIGHT = 20

    def render(self, state: SpawnDialogState, screen_width: int, screen_height: int):
        """Render the spawn dialog.

        Args:
            state: Current dialog state
            screen_width, screen_height: Screen dimensions for centering
        """
        # Center the dialog
        x = (screen_width - self.WIDTH) // 2
        y = (screen_height - self.HEIGHT) // 2

        # Draw box
        self._draw_box(x, y, self.WIDTH, self.HEIGHT, "CREATE NEW MONSTER")

        inner_x = x + 2
        inner_y = y + 2

        # Monster type selector
        type_label = "Type:"
        type_color = Color.TEXT_HIGHLIGHT if state.focus == "type" else Color.TEXT_PRIMARY
        self.window.put_string(inner_x, inner_y, type_label, type_color)

        # Type selector with arrows
        type_name = state.monster_type.title()
        selector = f"[< {type_name:^10} >]"
        self.window.put_string(inner_x + 7, inner_y, selector, type_color)

        inner_y += 2

        # Name field
        name_label = "Name:"
        name_color = Color.TEXT_HIGHLIGHT if state.focus == "name" else Color.TEXT_PRIMARY
        self.window.put_string(inner_x, inner_y, name_label, name_color)

        # Render text input field
        field_x = inner_x + 7
        field_width = self.WIDTH - 11
        state.name_field.active = state.focus == "name"
        state.name_field.render(
            self.window,
            field_x,
            inner_y,
            field_width,
            name_color,
            Color.TEXT_HIGHLIGHT,
        )

        inner_y += 2

        # Skills selection
        skills_label = f"Select 3 Skills ({len(state.selected_skills)}/3):"
        skills_color = Color.TEXT_HIGHLIGHT if state.focus == "skills" else Color.TEXT_PRIMARY
        self.window.put_string(inner_x, inner_y, skills_label, skills_color)

        inner_y += 1

        # Skill list
        for i, skill in enumerate(TRANSFERABLE_SKILLS):
            checkbox = "[x]" if skill in state.selected_skills else "[ ]"
            skill_display = skill.replace("_", " ").title()

            # Highlight current selection
            if state.focus == "skills" and i == state.skill_cursor:
                color = Color.TEXT_HIGHLIGHT
                prefix = "> "
            else:
                color = Color.TEXT_SECONDARY if skill in state.selected_skills else Color.TEXT_MUTED
                prefix = "  "

            self.window.put_string(inner_x, inner_y + i, f"{prefix}{checkbox} {skill_display}", color)

        # Controls hint
        hint_y = y + self.HEIGHT - 2
        can_create = state.can_create()

        if can_create:
            self.window.put_string(inner_x, hint_y, "[Enter] Create", Color.SUCCESS)
        else:
            self.window.put_string(inner_x, hint_y, "[Enter] Create", Color.TEXT_MUTED)

        self.window.put_string(inner_x + 16, hint_y, "[Esc] Cancel", Color.TEXT_SECONDARY)

        # Navigation hint
        nav_y = y + self.HEIGHT - 3
        self.window.put_string(inner_x, nav_y, "[Tab] Switch field  [Space] Toggle", Color.TEXT_MUTED)


class RecipeDialog(DialogRenderer):
    """Dialog for selecting a workshop recipe."""

    WIDTH = 38
    HEIGHT = 18

    def render(
        self,
        state: RecipeDialogState,
        screen_width: int,
        screen_height: int,
        recipe_details: Optional[dict] = None,
    ):
        """Render the recipe selection dialog.

        Args:
            state: Current dialog state
            screen_width, screen_height: Screen dimensions for centering
            recipe_details: Optional details about selected recipe
        """
        # Center the dialog
        x = (screen_width - self.WIDTH) // 2
        y = (screen_height - self.HEIGHT) // 2

        # Draw box
        title = f"SELECT RECIPE"
        self._draw_box(x, y, self.WIDTH, self.HEIGHT, title)

        inner_x = x + 2
        inner_y = y + 2

        # Workshop name
        self.window.put_string(inner_x, inner_y, f"Workshop: {state.workshop_name}", Color.TEXT_SECONDARY)
        inner_y += 2

        # Recipe list
        visible_recipes = 6  # Max recipes to show at once
        start_idx = max(0, state.selected_index - visible_recipes // 2)
        end_idx = min(len(state.available_recipes), start_idx + visible_recipes)

        # Adjust start if we're near the end
        if end_idx - start_idx < visible_recipes and start_idx > 0:
            start_idx = max(0, end_idx - visible_recipes)

        for i, recipe in enumerate(state.available_recipes[start_idx:end_idx]):
            actual_idx = start_idx + i
            is_selected = actual_idx == state.selected_index

            if is_selected:
                prefix = "> "
                color = Color.TEXT_HIGHLIGHT
            else:
                prefix = "  "
                color = Color.TEXT_PRIMARY

            # Truncate if needed
            display_name = recipe
            if len(display_name) > self.WIDTH - 6:
                display_name = display_name[: self.WIDTH - 9] + "..."

            self.window.put_string(inner_x, inner_y + i, f"{prefix}{display_name}", color)

        # Scroll indicators
        if start_idx > 0:
            self.window.put_string(x + self.WIDTH - 4, inner_y, "^^^", Color.TEXT_MUTED)
        if end_idx < len(state.available_recipes):
            self.window.put_string(x + self.WIDTH - 4, inner_y + visible_recipes - 1, "vvv", Color.TEXT_MUTED)

        inner_y += visible_recipes + 1

        # Recipe details
        if recipe_details and state.selected_recipe:
            self.window.put_string(inner_x, inner_y, "Requirements:", Color.TEXT_SECONDARY)
            inner_y += 1

            # Inputs
            inputs = recipe_details.get("inputs", [])
            if inputs:
                inputs_str = ", ".join(inputs[:2])
                if len(inputs) > 2:
                    inputs_str += f" (+{len(inputs) - 2})"
                if len(inputs_str) > self.WIDTH - 4:
                    inputs_str = inputs_str[: self.WIDTH - 7] + "..."
                self.window.put_string(inner_x, inner_y, f"  In: {inputs_str}", Color.TEXT_MUTED)
                inner_y += 1

            # Tools
            tools = recipe_details.get("tools", [])
            if tools:
                tools_str = ", ".join(tools[:2])
                if len(tools) > 2:
                    tools_str += f" (+{len(tools) - 2})"
                if len(tools_str) > self.WIDTH - 4:
                    tools_str = tools_str[: self.WIDTH - 7] + "..."
                self.window.put_string(inner_x, inner_y, f"  Tools: {tools_str}", Color.TEXT_MUTED)
                inner_y += 1

            # Time
            time_ticks = recipe_details.get("time", 0)
            self.window.put_string(inner_x, inner_y, f"  Time: {time_ticks} ticks", Color.TEXT_MUTED)

        # Controls hint
        hint_y = y + self.HEIGHT - 2
        self.window.put_string(inner_x, hint_y, "[Enter] Select", Color.SUCCESS)
        self.window.put_string(inner_x + 16, hint_y, "[Esc] Cancel", Color.TEXT_SECONDARY)


class HelpOverlay(DialogRenderer):
    """Help overlay showing keybindings."""

    WIDTH = 50
    HEIGHT = 22

    def render(self, screen_width: int, screen_height: int):
        """Render the help overlay.

        Args:
            screen_width, screen_height: Screen dimensions for centering
        """
        x = (screen_width - self.WIDTH) // 2
        y = (screen_height - self.HEIGHT) // 2

        self._draw_box(x, y, self.WIDTH, self.HEIGHT, "CONTROLS")

        inner_x = x + 2
        inner_y = y + 2

        # Keybindings
        bindings = [
            ("Movement", ""),
            ("  WASD / Arrow Keys", "Move monster"),
            ("", ""),
            ("Actions", ""),
            ("  Space / E", "Interact"),
            ("  R", "Toggle Recording"),
            ("  P", "Toggle Playback"),
            ("  H", "Hitch/Unhitch Wagon"),
            ("  U", "Unload Wagon"),
            ("", ""),
            ("Menus", ""),
            ("  N", "New Monster"),
            ("  C", "Craft/Select Recipe"),
            ("  F1", "This Help"),
            ("", ""),
            ("  Q / Esc", "Quit"),
        ]

        for i, (key, action) in enumerate(bindings):
            if action:
                self.window.put_string(inner_x, inner_y + i, key, Color.TEXT_HIGHLIGHT)
                self.window.put_string(inner_x + 22, inner_y + i, action, Color.TEXT_SECONDARY)
            elif key:
                # Section header
                self.window.put_string(inner_x, inner_y + i, key, Color.TEXT_PRIMARY)

        # Dismiss hint
        hint_y = y + self.HEIGHT - 2
        self.window.put_string(inner_x, hint_y, "Press any key to close", Color.TEXT_MUTED)
