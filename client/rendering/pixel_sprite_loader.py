"""Pixel sprite loader for item sprites with color inheritance."""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pygame


# Path to item sprite assets
ASSETS_DIR = Path(__file__).parent / "assets" / "items"

# Cell size constants (pixels per game cell)
CELL_WIDTH = 10
CELL_HEIGHT = 20


class PixelSpriteLoader:
    """Loads and caches pixel sprites with color transformation support."""

    def __init__(self):
        self._metadata: Dict[str, Dict[str, Any]] = {}
        self._surfaces: Dict[str, pygame.Surface] = {}
        self._colored_cache: Dict[Tuple[str, Tuple[int, int, int]], pygame.Surface] = {}
        self._loaded = False

    def load_all(self) -> None:
        """Load all sprite PNG and JSON metadata files."""
        if self._loaded:
            return

        if not ASSETS_DIR.exists():
            return

        for json_path in ASSETS_DIR.glob("*.json"):
            sprite_name = json_path.stem
            png_path = ASSETS_DIR / f"{sprite_name}.png"

            # Load metadata
            try:
                with open(json_path) as f:
                    meta = json.load(f)
                self._metadata[sprite_name] = meta
            except (json.JSONDecodeError, OSError):
                continue

            # Load PNG surface
            if png_path.exists():
                try:
                    surface = pygame.image.load(str(png_path)).convert_alpha()
                    self._surfaces[sprite_name] = surface
                except pygame.error:
                    continue

        self._loaded = True

    def get_sprite_info(self, sprite_name: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a sprite."""
        self.load_all()
        return self._metadata.get(sprite_name)

    def get_sprite_dimensions(self, sprite_name: str) -> Tuple[int, int]:
        """Get sprite dimensions in cells (width_cells, height_cells)."""
        self.load_all()
        surface = self._surfaces.get(sprite_name)
        if surface is None:
            return (2, 1)  # Default item size

        w_pixels, h_pixels = surface.get_size()
        w_cells = max(1, w_pixels // CELL_WIDTH)
        h_cells = max(1, h_pixels // CELL_HEIGHT)
        return (w_cells, h_cells)

    def get_sprite_surface(
        self,
        sprite_name: str,
        effective_color: Optional[Tuple[int, int, int]] = None,
    ) -> Optional[pygame.Surface]:
        """Get a sprite surface, optionally color-transformed.

        Args:
            sprite_name: Name of the sprite (filename without extension)
            effective_color: RGB color for grey multiplication (for takers)

        Returns:
            pygame Surface or None if sprite not found
        """
        self.load_all()

        base_surface = self._surfaces.get(sprite_name)
        if base_surface is None:
            return None

        # Check if this sprite needs color transformation
        meta = self._metadata.get(sprite_name, {})
        color_role = meta.get("color_role")

        # If no color transformation needed, return base surface
        if color_role != "taker" or effective_color is None:
            return base_surface

        # Check cache
        cache_key = (sprite_name, tuple(effective_color))
        if cache_key in self._colored_cache:
            return self._colored_cache[cache_key]

        # Apply grey multiplication coloring
        colored = self._apply_grey_multiplication(base_surface, effective_color)
        self._colored_cache[cache_key] = colored
        return colored

    def _apply_grey_multiplication(
        self,
        surface: pygame.Surface,
        color: Tuple[int, int, int],
    ) -> pygame.Surface:
        """Apply grey multiplication coloring to a surface.

        Finds pixels where R == G == B (perfect grey) and multiplies
        the grey value by the target color.

        Args:
            surface: Source surface
            color: Target RGB color

        Returns:
            New surface with color transformation applied
        """
        # Create a copy of the surface
        result = surface.copy()
        width, height = result.get_size()

        # Lock surface for pixel access
        result.lock()

        for y in range(height):
            for x in range(width):
                r, g, b, a = result.get_at((x, y))

                # Check if pixel is grey (R == G == B)
                if r == g == b and a > 0:
                    # Grey value (0-255)
                    grey = r

                    # Multiply grey by color and normalize
                    new_r = min(255, (grey * color[0]) // 255)
                    new_g = min(255, (grey * color[1]) // 255)
                    new_b = min(255, (grey * color[2]) // 255)

                    result.set_at((x, y), (new_r, new_g, new_b, a))

        result.unlock()
        return result

    def has_sprite(self, sprite_name: str) -> bool:
        """Check if a sprite exists."""
        self.load_all()
        return sprite_name in self._surfaces

    def get_all_sprite_names(self) -> list:
        """Get list of all available sprite names."""
        self.load_all()
        return list(self._surfaces.keys())

    def clear_color_cache(self) -> None:
        """Clear the colored sprite cache."""
        self._colored_cache.clear()


# Global singleton instance
_loader: Optional[PixelSpriteLoader] = None


def get_loader() -> PixelSpriteLoader:
    """Get the global pixel sprite loader instance."""
    global _loader
    if _loader is None:
        _loader = PixelSpriteLoader()
    return _loader


def get_item_sprite(
    good_type: str,
    effective_color: Optional[Tuple[int, int, int]] = None,
) -> Tuple[Optional[pygame.Surface], int, int]:
    """Get an item sprite by good_type with optional color transformation.

    Args:
        good_type: The item's good_type (e.g. "cotton_bolls", "fabric")
        effective_color: RGB color for taker items

    Returns:
        Tuple of (surface, width_cells, height_cells)
        Returns (None, 2, 1) if sprite not found
    """
    loader = get_loader()

    # Convert good_type to sprite name (replace spaces with underscores)
    sprite_name = good_type.lower().replace(" ", "_")

    surface = loader.get_sprite_surface(sprite_name, effective_color)
    if surface is None:
        return (None, 2, 1)

    w_cells, h_cells = loader.get_sprite_dimensions(sprite_name)
    return (surface, w_cells, h_cells)


def good_type_to_sprite_name(good_type: str) -> str:
    """Convert a good_type to its sprite name."""
    return good_type.lower().replace(" ", "_")


def has_pixel_sprite(good_type: str) -> bool:
    """Check if a pixel sprite exists for the given good_type."""
    loader = get_loader()
    sprite_name = good_type_to_sprite_name(good_type)
    return loader.has_sprite(sprite_name)
