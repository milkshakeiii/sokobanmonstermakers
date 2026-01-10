"""Monster Workshop - Frontend Client.

pyunicodegame-based client for rendering the game world with
unicode graphics, particles, animations, and effects.
"""

import asyncio
import json
import sys
from typing import Optional
from dataclasses import dataclass

try:
    import pygame
except ImportError as exc:
    raise SystemExit(
        "Error: pygame is required to run the client. Install with: pip install pygame"
    ) from exc

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    print("Warning: websockets not installed. Run: pip install websockets")


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class GameConfig:
    """Game configuration settings."""
    # Server connection
    server_url: str = "ws://localhost:8000/ws"
    api_url: str = "http://localhost:8000"

    # Display settings
    cell_width: int = 8  # Narrow character width
    cell_height: int = 16  # Character height
    viewport_width: int = 60  # Cells visible horizontally
    viewport_height: int = 20  # Cells visible vertically

    # Panel sizes
    panel_width: int = 20  # Left panel width in cells

    # Colors (RGB)
    bg_color: tuple = (10, 10, 20)  # Dark background
    text_color: tuple = (200, 200, 200)  # Light text
    highlight_color: tuple = (100, 200, 255)  # Cyan highlight

    # Animation settings
    bob_amplitude: float = 2.0  # Pixels for idle bob
    bob_speed: float = 2.0  # Cycles per second

    @property
    def window_width(self) -> int:
        """Total window width in pixels."""
        return (self.panel_width + self.viewport_width) * self.cell_width * 2

    @property
    def window_height(self) -> int:
        """Total window height in pixels."""
        return self.viewport_height * self.cell_height


# =============================================================================
# Game State
# =============================================================================

@dataclass
class GameState:
    """Client-side game state."""
    connected: bool = False
    authenticated: bool = False
    player_id: Optional[str] = None
    token: Optional[str] = None
    current_zone_id: Optional[str] = None
    current_monster_id: Optional[str] = None
    camera_x: int = 0
    camera_y: int = 0
    tick_number: int = 0

    # Zone data
    entities: dict = None
    monsters: dict = None
    terrain: list = None

    def __post_init__(self):
        if self.entities is None:
            self.entities = {}
        if self.monsters is None:
            self.monsters = {}
        if self.terrain is None:
            self.terrain = []


# =============================================================================
# Network Client
# =============================================================================

class NetworkClient:
    """WebSocket client for server communication."""

    def __init__(self, config: GameConfig):
        self.config = config
        self.websocket = None
        self.connected = False
        self.message_queue = asyncio.Queue()

    async def connect(self, token: str) -> bool:
        """Connect to game server with authentication token."""
        if not WEBSOCKETS_AVAILABLE:
            print("Cannot connect: websockets not installed")
            return False

        try:
            url = f"{self.config.server_url}?token={token}"
            self.websocket = await websockets.connect(url)
            self.connected = True
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    async def disconnect(self):
        """Disconnect from server."""
        if self.websocket:
            await self.websocket.close()
            self.connected = False

    async def send(self, message: dict):
        """Send message to server."""
        if self.websocket and self.connected:
            await self.websocket.send(json.dumps(message))

    async def receive(self) -> Optional[dict]:
        """Receive message from server."""
        if self.websocket and self.connected:
            try:
                data = await asyncio.wait_for(self.websocket.recv(), timeout=0.1)
                return json.loads(data)
            except asyncio.TimeoutError:
                return None
            except Exception as e:
                print(f"Receive error: {e}")
                return None
        return None

    async def subscribe_zone(self, zone_id: str):
        """Subscribe to zone updates."""
        await self.send({
            "type": "subscribe",
            "zone_id": zone_id
        })

    async def send_intent(self, action: str, **kwargs):
        """Send player intent to server."""
        await self.send({
            "type": "intent",
            "data": {
                "action": action,
                **kwargs
            }
        })


# =============================================================================
# Renderer (Placeholder)
# =============================================================================

class Renderer:
    """Unicode-based game renderer using pyunicodegame."""

    def __init__(self, config: GameConfig):
        self.config = config
        self.screen = None
        self.font = None
        self.initialized = False

    def init(self):
        """Initialize pygame and renderer."""
        pygame.init()
        self.screen = pygame.display.set_mode(
            (self.config.window_width, self.config.window_height)
        )
        pygame.display.set_caption("Monster Workshop")

        # Try to load Unifont for unicode rendering
        try:
            self.font = pygame.font.Font(None, self.config.cell_height)
        except Exception:
            self.font = pygame.font.SysFont("monospace", self.config.cell_height)

        self.initialized = True
        return True

    def render(self, state: GameState):
        """Render the current game state."""
        if not self.initialized:
            return

        # Clear screen
        self.screen.fill(self.config.bg_color)

        # Render left panels
        self._render_panels(state)

        # Render game viewport
        self._render_viewport(state)

        # Update display
        pygame.display.flip()

    def _render_panels(self, state: GameState):
        """Render left-side info panels."""
        # Object info panel (top)
        panel_rect = pygame.Rect(
            0, 0,
            self.config.panel_width * self.config.cell_width * 2,
            self.config.window_height // 2
        )
        pygame.draw.rect(self.screen, (20, 20, 30), panel_rect)

        # Monster skills panel (bottom)
        panel_rect = pygame.Rect(
            0, self.config.window_height // 2,
            self.config.panel_width * self.config.cell_width * 2,
            self.config.window_height // 2
        )
        pygame.draw.rect(self.screen, (20, 25, 35), panel_rect)

    def _render_viewport(self, state: GameState):
        """Render the game world viewport."""
        viewport_x = self.config.panel_width * self.config.cell_width * 2
        viewport_rect = pygame.Rect(
            viewport_x, 0,
            self.config.viewport_width * self.config.cell_width * 2,
            self.config.viewport_height * self.config.cell_height
        )
        pygame.draw.rect(self.screen, (15, 15, 25), viewport_rect)

        # Render terrain
        for y, row in enumerate(state.terrain):
            for x, cell in enumerate(row):
                if 0 <= x - state.camera_x < self.config.viewport_width:
                    if 0 <= y - state.camera_y < self.config.viewport_height:
                        self._render_cell(
                            viewport_x + (x - state.camera_x) * self.config.cell_width * 2,
                            (y - state.camera_y) * self.config.cell_height,
                            cell
                        )

        # Render entities
        for entity_id, entity in state.entities.items():
            self._render_entity(viewport_x, state, entity)

        # Render monsters
        for monster_id, monster in state.monsters.items():
            self._render_monster(viewport_x, state, monster)

    def _render_cell(self, x: int, y: int, cell: str):
        """Render a single terrain cell."""
        if cell == "#":
            color = (60, 60, 80)  # Wall
        elif cell == ".":
            color = (30, 30, 40)  # Floor
        else:
            color = (20, 20, 30)

        rect = pygame.Rect(x, y, self.config.cell_width * 2, self.config.cell_height)
        pygame.draw.rect(self.screen, color, rect)

    def _render_entity(self, viewport_x: int, state: GameState, entity: dict):
        """Render an entity on the grid."""
        x = entity.get("x", 0) - state.camera_x
        y = entity.get("y", 0) - state.camera_y

        if 0 <= x < self.config.viewport_width and 0 <= y < self.config.viewport_height:
            px = viewport_x + x * self.config.cell_width * 2
            py = y * self.config.cell_height

            # Draw entity (placeholder)
            color = (100, 150, 200)
            rect = pygame.Rect(px, py, self.config.cell_width * 2, self.config.cell_height)
            pygame.draw.rect(self.screen, color, rect)

    def _render_monster(self, viewport_x: int, state: GameState, monster: dict):
        """Render a monster on the grid."""
        x = monster.get("x", 0) - state.camera_x
        y = monster.get("y", 0) - state.camera_y

        if 0 <= x < self.config.viewport_width and 0 <= y < self.config.viewport_height:
            px = viewport_x + x * self.config.cell_width * 2
            py = y * self.config.cell_height

            # Apply bob animation
            import time
            bob_offset = self.config.bob_amplitude * (
                1 + (0.5 * (1 + (time.time() * self.config.bob_speed % 1) * 2 - 1))
            )
            py += int(bob_offset)

            # Draw monster (placeholder - use unicode character later)
            color = (200, 100, 100) if monster.get("id") == state.current_monster_id else (150, 150, 100)
            rect = pygame.Rect(px, py, self.config.cell_width * 2, self.config.cell_height)
            pygame.draw.rect(self.screen, color, rect)

    def cleanup(self):
        """Cleanup pygame resources."""
        pygame.quit()


# =============================================================================
# Input Handler
# =============================================================================

class InputHandler:
    """Handle keyboard and mouse input."""

    # Key mappings for movement
    MOVE_KEYS = {
        pygame.K_UP: "up",
        pygame.K_DOWN: "down",
        pygame.K_LEFT: "left",
        pygame.K_RIGHT: "right",
        pygame.K_w: "up",
        pygame.K_s: "down",
        pygame.K_a: "left",
        pygame.K_d: "right",
    }

    def __init__(self):
        self.quit_requested = False

    def process_events(self) -> list:
        """Process pygame events and return list of intents."""
        intents = []

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.quit_requested = True

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.quit_requested = True

                elif event.key in self.MOVE_KEYS:
                    direction = self.MOVE_KEYS[event.key]
                    # Shift+move = push
                    mods = pygame.key.get_mods()
                    if mods & pygame.KMOD_SHIFT:
                        intents.append({"action": "push", "direction": direction})
                    else:
                        intents.append({"action": "move", "direction": direction})

                elif event.key == pygame.K_SPACE:
                    intents.append({"action": "interact"})

                elif event.key == pygame.K_r:
                    mods = pygame.key.get_mods()
                    if mods & pygame.KMOD_CTRL:
                        intents.append({"action": "stop_recording"})
                    else:
                        intents.append({"action": "start_recording"})

                elif event.key == pygame.K_p:
                    mods = pygame.key.get_mods()
                    if mods & pygame.KMOD_CTRL:
                        intents.append({"action": "stop_autorepeat"})
                    else:
                        intents.append({"action": "start_autorepeat"})

                elif event.key == pygame.K_h:
                    intents.append({"action": "hitch_wagon"})

                elif event.key == pygame.K_u:
                    intents.append({"action": "unhitch_wagon"})

                # Number keys for recipe selection
                elif pygame.K_1 <= event.key <= pygame.K_9:
                    recipe_index = event.key - pygame.K_1
                    intents.append({"action": "select_recipe", "recipe_index": recipe_index})

        return intents


# =============================================================================
# Main Game Loop
# =============================================================================

async def main():
    """Main game entry point."""
    print("=" * 50)
    print("  Monster Workshop - Client")
    print("=" * 50)

    # Initialize
    config = GameConfig()
    state = GameState()
    renderer = Renderer(config)
    input_handler = InputHandler()
    network = NetworkClient(config)

    if not renderer.init():
        print("Failed to initialize renderer")
        return

    # TODO: Implement login UI
    # For now, we just show the game loop structure
    print("\nGame client initialized!")
    print("Controls:")
    print("  Arrow keys / WASD: Move")
    print("  Shift + Move: Push")
    print("  Space: Interact")
    print("  R: Start recording")
    print("  Ctrl+R: Stop recording")
    print("  P: Start auto-repeat")
    print("  Ctrl+P: Stop auto-repeat")
    print("  H: Hitch wagon")
    print("  U: Unhitch wagon")
    print("  1-9: Select recipe")
    print("  ESC: Quit")
    print("")

    # Sample terrain for testing
    state.terrain = [
        ["#" if x == 0 or x == 59 or y == 0 or y == 19 else "." for x in range(60)]
        for y in range(20)
    ]

    # Main loop
    clock = pygame.time.Clock()
    running = True

    while running and not input_handler.quit_requested:
        # Process input
        intents = input_handler.process_events()

        # Send intents to server (when connected)
        for intent in intents:
            if state.connected:
                await network.send_intent(**intent)
            else:
                print(f"Intent (offline): {intent}")

        # Receive updates from server
        if state.connected:
            message = await network.receive()
            if message:
                # TODO: Process server messages
                pass

        # Render
        renderer.render(state)

        # Cap frame rate
        clock.tick(60)

    # Cleanup
    await network.disconnect()
    renderer.cleanup()
    print("\nGame closed.")


# =============================================================================
# Entry Point
# =============================================================================

if __name__ == "__main__":
    asyncio.run(main())
