"""Input handling and state machine for the game client."""

import time
from enum import Enum, auto
from typing import Any, Callable, Dict, Optional

import pygame

from config import (
    Action,
    ACTION_TO_DIRECTION,
    DEFAULT_KEYBINDS,
    MONSTER_TYPES,
    TRANSFERABLE_SKILLS,
)


class InputState(Enum):
    """Current input context/state."""
    GAMEPLAY = auto()
    SPAWN_DIALOG = auto()
    RECIPE_DIALOG = auto()
    HELP_OVERLAY = auto()


class TextInputField:
    """Text input field for dialogs."""

    def __init__(self, max_length: int = 20):
        self.text = ""
        self.cursor = 0
        self.max_length = max_length
        self.active = False

    def handle_key(self, key: int, unicode_char: str) -> bool:
        """Handle a key press.

        Args:
            key: pygame key code
            unicode_char: Unicode character from event

        Returns:
            True if key was consumed
        """
        if key == pygame.K_BACKSPACE:
            if self.cursor > 0:
                self.text = self.text[: self.cursor - 1] + self.text[self.cursor :]
                self.cursor -= 1
            return True
        elif key == pygame.K_DELETE:
            self.text = self.text[: self.cursor] + self.text[self.cursor + 1 :]
            return True
        elif key == pygame.K_LEFT:
            self.cursor = max(0, self.cursor - 1)
            return True
        elif key == pygame.K_RIGHT:
            self.cursor = min(len(self.text), self.cursor + 1)
            return True
        elif key == pygame.K_HOME:
            self.cursor = 0
            return True
        elif key == pygame.K_END:
            self.cursor = len(self.text)
            return True
        elif unicode_char and len(self.text) < self.max_length:
            if unicode_char.isprintable() and ord(unicode_char) >= 32:
                self.text = (
                    self.text[: self.cursor] + unicode_char + self.text[self.cursor :]
                )
                self.cursor += 1
                return True
        return False

    def render(self, window, x: int, y: int, width: int, fg_color, cursor_color):
        """Render the text field.

        Args:
            window: pyunicodegame window
            x, y: Position
            width: Field width in characters
            fg_color: Text color
            cursor_color: Cursor color
        """
        # Draw field with brackets
        display_text = self.text.ljust(width - 2)
        field = f"[{display_text}]"
        window.put_string(x, y, field, fg_color)

        # Draw blinking cursor
        if self.active and int(time.time() * 2) % 2:
            cursor_x = x + 1 + self.cursor
            window.put(cursor_x, y, "_", cursor_color)

    def clear(self):
        """Clear the field."""
        self.text = ""
        self.cursor = 0


class SpawnDialogState:
    """State for the spawn monster dialog."""

    def __init__(self):
        self.monster_type_index = 0
        self.name_field = TextInputField(max_length=20)
        self.selected_skills: set = set()
        self.skill_cursor = 0
        self.focus = "type"  # "type", "name", or "skills"

        # Set default name
        self.name_field.text = "Monster"
        self.name_field.cursor = len(self.name_field.text)

    @property
    def monster_type(self) -> str:
        return MONSTER_TYPES[self.monster_type_index]

    @property
    def skills_list(self) -> list:
        return TRANSFERABLE_SKILLS

    def toggle_skill(self, skill: str):
        """Toggle a skill selection."""
        if skill in self.selected_skills:
            self.selected_skills.remove(skill)
        elif len(self.selected_skills) < 3:
            self.selected_skills.add(skill)

    def can_create(self) -> bool:
        """Check if monster can be created."""
        return (
            len(self.name_field.text.strip()) > 0
            and len(self.selected_skills) == 3
        )

    def reset(self):
        """Reset dialog state."""
        self.monster_type_index = 0
        self.name_field.clear()
        self.name_field.text = "Monster"
        self.name_field.cursor = len(self.name_field.text)
        self.selected_skills.clear()
        self.skill_cursor = 0
        self.focus = "type"


class RecipeDialogState:
    """State for the recipe selection dialog."""

    def __init__(self):
        self.workshop_id: Optional[str] = None
        self.workshop_name: str = ""
        self.available_recipes: list = []
        self.selected_index = 0

    @property
    def selected_recipe(self) -> Optional[str]:
        if 0 <= self.selected_index < len(self.available_recipes):
            return self.available_recipes[self.selected_index]
        return None

    def reset(self):
        """Reset dialog state."""
        self.workshop_id = None
        self.workshop_name = ""
        self.available_recipes = []
        self.selected_index = 0


class InputHandler:
    """Handles all input processing and state management."""

    def __init__(self):
        self.state = InputState.GAMEPLAY
        self.keybinds = DEFAULT_KEYBINDS.copy()

        # Dialog states
        self.spawn_dialog = SpawnDialogState()
        self.recipe_dialog = RecipeDialogState()

        # Callbacks
        self._on_action: Optional[Callable[[Action, Dict], None]] = None
        self._on_dialog_submit: Optional[Callable[[str, Dict], None]] = None
        self._on_dialog_cancel: Optional[Callable[[], None]] = None

    def set_callbacks(
        self,
        on_action: Optional[Callable[[Action, Dict], None]] = None,
        on_dialog_submit: Optional[Callable[[str, Dict], None]] = None,
        on_dialog_cancel: Optional[Callable[[], None]] = None,
    ):
        """Set callback functions.

        Args:
            on_action: Called when a gameplay action is triggered
            on_dialog_submit: Called when a dialog is submitted
            on_dialog_cancel: Called when a dialog is cancelled
        """
        self._on_action = on_action
        self._on_dialog_submit = on_dialog_submit
        self._on_dialog_cancel = on_dialog_cancel

    def open_spawn_dialog(self):
        """Open the spawn monster dialog."""
        self.spawn_dialog.reset()
        self.state = InputState.SPAWN_DIALOG

    def open_recipe_dialog(self, workshop_id: str, workshop_name: str, recipes: list):
        """Open the recipe selection dialog.

        Args:
            workshop_id: ID of the workshop
            workshop_name: Display name of workshop
            recipes: List of available recipe names
        """
        self.recipe_dialog.reset()
        self.recipe_dialog.workshop_id = workshop_id
        self.recipe_dialog.workshop_name = workshop_name
        self.recipe_dialog.available_recipes = recipes
        self.state = InputState.RECIPE_DIALOG

    def open_help(self):
        """Open the help overlay."""
        self.state = InputState.HELP_OVERLAY

    def close_dialog(self):
        """Close any open dialog and return to gameplay."""
        self.state = InputState.GAMEPLAY
        if self._on_dialog_cancel:
            self._on_dialog_cancel()

    def handle_key(self, key: int, unicode_char: str = "") -> bool:
        """Handle a key press.

        Args:
            key: pygame key code
            unicode_char: Unicode character from event

        Returns:
            True if key was consumed
        """
        if self.state == InputState.GAMEPLAY:
            return self._handle_gameplay(key)
        elif self.state == InputState.SPAWN_DIALOG:
            return self._handle_spawn_dialog(key, unicode_char)
        elif self.state == InputState.RECIPE_DIALOG:
            return self._handle_recipe_dialog(key)
        elif self.state == InputState.HELP_OVERLAY:
            return self._handle_help(key)
        return False

    def _handle_gameplay(self, key: int) -> bool:
        """Handle input in gameplay state."""
        action = self.keybinds.get(key)
        if action is None:
            return False

        # Handle UI actions directly
        if action == Action.QUIT:
            if self._on_action:
                self._on_action(action, {})
            return True

        if action == Action.TOGGLE_HELP:
            self.open_help()
            return True

        if action == Action.OPEN_SPAWN_DIALOG:
            self.open_spawn_dialog()
            return True

        # Other actions require a callback
        if self._on_action:
            extra_data = {}

            # Add direction for movement
            if action in ACTION_TO_DIRECTION:
                extra_data["direction"] = ACTION_TO_DIRECTION[action]

            self._on_action(action, extra_data)

        return True

    def _handle_spawn_dialog(self, key: int, unicode_char: str) -> bool:
        """Handle input in spawn dialog."""
        dialog = self.spawn_dialog

        # Escape to cancel
        if key == pygame.K_ESCAPE:
            self.close_dialog()
            return True

        # Tab or up/down to change focus
        if key == pygame.K_TAB:
            if dialog.focus == "type":
                dialog.focus = "name"
                dialog.name_field.active = True
            elif dialog.focus == "name":
                dialog.focus = "skills"
                dialog.name_field.active = False
            else:
                dialog.focus = "type"
            return True

        # Handle based on focus
        if dialog.focus == "type":
            if key in (pygame.K_LEFT, pygame.K_a):
                dialog.monster_type_index = (dialog.monster_type_index - 1) % len(MONSTER_TYPES)
                return True
            elif key in (pygame.K_RIGHT, pygame.K_d):
                dialog.monster_type_index = (dialog.monster_type_index + 1) % len(MONSTER_TYPES)
                return True
            elif key in (pygame.K_DOWN, pygame.K_s):
                dialog.focus = "name"
                dialog.name_field.active = True
                return True

        elif dialog.focus == "name":
            dialog.name_field.active = True
            if key in (pygame.K_UP, pygame.K_w):
                dialog.focus = "type"
                dialog.name_field.active = False
                return True
            elif key in (pygame.K_DOWN, pygame.K_s):
                dialog.focus = "skills"
                dialog.name_field.active = False
                return True
            elif key == pygame.K_RETURN:
                dialog.focus = "skills"
                dialog.name_field.active = False
                return True
            else:
                return dialog.name_field.handle_key(key, unicode_char)

        elif dialog.focus == "skills":
            if key in (pygame.K_UP, pygame.K_w):
                if dialog.skill_cursor > 0:
                    dialog.skill_cursor -= 1
                else:
                    dialog.focus = "name"
                    dialog.name_field.active = True
                return True
            elif key in (pygame.K_DOWN, pygame.K_s):
                if dialog.skill_cursor < len(TRANSFERABLE_SKILLS) - 1:
                    dialog.skill_cursor += 1
                return True
            elif key == pygame.K_SPACE:
                skill = TRANSFERABLE_SKILLS[dialog.skill_cursor]
                dialog.toggle_skill(skill)
                return True

        # Enter to create
        if key == pygame.K_RETURN and dialog.can_create():
            if self._on_dialog_submit:
                self._on_dialog_submit(
                    "spawn_monster",
                    {
                        "monster_type": dialog.monster_type,
                        "name": dialog.name_field.text.strip(),
                        "skills": list(dialog.selected_skills),
                    },
                )
            self.state = InputState.GAMEPLAY
            return True

        return False

    def _handle_recipe_dialog(self, key: int) -> bool:
        """Handle input in recipe dialog."""
        dialog = self.recipe_dialog

        # Escape to cancel
        if key == pygame.K_ESCAPE:
            self.close_dialog()
            return True

        # Navigate recipes
        if key in (pygame.K_UP, pygame.K_w):
            if dialog.selected_index > 0:
                dialog.selected_index -= 1
            return True
        elif key in (pygame.K_DOWN, pygame.K_s):
            if dialog.selected_index < len(dialog.available_recipes) - 1:
                dialog.selected_index += 1
            return True

        # Select recipe
        if key == pygame.K_RETURN and dialog.selected_recipe:
            if self._on_dialog_submit:
                self._on_dialog_submit(
                    "select_recipe",
                    {
                        "workshop_id": dialog.workshop_id,
                        "recipe_id": dialog.selected_recipe,
                    },
                )
            self.state = InputState.GAMEPLAY
            return True

        return False

    def _handle_help(self, key: int) -> bool:
        """Handle input in help overlay - any key dismisses."""
        self.state = InputState.GAMEPLAY
        return True
