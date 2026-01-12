"""Configuration constants for Monster Workshop client."""

from enum import Enum, auto
from dataclasses import dataclass
from typing import Dict, Tuple
import pygame

# Server Configuration
API_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws"

# Window Layout (in cells)
SCREEN_WIDTH = 100
SCREEN_HEIGHT = 35

# Panel dimensions
PANEL_WIDTH = 24
MONSTER_PANEL_HEIGHT = 12
CONTEXT_PANEL_HEIGHT = 20
NOTIFICATION_HEIGHT = 3
GAME_AREA_WIDTH = SCREEN_WIDTH - PANEL_WIDTH  # 76

# Panel positions
MONSTER_PANEL_X, MONSTER_PANEL_Y = 0, 0
CONTEXT_PANEL_X, CONTEXT_PANEL_Y = 0, MONSTER_PANEL_HEIGHT
NOTIFICATION_X, NOTIFICATION_Y = 0, SCREEN_HEIGHT - NOTIFICATION_HEIGHT
GAME_AREA_X, GAME_AREA_Y = PANEL_WIDTH, 0

# Game world size (larger than visible for scrolling)
GAME_WORLD_WIDTH = 80
GAME_WORLD_HEIGHT = 40


class Color:
    """Color palette for the game."""
    # Basic colors
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)
    GRAY = (128, 128, 128)
    DARK_GRAY = (80, 80, 80)
    LIGHT_GRAY = (200, 200, 200)

    # UI colors
    PANEL_BG_MONSTER = (20, 25, 35, 240)
    PANEL_BG_CONTEXT = (25, 20, 35, 240)
    PANEL_BG_NOTIFY = (15, 15, 25, 200)
    PANEL_BORDER = (60, 70, 90)

    # Text colors
    TEXT_PRIMARY = (255, 255, 255)
    TEXT_SECONDARY = (180, 180, 180)
    TEXT_MUTED = (120, 120, 120)
    TEXT_HIGHLIGHT = (255, 255, 100)

    # Status colors
    SUCCESS = (100, 255, 100)
    ERROR = (255, 100, 100)
    WARNING = (255, 200, 100)
    INFO = (100, 200, 255)

    # Monster colors (player)
    PLAYER_CYCLOPS = (100, 255, 100)
    PLAYER_ELF = (100, 255, 255)
    PLAYER_GOBLIN = (150, 255, 100)
    PLAYER_ORC = (255, 255, 100)
    PLAYER_TROLL = (255, 255, 255)

    # Monster colors (other)
    OTHER_CYCLOPS = (255, 100, 100)
    OTHER_ELF = (255, 100, 255)
    OTHER_GOBLIN = (255, 150, 50)
    OTHER_ORC = (180, 100, 50)
    OTHER_TROLL = (150, 150, 150)

    # Item colors
    ITEM_COTTON = (245, 245, 245)
    ITEM_SILK = (255, 215, 0)
    ITEM_STALKS = (139, 119, 101)
    ITEM_GRAIN = (218, 165, 32)
    ITEM_THREAD = (255, 255, 240)
    ITEM_FABRIC = (245, 245, 220)
    ITEM_FLOUR = (255, 248, 220)
    ITEM_SUGAR = (255, 255, 255)
    ITEM_CLAY_RED = (178, 34, 34)
    ITEM_CLAY_YELLOW = (218, 165, 32)
    ITEM_CLAY_BLUE = (70, 130, 180)
    ITEM_CLAY_WHITE = (245, 245, 245)
    ITEM_CLAY_BLACK = (50, 50, 50)
    ITEM_BRICK = (178, 34, 34)
    ITEM_CERAMIC = (245, 222, 179)
    ITEM_METAL = (192, 192, 192)
    ITEM_TOOL = (169, 169, 169)
    ITEM_DEFAULT = (200, 200, 200)

    # Dye colors
    DYE_CRIMSON = (220, 20, 60)
    DYE_PINK = (255, 182, 193)
    DYE_PURPLE = (128, 0, 128)
    DYE_CANARY_YELLOW = (255, 239, 0)
    DYE_GOLDEN_YELLOW = (255, 215, 0)
    DYE_INDIGO = (75, 0, 130)
    DYE_TEA_BROWN = (139, 90, 43)
    DYE_DARK_GREEN = (0, 100, 0)
    DYE_BRIGHT_GREEN = (0, 255, 0)
    DYE_LIGHT_GREEN = (144, 238, 144)
    DYE_DEEP_SKY_BLUE = (0, 191, 255)
    DYE_EGGSHELL_BLUE = (176, 224, 230)
    DYE_BLACK = (32, 32, 32)
    DYE_WOOD_RED = (139, 69, 19)

    # Building colors
    WORKSHOP_SPINNING = (200, 200, 255)
    WORKSHOP_WEAVING = (255, 220, 180)
    WORKSHOP_DYEING = (150, 100, 200)
    WORKSHOP_SERICULTURE = (255, 215, 0)
    WORKSHOP_SMITHING = (255, 150, 50)
    WORKSHOP_POTTERY = (180, 120, 80)
    WORKSHOP_MILLING = (210, 180, 140)
    WORKSHOP_GENERAL = (150, 150, 150)

    GATHERING_SPOT = (100, 180, 100)
    DISPENSER = (100, 100, 255)
    SIGNPOST = (255, 255, 100)
    DELIVERY = (100, 255, 100)
    COMMUNE = (255, 200, 100)
    TERRAIN = (80, 80, 80)
    WAGON = (139, 90, 43)

    # Lighting
    AMBIENT = (80, 80, 100)
    LIGHT_TORCH = (255, 200, 150)
    LIGHT_WORKSHOP = (255, 180, 100)
    LIGHT_GATHERING = (150, 255, 150)
    LIGHT_SIGNPOST = (255, 255, 200)
    LIGHT_COMMUNE = (255, 215, 0)

    # Speech bubble
    BUBBLE_COLOR = (200, 200, 255)
    BUBBLE_TEXT = (40, 40, 80)


class Action(Enum):
    """All possible player actions."""
    # Movement
    MOVE_UP = auto()
    MOVE_DOWN = auto()
    MOVE_LEFT = auto()
    MOVE_RIGHT = auto()

    # Core interactions
    INTERACT = auto()

    # Recording/Playback
    TOGGLE_RECORDING = auto()
    TOGGLE_PLAYBACK = auto()

    # Wagon
    TOGGLE_HITCH = auto()
    UNLOAD_WAGON = auto()

    # Menus/Dialogs
    OPEN_SPAWN_DIALOG = auto()
    OPEN_RECIPE_DIALOG = auto()

    # UI
    QUIT = auto()
    TOGGLE_HELP = auto()
    CANCEL = auto()
    CONFIRM = auto()


# Default keybindings
DEFAULT_KEYBINDS: Dict[int, Action] = {
    # Movement - WASD and Arrows
    pygame.K_w: Action.MOVE_UP,
    pygame.K_UP: Action.MOVE_UP,
    pygame.K_s: Action.MOVE_DOWN,
    pygame.K_DOWN: Action.MOVE_DOWN,
    pygame.K_a: Action.MOVE_LEFT,
    pygame.K_LEFT: Action.MOVE_LEFT,
    pygame.K_d: Action.MOVE_RIGHT,
    pygame.K_RIGHT: Action.MOVE_RIGHT,

    # Interactions
    pygame.K_SPACE: Action.INTERACT,
    pygame.K_e: Action.INTERACT,

    # Recording
    pygame.K_r: Action.TOGGLE_RECORDING,
    pygame.K_p: Action.TOGGLE_PLAYBACK,

    # Wagon
    pygame.K_h: Action.TOGGLE_HITCH,
    pygame.K_u: Action.UNLOAD_WAGON,

    # Menus
    pygame.K_n: Action.OPEN_SPAWN_DIALOG,
    pygame.K_c: Action.OPEN_RECIPE_DIALOG,

    # UI
    pygame.K_q: Action.QUIT,
    pygame.K_ESCAPE: Action.CANCEL,
    pygame.K_F1: Action.TOGGLE_HELP,
    pygame.K_RETURN: Action.CONFIRM,
}


# Direction mappings
DIRECTION_DELTAS = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
}

ACTION_TO_DIRECTION = {
    Action.MOVE_UP: "up",
    Action.MOVE_DOWN: "down",
    Action.MOVE_LEFT: "left",
    Action.MOVE_RIGHT: "right",
}


# Monster types
MONSTER_TYPES = ["goblin", "cyclops", "elf", "orc", "troll"]

# Transferable skills
TRANSFERABLE_SKILLS = [
    "mathematics",
    "science",
    "engineering",
    "writing",
    "visual_art",
    "music",
    "handcrafts",
    "athletics",
    "outdoorsmonstership",
    "social",
]


# Lighting configuration
@dataclass
class LightConfig:
    """Configuration for a light source."""
    radius: int
    color: Tuple[int, int, int]
    intensity: float
    falloff: float
    casts_shadows: bool


LIGHT_CONFIGS = {
    "player_torch": LightConfig(8, Color.LIGHT_TORCH, 1.2, 2.0, True),
    "workshop_active": LightConfig(6, Color.LIGHT_WORKSHOP, 0.8, 2.0, True),
    "gathering_spot": LightConfig(4, Color.LIGHT_GATHERING, 0.5, 2.0, False),
    "signpost": LightConfig(3, Color.LIGHT_SIGNPOST, 0.6, 2.0, False),
    "commune": LightConfig(10, Color.LIGHT_COMMUNE, 1.0, 2.0, True),
}


# Animation/timing
CAMERA_LERP_SPEED = 0.1  # Smooth camera follow factor
SPRITE_LERP_SPEED = 10.0  # Cells per second for sprite movement
NOTIFICATION_DURATION = 4.0  # Seconds
BUBBLE_DURATION = 5.0  # Seconds for speech bubbles


# Quality thresholds
QUALITY_MASTERWORK = 90
QUALITY_FINE = 70
QUALITY_NORMAL = 50
