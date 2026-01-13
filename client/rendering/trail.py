"""Movement trail rendering using Unicode box-drawing characters."""

from typing import List, Optional, Tuple

from config import (
    TRAIL_COLOR,
    TRAIL_HORIZONTAL,
    TRAIL_VERTICAL,
    TRAIL_CORNERS,
    TRAIL_ARROWS,
)


class TrailRenderer:
    """Renders the movement prediction trail using box-drawing characters."""

    def __init__(self, overlay_window):
        """Initialize the trail renderer.

        Args:
            overlay_window: The pyunicodegame window to render on.
        """
        self.overlay_window = overlay_window

    def render(self, trail_positions: List[Tuple[int, int, str, Optional[str], bool, bool]]):
        """Render the trail on the overlay window.

        Args:
            trail_positions: List of (x, y, incoming_dir, outgoing_dir, is_second_to_last, is_last)
                tuples from GameState.get_trail_positions()
        """
        for x, y, incoming_dir, outgoing_dir, is_second_to_last, is_last in trail_positions:
            char = self._get_trail_char(incoming_dir, outgoing_dir, is_second_to_last, is_last)
            self.overlay_window.put(x, y, char, TRAIL_COLOR)

    def _get_trail_char(
        self, incoming_dir: str, outgoing_dir: Optional[str], is_second_to_last: bool, is_last: bool
    ) -> str:
        """Determine which box-drawing character to use.

        Args:
            incoming_dir: Direction we moved to reach this cell
            outgoing_dir: Direction of next move (None if last)
            is_second_to_last: Whether this is the second-to-last step
            is_last: Whether this is the last step in the queue

        Returns:
            The appropriate Unicode character for this trail segment.
        """
        if is_last:
            # End of trail - use dot
            return "·"

        if outgoing_dir is None or incoming_dir == outgoing_dir:
            # Continuing straight
            if incoming_dir in ("left", "right"):
                return TRAIL_HORIZONTAL
            else:
                return TRAIL_VERTICAL

        # Corner - direction changes
        return TRAIL_CORNERS.get((incoming_dir, outgoing_dir), "·")
