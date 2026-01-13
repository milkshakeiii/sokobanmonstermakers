"""Monster Workshop Client - Main entry point."""

# TODO: Add "Commune Status" page that shows:
#   - All monsters owned by the player (including phased-out ones)
#   - Ability to select which monster to control
#   - Commune resources/renown
#   - Monster stats overview

import logging
import sys
import os
import time

# Add client directory and pyunicodegame to path
_client_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _client_dir)
sys.path.insert(0, os.path.expanduser("~/Documents/github/pyunicodegame/src"))

import pygame
import pyunicodegame

from config import (
    Action,
    ACTION_TO_DIRECTION,
    Color,
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    PANEL_WIDTH,
    MONSTER_PANEL_HEIGHT,
    CONTEXT_PANEL_HEIGHT,
    NOTIFICATION_HEIGHT,
    GAME_AREA_X,
    GAME_WORLD_WIDTH,
    GAME_WORLD_HEIGHT,
    CAMERA_LERP_SPEED,
    LIGHT_CONFIGS,
)
from network.client import NetworkClient
from state.game_state import GameState
from input.handlers import InputHandler, InputState
from rendering.sprites import SpriteFactory, LightManager
from rendering.effects import EffectsManager
from rendering.trail import TrailRenderer
from ui.panels import MonsterPanel, ContextPanel
from ui.dialogs import SpawnDialog, RecipeDialog, HelpOverlay
from ui.notifications import NotificationManager, TutorialManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class MonsterWorkshopClient:
    """Main game client integrating all systems."""

    def __init__(self):
        # Core systems
        self.network = NetworkClient()
        self.game_state = GameState()
        self.input_handler = InputHandler()

        # Windows (initialized in setup)
        self.root_window = None
        self.game_window = None
        self.game_overlay_window = None  # Unlit overlay for UI text in world coords
        self.monster_panel_window = None
        self.context_panel_window = None
        self.notification_window = None
        self.ui_overlay_window = None

        # Rendering systems (initialized after windows)
        self.sprite_factory = None
        self.light_manager = None
        self.effects_manager = None
        self.trail_renderer = None

        # UI systems
        self.monster_panel = None
        self.context_panel = None
        self.notification_manager = None
        self.tutorial_manager = None
        self.spawn_dialog = None
        self.recipe_dialog = None
        self.help_overlay = None

        # Camera state
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.camera_initialized = False

        # Running flag
        self.running = False

    def start(self):
        """Start the game client."""
        logger.info("Starting Monster Workshop Client...")

        # 1. Authenticate
        if not self.network.authenticate():
            logger.error("Authentication failed")
            return

        # 2. Select zone
        if not self.network.select_zone("Starting Village"):
            logger.error("Zone selection failed")
            return

        # 3. Set up game state
        self.game_state.set_player_id(self.network.player_id)

        # 4. Set up callbacks
        self._setup_callbacks()

        # 5. Start network
        self.network.start()

        # 6. Spawn initial monster
        self.network.send_spawn_monster(
            monster_type="goblin",
            name="Player",
            transferable_skills=["handcrafts", "athletics", "outdoorsmonstership"],
        )

        # 7. Run game loop
        self.running = True
        self._run_game()

    def _setup_callbacks(self):
        """Set up callback functions for various systems."""
        # Input callbacks
        self.input_handler.set_callbacks(
            on_action=self._handle_action,
            on_dialog_submit=self._handle_dialog_submit,
            on_dialog_cancel=self._handle_dialog_cancel,
        )

    def _run_game(self):
        """Initialize pyunicodegame and run the main loop."""
        # Initialize display
        self.root_window = pyunicodegame.init(
            "Monster Workshop",
            width=SCREEN_WIDTH,
            height=SCREEN_HEIGHT,
            bg=(10, 10, 20, 255),
        )

        # Start in fullscreen
        pyunicodegame._toggle_fullscreen()

        # Create windows
        self._create_windows()

        # Initialize subsystems
        self._init_subsystems()

        # Run main loop
        pyunicodegame.run(
            update=self._update,
            render=self._render,
            on_key=self._on_key,
            on_event=self._on_event,
        )

        # Cleanup
        self.running = False
        self.network.stop()

    def _create_windows(self):
        """Create all game windows."""
        # Game world - large scrolling area
        self.game_window = pyunicodegame.create_window(
            "game",
            x=GAME_AREA_X,
            y=0,
            width=GAME_WORLD_WIDTH,
            height=GAME_WORLD_HEIGHT,
            z_index=0,
            depth=0.0,
        )

        # Game overlay for tutorial bubbles (unlit, same depth as game window)
        self.game_overlay_window = pyunicodegame.create_window(
            "game_overlay",
            x=GAME_AREA_X,
            y=0,
            width=GAME_WORLD_WIDTH,
            height=GAME_WORLD_HEIGHT,
            z_index=1,
            depth=0.0,
        )

        # Monster info panel (top-left, fixed)
        self.monster_panel_window = pyunicodegame.create_window(
            "monster_panel",
            x=0,
            y=0,
            width=PANEL_WIDTH,
            height=MONSTER_PANEL_HEIGHT,
            z_index=101,
            fixed=True,
            bg=Color.PANEL_BG_MONSTER,
        )

        # Context panel (below monster panel, fixed)
        self.context_panel_window = pyunicodegame.create_window(
            "context_panel",
            x=0,
            y=MONSTER_PANEL_HEIGHT,
            width=PANEL_WIDTH,
            height=CONTEXT_PANEL_HEIGHT,
            z_index=101,
            fixed=True,
            bg=Color.PANEL_BG_CONTEXT,
        )

        # Notification bar (bottom, fixed)
        self.notification_window = pyunicodegame.create_window(
            "notifications",
            x=0,
            y=SCREEN_HEIGHT - NOTIFICATION_HEIGHT,
            width=SCREEN_WIDTH,
            height=NOTIFICATION_HEIGHT,
            z_index=102,
            fixed=True,
            bg=Color.PANEL_BG_NOTIFY,
        )

        # UI overlay for dialogs (full screen, fixed, hidden by default)
        self.ui_overlay_window = pyunicodegame.create_window(
            "ui_overlay",
            x=0,
            y=0,
            width=SCREEN_WIDTH,
            height=SCREEN_HEIGHT,
            z_index=200,
            fixed=True,
            bg=(0, 0, 0, 180),
        )
        self.ui_overlay_window.visible = False

        # Enable lighting on game window (optimized with numpy vectorization)
        self.game_window.set_lighting(enabled=True, ambient=Color.AMBIENT)

    def _init_subsystems(self):
        """Initialize rendering and UI subsystems."""
        # Sprite factory
        self.sprite_factory = SpriteFactory(self.game_window, self.network.player_id)

        # Light manager (optimized with numpy vectorization)
        self.light_manager = LightManager(self.game_window, enabled=True)

        # Effects manager
        self.effects_manager = EffectsManager(self.game_window)

        # Trail renderer (for movement queue visualization)
        self.trail_renderer = TrailRenderer(self.game_overlay_window)

        # UI panels
        self.monster_panel = MonsterPanel(self.monster_panel_window)
        self.context_panel = ContextPanel(self.context_panel_window)

        # Notifications
        self.notification_manager = NotificationManager(self.notification_window)

        # Tutorial
        self.tutorial_manager = TutorialManager(self.game_window)

        # Dialogs
        self.spawn_dialog = SpawnDialog(self.ui_overlay_window)
        self.recipe_dialog = RecipeDialog(self.ui_overlay_window)
        self.help_overlay = HelpOverlay(self.ui_overlay_window)

    def _update(self, dt: float):
        """Main update loop.

        Args:
            dt: Delta time in seconds
        """
        # Process network state
        state = self.network.get_latest_state()
        if state:
            self._sync_state(state)

        # Process events
        events = self.network.get_events()
        for event in events:
            self._handle_event(event)

        # Update camera
        self._update_camera(dt)

        # Update UI overlay visibility
        self.ui_overlay_window.visible = self.input_handler.state != InputState.GAMEPLAY

    def _sync_state(self, state: dict):
        """Synchronize local state with server state.

        Args:
            state: State dictionary from server
        """
        entities = state.get("entities", [])

        # Update game state
        added, updated, removed = self.game_state.sync_entities(entities)

        # Update sprites
        self.sprite_factory.sync_entities(
            added, updated, removed, self.game_state.entities
        )

        # Update lights for entities (skip phased-out monsters)
        for eid in added | updated:
            entity = self.game_state.get_entity(eid)
            if entity:
                if self.game_state.is_phased_out(entity):
                    self.light_manager.remove_entity_light(eid)
                    self.effects_manager.remove_crafting_effect(eid)
                else:
                    self.light_manager.update_entity_light(eid, entity)
                    self.effects_manager.update_crafting_effect(eid, entity)

        for eid in removed:
            self.light_manager.remove_entity_light(eid)
            self.effects_manager.remove_crafting_effect(eid)

        # Create/update player torch
        monster = self.game_state.get_player_monster()
        if monster and self.game_state.local_monster_id:
            monster_sprite = self.sprite_factory.get_sprite(self.game_state.local_monster_id)
            if monster_sprite and not self.light_manager.player_light:
                self.light_manager.create_player_torch(monster_sprite)

        # Sync predicted movement queue with server state
        if monster:
            current_task = monster.get("metadata", {}).get("current_task", {})
            server_queue = current_task.get("movement_queue", [])
            self.game_state.sync_predicted_queue(server_queue)

        # Check tutorial triggers
        nearby = self.game_state.get_nearby_entity()
        self.tutorial_manager.check_nearby_entity(nearby, self.game_state)

        # Show welcome hint on first sync
        if monster and "welcome" not in self.tutorial_manager.shown_hints:
            self.tutorial_manager.show_bubble("Use WASD to move around.", 0, 0)
            self.tutorial_manager.shown_hints.add("welcome")

    def _handle_event(self, event: dict):
        """Handle a game event from the server.

        Args:
            event: Event dictionary
        """
        # Pass to notification manager
        self.notification_manager.handle_event(event)

        # Handle specific events
        event_type = event.get("type", "")

        if event_type == "push":
            # Mark that player has pushed
            self.game_state.player_has_pushed = True

            # Show push effect
            entity_id = event.get("entity_id")
            entity = self.game_state.get_entity(entity_id)
            if entity:
                self.effects_manager.show_push_effect(
                    entity["x"],
                    entity["y"],
                    self.game_state.facing_direction,
                )

        elif event_type == "blocked":
            monster = self.game_state.get_player_monster()
            if monster:
                self.effects_manager.show_blocked_effect(
                    monster["x"],
                    monster["y"],
                    self.game_state.facing_direction,
                )

        elif event_type == "spawned":
            entity_id = event.get("entity_id")
            entity = self.game_state.get_entity(entity_id)
            if entity:
                self.effects_manager.show_spawn_effect(entity["x"], entity["y"])

    def _update_camera(self, dt: float):
        """Update camera position to follow player.

        Args:
            dt: Delta time
        """
        monster = self.game_state.get_player_monster()
        if not monster:
            return

        monster_sprite = self.sprite_factory.get_sprite(self.game_state.local_monster_id)
        if not monster_sprite:
            return

        # Get cell size for pixel calculations
        cell_w, cell_h = self.game_window.cell_size

        # Target: center monster in visible game area
        visible_width = SCREEN_WIDTH - PANEL_WIDTH
        visible_height = SCREEN_HEIGHT - NOTIFICATION_HEIGHT

        target_x = monster_sprite.x * cell_w - (visible_width * cell_w) / 2
        target_y = monster_sprite.y * cell_h - (visible_height * cell_h) / 2

        # Snap to target on first frame, then lerp
        if not self.camera_initialized:
            self.camera_x = target_x
            self.camera_y = target_y
            self.camera_initialized = True
        else:
            # Smooth interpolation
            self.camera_x += (target_x - self.camera_x) * CAMERA_LERP_SPEED
            self.camera_y += (target_y - self.camera_y) * CAMERA_LERP_SPEED

        # Apply camera
        pyunicodegame.set_camera(x=self.camera_x, y=self.camera_y)

    def _render(self):
        """Main render loop."""
        # Clear the game overlay (transparent background)
        if self.game_overlay_window:
            self.game_overlay_window.surface.fill((0, 0, 0, 0))

        # Render movement trail on overlay
        if self.trail_renderer:
            trail_positions = self.game_state.get_trail_positions()
            self.trail_renderer.render(trail_positions)

        # Render UI panels
        monster = self.game_state.get_player_monster()
        self.monster_panel.render(
            monster,
            is_recording=self.game_state.is_monster_recording(),
            is_playing=self.game_state.is_monster_playing(),
        )

        nearby_entity = self.game_state.get_nearby_entity()
        self.context_panel.render(nearby_entity, self.game_state.facing_direction)

        # Render notifications
        self.notification_manager.render()

        # FPS counter in notification bar
        fps = pyunicodegame._clock.get_fps()
        self.notification_window.put_string(
            SCREEN_WIDTH - 12, 0, f"FPS: {fps:5.1f}", Color.TEXT_MUTED
        )

        # Render tutorial bubble
        if monster and self.game_overlay_window:
            self.tutorial_manager.render_near_player(
                self.game_overlay_window,
                monster["x"],
                monster["y"]
            )

        # Render dialogs if active
        if self.input_handler.state == InputState.SPAWN_DIALOG:
            self.spawn_dialog.render(
                self.input_handler.spawn_dialog,
                SCREEN_WIDTH,
                SCREEN_HEIGHT,
            )
        elif self.input_handler.state == InputState.RECIPE_DIALOG:
            self.recipe_dialog.render(
                self.input_handler.recipe_dialog,
                SCREEN_WIDTH,
                SCREEN_HEIGHT,
            )
        elif self.input_handler.state == InputState.HELP_OVERLAY:
            self.help_overlay.render(SCREEN_WIDTH, SCREEN_HEIGHT)

    def _on_key(self, key: int):
        """Handle key press.

        Args:
            key: pygame key code
        """
        self.input_handler.handle_key(key, "")

    def _on_event(self, event: pygame.event.Event) -> bool:
        """Handle pygame event.

        Args:
            event: pygame event

        Returns:
            True to consume the event
        """
        if event.type == pygame.KEYDOWN:
            # Dismiss tutorial bubble on any key press first
            if self.tutorial_manager.on_key_press():
                return True  # Consume the key if bubble was dismissed

            # Get unicode character for text input
            unicode_char = event.unicode if hasattr(event, "unicode") else ""
            self.input_handler.handle_key(event.key, unicode_char)

            return True

        return False

    def _handle_action(self, action: Action, extra_data: dict):
        """Handle a gameplay action.

        Args:
            action: The action to perform
            extra_data: Additional data (e.g., direction)
        """
        monster_id = self.game_state.local_monster_id

        if action == Action.QUIT:
            pyunicodegame.quit()
            return

        if action == Action.TOGGLE_FULLSCREEN:
            pyunicodegame._toggle_fullscreen()
            return

        # Most actions require a monster
        if not monster_id:
            self.notification_manager.add_warning("No monster - press [N] to spawn")
            return

        # Movement
        if action in ACTION_TO_DIRECTION:
            direction = extra_data.get("direction")
            if direction:
                self.game_state.update_facing(direction)
                # Add to predicted queue for immediate trail feedback
                self.game_state.add_predicted_step(direction)
                self.network.send_move(direction, monster_id)

        # Clear path
        elif action == Action.CLEAR_PATH:
            self.game_state.clear_predicted_queue()
            self.network.send_clear_path(monster_id)

        # Interact
        elif action == Action.INTERACT:
            self.network.send_interact(monster_id)

        # Recording
        elif action == Action.TOGGLE_RECORDING:
            if self.game_state.is_monster_recording():
                self.network.send_recording_stop()
            else:
                self.network.send_recording_start()
                self.game_state.player_has_recorded = True

        # Playback
        elif action == Action.TOGGLE_PLAYBACK:
            if self.game_state.is_monster_playing():
                self.network.send_autorepeat_stop()
            else:
                self.network.send_autorepeat_start()

        # Wagon
        elif action == Action.TOGGLE_HITCH:
            if self.game_state.is_monster_hitched():
                self.network.send_unhitch_wagon()
            else:
                self.network.send_hitch_wagon()

        elif action == Action.UNLOAD_WAGON:
            self.network.send_unload_wagon()

        # Dialogs
        elif action == Action.OPEN_SPAWN_DIALOG:
            self.input_handler.open_spawn_dialog()

        elif action == Action.OPEN_RECIPE_DIALOG:
            workshop = self.game_state.get_adjacent_workshop()
            if workshop:
                # TODO: Get available recipes from workshop metadata
                recipes = ["Silk Thread", "Cotton Thread", "Fabric"]  # Placeholder
                workshop_name = workshop.get("metadata", {}).get("workshop_type", "Workshop")
                self.input_handler.open_recipe_dialog(
                    workshop["id"],
                    workshop_name,
                    recipes,
                )
            else:
                self.notification_manager.add_warning("No workshop nearby")

    def _handle_dialog_submit(self, dialog_type: str, data: dict):
        """Handle dialog submission.

        Args:
            dialog_type: Type of dialog ("spawn_monster", "select_recipe")
            data: Dialog data
        """
        if dialog_type == "spawn_monster":
            self.network.send_spawn_monster(
                monster_type=data["monster_type"],
                name=data["name"],
                transferable_skills=data["skills"],
            )

        elif dialog_type == "select_recipe":
            self.network.send_select_recipe(
                workshop_id=data["workshop_id"],
                recipe_id=data["recipe_id"],
                monster_id=self.game_state.local_monster_id,
            )

    def _handle_dialog_cancel(self):
        """Handle dialog cancellation."""
        pass  # Nothing special needed


def main():
    """Main entry point."""
    client = MonsterWorkshopClient()
    client.start()


if __name__ == "__main__":
    main()
