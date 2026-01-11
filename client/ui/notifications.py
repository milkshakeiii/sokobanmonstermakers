"""Notification system for displaying event messages."""

import time
from typing import List, Optional, Tuple

from config import Color, NOTIFICATION_DURATION, NOTIFICATION_HEIGHT


class Notification:
    """A single notification message."""

    def __init__(self, text: str, color: Tuple[int, int, int], duration: float = NOTIFICATION_DURATION):
        self.text = text
        self.color = color
        self.created = time.time()
        self.duration = duration

    @property
    def age(self) -> float:
        """Time since creation in seconds."""
        return time.time() - self.created

    @property
    def is_expired(self) -> bool:
        """Check if notification should be removed."""
        return self.age >= self.duration

    @property
    def alpha_factor(self) -> float:
        """Get alpha factor for fading (0.0 to 1.0)."""
        remaining = self.duration - self.age
        if remaining <= 1.0:
            return max(0.0, remaining)
        return 1.0

    def get_faded_color(self) -> Tuple[int, int, int]:
        """Get color with fade applied."""
        factor = self.alpha_factor
        return tuple(int(c * factor) for c in self.color)


class NotificationManager:
    """Manages notification display and lifecycle."""

    def __init__(self, window, max_messages: int = 3):
        """Initialize the notification manager.

        Args:
            window: pyunicodegame window for notifications
            max_messages: Maximum notifications to display at once
        """
        self.window = window
        self.max_messages = max_messages
        self.notifications: List[Notification] = []

    def add(self, text: str, color: Tuple[int, int, int] = Color.TEXT_PRIMARY):
        """Add a notification message.

        Args:
            text: Message text
            color: Message color
        """
        notification = Notification(text, color)
        self.notifications.append(notification)

        # Remove oldest if over limit
        while len(self.notifications) > self.max_messages:
            self.notifications.pop(0)

    def add_success(self, text: str):
        """Add a success notification."""
        self.add(text, Color.SUCCESS)

    def add_error(self, text: str):
        """Add an error notification."""
        self.add(text, Color.ERROR)

    def add_warning(self, text: str):
        """Add a warning notification."""
        self.add(text, Color.WARNING)

    def add_info(self, text: str):
        """Add an info notification."""
        self.add(text, Color.INFO)

    def update(self):
        """Remove expired notifications."""
        self.notifications = [n for n in self.notifications if not n.is_expired]

    def render(self):
        """Render all active notifications."""
        self.update()

        # Clear the notification area
        for y in range(NOTIFICATION_HEIGHT):
            self.window.put_string(0, y, " " * 100, Color.TEXT_PRIMARY)

        # Draw notifications
        for i, notification in enumerate(self.notifications):
            if i >= NOTIFICATION_HEIGHT:
                break

            color = notification.get_faded_color()
            self.window.put_string(1, i, notification.text, color)

    def handle_event(self, event: dict):
        """Handle a game event and create appropriate notification.

        Args:
            event: Event dictionary from server
        """
        event_type = event.get("type", "")
        message = event.get("message", "")

        if event_type == "spawned":
            self.add_success(f"Spawned: {message}")

        elif event_type == "error":
            self.add_error(f"Error: {message}")

        elif event_type == "push":
            pass  # Silent, visual feedback handles this

        elif event_type == "blocked":
            self.add_warning("Blocked!")

        elif event_type == "recording_started":
            self.add_warning("Recording started")

        elif event_type == "recording_stopped":
            self.add_info("Recording stopped")

        elif event_type == "autorepeat_started":
            self.add_success("Playback started")

        elif event_type == "autorepeat_stopped":
            self.add_info("Playback stopped")

        elif event_type == "crafting_started":
            recipe = event.get("recipe_id", "item")
            self.add_success(f"Crafting: {recipe}")

        elif event_type == "crafting_blocked":
            self.add_warning("Crafting blocked - missing inputs")

        elif event_type == "wagon_hitched":
            self.add_info("Wagon hitched")

        elif event_type == "wagon_unhitched":
            self.add_info("Wagon unhitched")

        elif event_type == "item_unloaded":
            self.add_info("Item unloaded from wagon")

        elif event_type == "interact":
            pass  # Context panel handles this

        elif event_type == "message":
            if message:
                self.add_info(message)

    def clear(self):
        """Clear all notifications."""
        self.notifications.clear()


class SpeechBubble:
    """A speech bubble for tutorial hints."""

    def __init__(self, text: str, target_x: int, target_y: int, duration: float = 5.0):
        """Initialize a speech bubble.

        Args:
            text: Bubble text content
            target_x: X position of target entity
            target_y: Y position of target entity
            duration: How long to display
        """
        self.text = text
        self.target_x = target_x
        self.target_y = target_y
        self.created = time.time()
        self.duration = duration

        # Wrap text
        self.lines = self._wrap_text(text, max_width=22)

    def _wrap_text(self, text: str, max_width: int) -> List[str]:
        """Wrap text to fit width."""
        words = text.split()
        lines = []
        current_line = []
        current_length = 0

        for word in words:
            if current_length + len(word) + 1 <= max_width:
                current_line.append(word)
                current_length += len(word) + 1
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
                current_length = len(word)

        if current_line:
            lines.append(" ".join(current_line))

        return lines

    @property
    def is_expired(self) -> bool:
        """Check if bubble should be removed."""
        return time.time() - self.created >= self.duration

    def render(self, window, offset_x: int = 0, offset_y: int = 0):
        """Render the speech bubble.

        Args:
            window: pyunicodegame window
            offset_x: Camera X offset
            offset_y: Camera Y offset
        """
        # Calculate screen position
        screen_x = self.target_x - offset_x
        screen_y = self.target_y - offset_y - len(self.lines) - 3

        if screen_x < 0 or screen_y < 0:
            return

        width = max(len(line) for line in self.lines) + 2
        color = Color.BUBBLE_BORDER

        # Top border
        window.put_string(screen_x, screen_y, "." + "-" * width + ".", color)

        # Content
        for i, line in enumerate(self.lines):
            padded = line.ljust(width - 2)
            window.put_string(screen_x, screen_y + 1 + i, f"( {padded} )", color)

        # Bottom border
        window.put_string(screen_x, screen_y + len(self.lines) + 1, "`" + "-" * width + "'", color)

        # Pointer
        pointer_x = screen_x + width // 2
        window.put_string(pointer_x, screen_y + len(self.lines) + 2, "\\/", color)


class TutorialManager:
    """Manages tutorial speech bubbles."""

    def __init__(self, game_window):
        """Initialize the tutorial manager.

        Args:
            game_window: pyunicodegame window for bubbles
        """
        self.game_window = game_window
        self.shown_hints: set = set()
        self.active_bubble: Optional[SpeechBubble] = None
        self.active_text: Optional[str] = None

    def check_facing_entity(self, facing_entity: Optional[dict], game_state):
        """Check if a tutorial bubble should be shown.

        Args:
            facing_entity: Entity the player is facing
            game_state: Current game state
        """
        if facing_entity is None:
            return

        if self.active_bubble and not self.active_bubble.is_expired:
            return

        metadata = facing_entity.get("metadata", {})
        kind = metadata.get("kind")
        x = facing_entity.get("x", 0)
        y = facing_entity.get("y", 0)

        # Check triggers
        if kind == "item" and "push" not in self.shown_hints:
            if not game_state.player_has_pushed:
                self.show_bubble("Push items by walking into them", x, y)
                self.shown_hints.add("push")

        elif kind == "workshop" and "workshop" not in self.shown_hints:
            if not metadata.get("selected_recipe_id"):
                self.show_bubble("Press [C] to select a crafting recipe", x, y)
                self.shown_hints.add("workshop")

        elif kind == "gathering_spot" and "gathering" not in self.shown_hints:
            self.show_bubble("Gathering spots produce raw materials. Press [C] to start.", x, y)
            self.shown_hints.add("gathering")

        elif kind == "wagon" and "wagon" not in self.shown_hints:
            if not metadata.get("hitched_by"):
                self.show_bubble("Press [H] to hitch wagon for hauling", x, y)
                self.shown_hints.add("wagon")

        elif kind == "wagon" and "wagon_unload" not in self.shown_hints:
            if metadata.get("loaded_item_ids"):
                self.show_bubble("Press [U] to unload items", x, y)
                self.shown_hints.add("wagon_unload")

        elif kind == "dispenser" and "dispenser" not in self.shown_hints:
            self.show_bubble("Dispensers store items of one type", x, y)
            self.shown_hints.add("dispenser")

        elif kind == "delivery" and "delivery" not in self.shown_hints:
            self.show_bubble("Deliver finished goods here", x, y)
            self.shown_hints.add("delivery")

        elif kind == "signpost" and "signpost" not in self.shown_hints:
            self.show_bubble("Press [Space] to travel to another area", x, y)
            self.shown_hints.add("signpost")

    def show_bubble(self, text: str, x: int, y: int):
        """Show a speech bubble."""
        self.active_bubble = SpeechBubble(text, x, y)
        self.active_text = text

    def update(self):
        """Update tutorial state."""
        if self.active_bubble and self.active_bubble.is_expired:
            self.active_bubble = None
            self.active_text = None

    def render(self, camera_x: int = 0, camera_y: int = 0):
        """Render active speech bubble on game window."""
        self.update()
        if self.active_bubble:
            self.active_bubble.render(self.game_window, camera_x, camera_y)

    def render_near_player(self, window, player_x: int, player_y: int):
        """Render tutorial bubble near the player in world coordinates.

        Args:
            window: Game window to render on
            player_x: Player's world X position
            player_y: Player's world Y position
        """
        self.update()
        if not self.active_text:
            return

        lines = self.active_bubble.lines if self.active_bubble else [self.active_text]

        # Position bubble above and to the right of player in world coords
        bubble_x = player_x + 2
        bubble_y = max(0, player_y - len(lines) - 3)

        # Draw speech bubble
        width = max(len(line) for line in lines) + 2
        color = Color.BUBBLE_BORDER

        # Top border
        window.put_string(bubble_x, bubble_y, "." + "-" * width + ".", color)

        # Content lines
        for i, line in enumerate(lines):
            padded = line.ljust(width - 2)
            window.put_string(bubble_x, bubble_y + 1 + i, f"( {padded} )", color)

        # Bottom border with pointer
        window.put_string(bubble_x, bubble_y + len(lines) + 1, "`" + "-" * width + "'", color)
        window.put_string(bubble_x, bubble_y + len(lines) + 2, " \\/", color)

    def dismiss(self):
        """Dismiss the current bubble."""
        self.active_bubble = None
        self.active_text = None

    def reset(self):
        """Reset all shown hints."""
        self.shown_hints.clear()
        self.active_bubble = None
        self.active_text = None
