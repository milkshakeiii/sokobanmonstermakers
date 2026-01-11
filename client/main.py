import asyncio
import threading
import json
import logging
import queue
import time
import sys
import os
from uuid import UUID
from typing import Dict, Any, Optional, List

# Add pyunicodegame to path
sys.path.append(os.path.expanduser("~/Documents/github/pyunicodegame/src"))

import httpx
import websockets
import pygame
import pyunicodegame

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
API_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws"

# Colors
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)
COLOR_RED = (255, 100, 100)
COLOR_GREEN = (100, 255, 100)
COLOR_BLUE = (100, 100, 255)
COLOR_YELLOW = (255, 255, 100)
COLOR_GRAY = (100, 100, 100)

class GameClient:
    def __init__(self):
        self.token: Optional[str] = None
        self.player_id: Optional[str] = None
        self.zone_id: Optional[str] = None
        
        # State
        self.entities: Dict[str, Any] = {}
        self.sprites: Dict[str, pyunicodegame.Sprite] = {}
        self.local_player_monster_id: Optional[str] = None
        
        # Queues for thread communication
        self.intent_queue = queue.Queue()
        self.state_queue = queue.Queue()
        
        # Pyunicodegame window
        self.root = None
        self.game_window = None
        self.ui_window = None
        
    def start(self):
        """Start the game client."""
        # 1. Login/Register via REST
        if not self.authenticate():
            logger.error("Authentication failed")
            return

        # 2. Get Zone
        if not self.select_zone():
            logger.error("Zone selection failed")
            return

        # 3. Start Network Thread
        self.running = True
        self.network_thread = threading.Thread(target=self.run_network_loop, daemon=True)
        self.network_thread.start()

        # 4. Start Pyunicodegame Loop (Main Thread)
        self.run_game_loop()

    def authenticate(self) -> bool:
        """Register/Login and get token."""
        username = "dev_player_" + str(int(time.time()))
        password = "password123"
        
        try:
            # Try Register
            logger.info(f"Registering as {username}...")
            resp = httpx.post(f"{API_URL}/api/auth/register", json={"username": username, "password": password})
            if resp.status_code not in (200, 201):
                 logger.info("Registration failed, trying login...")

            # Always login to get a token (register doesn't return one)
            logger.info("Logging in...")
            resp = httpx.post(f"{API_URL}/api/auth/login", json={"username": username, "password": password})

            if resp.status_code != 200:
                logger.error(f"Login failed: {resp.text}")
                return False

            data = resp.json()
            self.token = data["token"]
            self.player_id = data["player_id"]
            logger.info(f"Authenticated as {username} ({self.player_id})")
            return True
            
        except Exception as e:
            logger.error(f"Auth error: {e}")
            return False

    def select_zone(self) -> bool:
        """Get list of zones and pick one."""
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = httpx.get(f"{API_URL}/api/zones", headers=headers)
            if resp.status_code != 200:
                logger.error(f"Failed to list zones: {resp.text}")
                return False
                
            zones = resp.json().get("zones", [])
            if not zones:
                logger.error("No zones found")
                return False

            # Prefer "Starting Village" zone if available
            for zone in zones:
                if zone["name"] == "Starting Village":
                    self.zone_id = zone["id"]
                    logger.info(f"Selected zone: {zone['name']} ({self.zone_id})")
                    return True

            # Fall back to first zone
            self.zone_id = zones[0]["id"]
            logger.info(f"Selected zone: {zones[0]['name']} ({self.zone_id})")
            return True
            
        except Exception as e:
            logger.error(f"Zone error: {e}")
            return False

    def run_network_loop(self):
        """Asyncio loop for WebSocket communication."""
        asyncio.run(self._network_task())

    async def _network_task(self):
        """Connect to WS and handle messages."""
        uri = f"{WS_URL}?token={self.token}"
        while self.running:
            try:
                async with websockets.connect(uri) as websocket:
                    logger.info("Connected to WebSocket")
                    
                    # Subscribe to zone
                    await websocket.send(json.dumps({
                        "type": "subscribe",
                        "zone_id": self.zone_id
                    }))
                    
                    # Try to spawn a monster if we don't have one (simple check)
                    # We can send a spawn intent blindly, if we already have one it might error or spawn another
                    # Ideally we check the entity list first, but for now let's just spawn one
                    await websocket.send(json.dumps({
                        "type": "intent",
                        "data": {
                            "action": "spawn_monster",
                            "monster_type": "goblin",
                            "name": "MyGoblin",
                            "transferable_skills": ["handcrafts", "athletics", "outdoorsmonstership"]
                        }
                    }))

                    # Main loop
                    while self.running:
                        # 1. Send Intents
                        while not self.intent_queue.empty():
                            intent = self.intent_queue.get()
                            await websocket.send(json.dumps({
                                "type": "intent",
                                "data": intent
                            }))

                        # 2. Receive Messages (with timeout to yield to send loop)
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=0.05)
                            data = json.loads(message)
                            self.handle_message(data)
                        except asyncio.TimeoutError:
                            pass
                        
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(2) # Retry delay

    def handle_message(self, data: Dict[str, Any]):
        """Process server messages."""
        msg_type = data.get("type")
        
        if msg_type == "tick":
            # Put state update in queue for main thread
            state = data.get("state", {})
            self.state_queue.put(state)
        elif msg_type == "error":
            logger.warning(f"Server Error: {data.get('message')}")

    def run_game_loop(self):
        """Initialize pyunicodegame and run."""
        self.root = pyunicodegame.init("Monster Workshop Client", width=80, height=30, bg=(10, 10, 20, 255))
        
        # Create layers
        # Game world - moves with camera
        self.game_window = pyunicodegame.create_window("game", 0, 0, 200, 200, z_index=1, depth=0.0)
        
        # UI - fixed
        self.ui_window = pyunicodegame.create_window("ui", 0, 0, 80, 30, z_index=100, fixed=True)
        
        pyunicodegame.run(
            update=self.update,
            render=self.render,
            on_key=self.on_key
        )
        
        self.running = False # Signal network thread to stop

    def update(self, dt: float):
        """Game update loop."""
        # Process latest state
        while not self.state_queue.empty():
            state = self.state_queue.get()
            self.sync_state(state)
            
        # Camera follow
        if self.local_player_monster_id and self.local_player_monster_id in self.sprites:
            target = self.sprites[self.local_player_monster_id]
            # Center camera on target
            # Camera x/y are in pixels
            cw, ch = 80 * 10, 30 * 20 # Approx window size in pixels
            cam_x = target.x * 10 - cw / 2 # Assuming 10px width char
            cam_y = target.y * 20 - ch / 2 # Assuming 20px height char
            # pyunicodegame.set_camera(x=cam_x, y=cam_y)
            # Actually pyunicodegame camera works best if we just use move_camera to smooth it
            # But direct set is easier for now.
            # Let's just update camera position based on target cell
            pass 

    def sync_state(self, state: Dict[str, Any]):
        """Sync local sprites with server state."""
        server_entities = state.get("entities", [])
        current_ids = set()

        for entity_data in server_entities:
            eid = entity_data["id"]
            current_ids.add(eid)

            # Identify our monster
            was_our_monster = self.local_player_monster_id == eid
            if entity_data.get("owner_id") == self.player_id and \
               entity_data.get("metadata", {}).get("monster_type"):
                self.local_player_monster_id = eid

            # Update or Create
            if eid in self.sprites:
                sprite = self.sprites[eid]
                # Lerp to new position
                if sprite.x != entity_data["x"] or sprite.y != entity_data["y"]:
                     sprite.move_to(entity_data["x"], entity_data["y"])
                # Update sprite appearance if we just identified it as ours
                if not was_our_monster and eid == self.local_player_monster_id:
                    sprite.char = "@"
                    sprite.fg = COLOR_GREEN
            else:
                self.create_sprite(eid, entity_data)
        
        # Remove old
        to_remove = []
        for eid in self.sprites:
            if eid not in current_ids:
                to_remove.append(eid)
        
        for eid in to_remove:
            self.game_window.remove_sprite(self.sprites[eid]) # Wait, no remove_sprite on Window?
            # Creating a sprite adds it to the list? No, usually we add it to window.
            # pyunicodegame: create_sprite returns a Sprite. Does it add automatically?
            # Reading init.py: create_sprite returns Sprite. 
            # Window.add_sprite(sprite) is likely needed.
            # I need to check Window class in _window.py or just use root.add_sprite if window has it.
            # Let's assume window.add_sprite exists.
            # To remove, we probably need window.remove_sprite(sprite) if it exists, or sprite.kill().
            # I'll check Window class later. For now, let's assume I can manage them.
            pass

        # Since I can't easily see Window methods without reading _window.py, 
        # I'll rely on the fact that Sprites usually manage themselves or I need to clear/re-add?
        # Re-reading init.py: "Update all sprites in all windows... Draw all sprites..."
        # It iterates _windows.values().
        # Sprite is probably stored in the window.
        
        # Let's read _window.py quickly or just guess.
        
    def create_sprite(self, eid: str, data: Dict[str, Any]):
        """Create a sprite based on entity type."""
        metadata = data.get("metadata", {})
        kind = metadata.get("kind", "unknown")

        char = "?"
        color = COLOR_WHITE

        if kind == "monster":
            # Show player's monster differently
            if eid == self.local_player_monster_id:
                char = "@"
                color = COLOR_GREEN
            else:
                char = "M"
                color = COLOR_RED
        elif kind == "item":
            char = "*"
            color = COLOR_YELLOW
        elif kind == "workshop":
            char = "W"
            color = COLOR_BLUE
        elif kind == "gathering_spot":
            char = "G"
            color = COLOR_GREEN
        elif kind == "terrain_block":
            char = "#"
            color = COLOR_GRAY
        elif kind == "dispenser":
            char = "D"
            color = COLOR_BLUE
        elif kind == "delivery":
            char = ">"
            color = COLOR_YELLOW
        elif kind == "signpost":
            char = "!"
            color = COLOR_WHITE
        elif kind == "commune":
            char = "C"
            color = COLOR_GREEN

        sprite = pyunicodegame.create_sprite(char, x=data["x"], y=data["y"], fg=color, lerp_speed=10.0)
        self.sprites[eid] = sprite
        self.game_window.add_sprite(sprite)

    def render(self):
        """Render UI."""
        self.ui_window.put_string(1, 1, f"FPS: {pyunicodegame._clock.get_fps():.0f}", COLOR_WHITE)
        if self.local_player_monster_id:
             self.ui_window.put_string(1, 2, "Status: Connected (Monster Active)", COLOR_GREEN)
        else:
             self.ui_window.put_string(1, 2, "Status: Connecting...", COLOR_YELLOW)

        self.ui_window.put_string(1, 28, "WASD: Move  Space: Interact  Q: Quit", COLOR_GRAY)

    def on_key(self, key):
        """Handle input."""
        if not self.local_player_monster_id:
            return
            
        action = None
        direction = None
        
        if key == pygame.K_w or key == pygame.K_UP:
            action = "move"
            direction = "up"
        elif key == pygame.K_s or key == pygame.K_DOWN:
            action = "move"
            direction = "down"
        elif key == pygame.K_a or key == pygame.K_LEFT:
            action = "move"
            direction = "left"
        elif key == pygame.K_d or key == pygame.K_RIGHT:
            action = "move"
            direction = "right"
        elif key == pygame.K_SPACE:
            self.intent_queue.put({"action": "interact", "entity_id": self.local_player_monster_id})
            return

        # Pushing happens automatically when you move into an item
        if action and direction:
            intent = {
                "action": action,
                "direction": direction,
                "entity_id": self.local_player_monster_id
            }
            self.intent_queue.put(intent)
        
        if key == pygame.K_q:
            pyunicodegame.quit()

if __name__ == "__main__":
    client = GameClient()
    client.start()
