"""WebSocket client for communicating with the game server."""

import asyncio
import json
import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import httpx
import websockets

from config import API_URL, WS_URL

logger = logging.getLogger(__name__)


class NetworkClient:
    """Handles all network communication with the game server."""

    def __init__(self):
        self.token: Optional[str] = None
        self.player_id: Optional[str] = None
        self.zone_id: Optional[str] = None

        # Thread communication queues
        self.intent_queue: queue.Queue = queue.Queue()
        self.state_queue: queue.Queue = queue.Queue()
        self.event_queue: queue.Queue = queue.Queue()

        # Network thread
        self._running = False
        self._network_thread: Optional[threading.Thread] = None

        # Callbacks
        self._on_state_update: Optional[Callable[[Dict], None]] = None
        self._on_event: Optional[Callable[[Dict], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None

    def set_callbacks(
        self,
        on_state_update: Optional[Callable[[Dict], None]] = None,
        on_event: Optional[Callable[[Dict], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        """Set callback functions for network events."""
        self._on_state_update = on_state_update
        self._on_event = on_event
        self._on_error = on_error

    def authenticate(self, username: Optional[str] = None) -> bool:
        """Register/Login and get authentication token.

        Args:
            username: Optional username. If not provided, generates a unique one.

        Returns:
            True if authentication successful, False otherwise.
        """
        if username is None:
            username = f"dev_player_{int(time.time())}"
        password = "password123"

        try:
            # Try to register first
            logger.info(f"Registering as {username}...")
            resp = httpx.post(
                f"{API_URL}/api/auth/register",
                json={"username": username, "password": password},
            )
            if resp.status_code not in (200, 201):
                logger.info("Registration failed or user exists, trying login...")

            # Always login to get token
            logger.info("Logging in...")
            resp = httpx.post(
                f"{API_URL}/api/auth/login",
                json={"username": username, "password": password},
            )

            if resp.status_code != 200:
                logger.error(f"Login failed: {resp.text}")
                return False

            data = resp.json()
            self.token = data["token"]
            self.player_id = data["player_id"]
            logger.info(f"Authenticated as {username} ({self.player_id})")
            return True

        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False

    def get_zones(self) -> List[Dict[str, Any]]:
        """Get list of available zones.

        Returns:
            List of zone dictionaries with 'id' and 'name' keys.
        """
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = httpx.get(f"{API_URL}/api/zones", headers=headers)
            if resp.status_code != 200:
                logger.error(f"Failed to list zones: {resp.text}")
                return []

            return resp.json().get("zones", [])

        except Exception as e:
            logger.error(f"Zone list error: {e}")
            return []

    def select_zone(self, zone_name: Optional[str] = "Starting Village") -> bool:
        """Select a zone to join.

        Args:
            zone_name: Name of zone to join. Defaults to 'Starting Village'.

        Returns:
            True if zone selected, False otherwise.
        """
        zones = self.get_zones()
        if not zones:
            logger.error("No zones available")
            return False

        # Try to find requested zone
        for zone in zones:
            if zone["name"] == zone_name:
                self.zone_id = zone["id"]
                logger.info(f"Selected zone: {zone['name']} ({self.zone_id})")
                return True

        # Fall back to first zone
        self.zone_id = zones[0]["id"]
        logger.info(f"Selected zone: {zones[0]['name']} ({self.zone_id})")
        return True

    def start(self):
        """Start the network thread."""
        if self._running:
            return

        self._running = True
        self._network_thread = threading.Thread(target=self._run_network_loop, daemon=True)
        self._network_thread.start()

    def stop(self):
        """Stop the network thread."""
        self._running = False
        if self._network_thread:
            self._network_thread.join(timeout=2.0)
            self._network_thread = None

    def send_intent(self, action: str, **kwargs):
        """Send an intent to the server.

        Args:
            action: The action type (e.g., 'move', 'interact', 'spawn_monster')
            **kwargs: Additional parameters for the intent
        """
        intent = {"action": action, **kwargs}
        self.intent_queue.put(intent)

    def send_move(self, direction: str, entity_id: str):
        """Send a move intent."""
        self.send_intent("move", direction=direction, entity_id=entity_id)

    def send_interact(self, entity_id: str):
        """Send an interact intent."""
        self.send_intent("interact", entity_id=entity_id)

    def send_spawn_monster(
        self,
        monster_type: str,
        name: str,
        transferable_skills: List[str],
    ):
        """Send a spawn monster intent."""
        self.send_intent(
            "spawn_monster",
            monster_type=monster_type,
            name=name,
            transferable_skills=transferable_skills,
        )

    def send_recording_start(self):
        """Start recording actions."""
        self.send_intent("recording_start")

    def send_recording_stop(self):
        """Stop recording actions."""
        self.send_intent("recording_stop")

    def send_autorepeat_start(self):
        """Start playing back recorded actions."""
        self.send_intent("autorepeat_start")

    def send_autorepeat_stop(self):
        """Stop playing back recorded actions."""
        self.send_intent("autorepeat_stop")

    def send_select_recipe(
        self,
        workshop_id: str,
        recipe_id: str,
        monster_id: Optional[str] = None,
    ):
        """Select a recipe for a workshop."""
        intent_data = {
            "workshop_id": workshop_id,
            "recipe_id": recipe_id,
        }
        if monster_id:
            intent_data["monster_id"] = monster_id
        self.send_intent("select_recipe", **intent_data)

    def send_hitch_wagon(self):
        """Hitch to an adjacent wagon."""
        self.send_intent("hitch_wagon")

    def send_unhitch_wagon(self):
        """Unhitch from current wagon."""
        self.send_intent("unhitch_wagon")

    def send_unload_wagon(self):
        """Unload an item from the hitched wagon."""
        self.send_intent("unload_wagon")

    def send_clear_path(self, entity_id: str):
        """Clear the movement queue."""
        self.send_intent("clear_movement", entity_id=entity_id)

    def get_latest_state(self) -> Optional[Dict]:
        """Get the most recent state update, if any.

        Returns:
            The latest state dict, or None if no updates available.
        """
        latest = None
        while not self.state_queue.empty():
            try:
                latest = self.state_queue.get_nowait()
            except queue.Empty:
                break
        return latest

    def get_events(self) -> List[Dict]:
        """Get all pending events.

        Returns:
            List of event dictionaries.
        """
        events = []
        while not self.event_queue.empty():
            try:
                events.append(self.event_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def _run_network_loop(self):
        """Run the asyncio network loop in the background thread."""
        asyncio.run(self._network_task())

    async def _network_task(self):
        """Main WebSocket communication task."""
        uri = f"{WS_URL}?token={self.token}"

        while self._running:
            try:
                async with websockets.connect(uri) as websocket:
                    logger.info("Connected to WebSocket")

                    # Subscribe to zone
                    await websocket.send(
                        json.dumps({"type": "subscribe", "zone_id": self.zone_id})
                    )

                    # Main communication loop
                    while self._running:
                        # Send pending intents
                        while not self.intent_queue.empty():
                            try:
                                intent = self.intent_queue.get_nowait()
                                await websocket.send(
                                    json.dumps({"type": "intent", "data": intent})
                                )
                            except queue.Empty:
                                break

                        # Receive messages with timeout
                        try:
                            message = await asyncio.wait_for(
                                websocket.recv(), timeout=0.05
                            )
                            self._handle_message(json.loads(message))
                        except asyncio.TimeoutError:
                            pass

            except websockets.ConnectionClosed:
                logger.warning("WebSocket connection closed")
                if self._running:
                    await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                if self._running:
                    await asyncio.sleep(2)

    def _handle_message(self, data: Dict[str, Any]):
        """Process a message from the server."""
        msg_type = data.get("type")

        if msg_type == "tick":
            state = data.get("state", {})
            self.state_queue.put(state)

            # Extract and queue events
            events = state.get("events", [])
            for event in events:
                # Only queue events targeted at this player
                target = event.get("target_player_id")
                if target is None or target == self.player_id:
                    self.event_queue.put(event)

        elif msg_type == "error":
            error_msg = data.get("message", "Unknown error")
            logger.warning(f"Server error: {error_msg}")
            self.event_queue.put({"type": "error", "message": error_msg})
