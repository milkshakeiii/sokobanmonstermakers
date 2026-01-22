"""Sprite definitions and Unicode character mappings for all entity types."""

from typing import Any, Dict, List, Optional, Tuple

from config import Color


# Set of all available PNG item sprites (filename stems without .png)
# Items in this set will use pixel sprites instead of Unicode
PIXEL_SPRITE_ITEMS = {
    "alum_found",
    "ash_glaze",
    "barley_stalks",
    "bast_fiber",
    "black_clay",
    "black_dye",
    "blue_clay",
    "bricks",
    "bright_green_dye",
    "brown_sugar_cane",
    "canary_yellow_dye",
    "ceramic_cup",
    "ceramic_pot_mold",
    "ceramic_sycee_mold",
    "clay_palace_bricks",
    "clay_palace_tiles",
    "clay_tiles",
    "climbing_hempvine_stalks",
    "coal",
    "coke",
    "cotton_bolls",
    "cotton_seeds",
    "cotton_slivers",
    "crimson_dye",
    "dark_barley_stalks",
    "dark_green_dye",
    "decorated_ceramic",
    "deep_sky_blue_dye",
    "die",
    "die_pattern",
    "dyed_fabric",
    "eggshell_blue_dye",
    "fabric",
    "file",
    "flail",
    "flour",
    "flour_powered",
    "gallnuts",
    "golden_yellow_dye",
    "great_metal_statue",
    "green_vitriol",
    "green_vitriol_found",
    "hemp_stalks",
    "hulled_grain",
    "hungry_rice_stalks",
    "indigo",
    "indigofera_leaves",
    "knife",
    "kudzu_stalks",
    "large_mirror",
    "light_green_dye",
    "little_millet_stalks",
    "lotus_blossoms",
    "lye",
    "malt",
    "metal_anvil",
    "metal_axe",
    "metal_chisel",
    "metal_hammer",
    "metal_pot",
    "mirror_pattern",
    "nail",
    "needle",
    "oyster_lime",
    "palace_glaze",
    "pigweed_indigo_leaves",
    "pink_dye",
    "plums",
    "porcelain_clay_paste",
    "purple_dye",
    "ramie_stalks",
    "red_clay",
    "rice_stalks",
    "rice_stalks_irrigated",
    "rope",
    "royal_blue_dyed_fabric",
    "safflower_blossoms",
    "safflower_cakes",
    "safflower_seeds",
    "sand_mold",
    "saw",
    "scholartree_bud_cakes",
    "scholartree_buds",
    "sea_salt",
    "seeth_water",
    "sesame_stalks",
    "shaped_candy",
    "silk_thread",
    "silkworm_cacoons",
    "sorghum_stalks",
    "stone_anvil",
    "stone_hammer",
    "sugar",
    "sycee",
    "tea_brown_dye",
    "temple_bell",
    "thread",
    "velvetleaf_stalks",
    "well_salt",
    "wheat_stalks",
    "white_clay",
    "white_sugar_cane",
    "whole_grain",
    "wire",
    "wood_red_dye",
    "yellow_clay",
    "yellow_dye",
}


def has_pixel_sprite(good_type: str) -> bool:
    """Check if a good_type has a pixel sprite available."""
    # Normalize good_type to sprite name format
    sprite_name = good_type.lower().replace(" ", "_")
    return sprite_name in PIXEL_SPRITE_ITEMS


def get_pixel_sprite_name(good_type: str) -> Optional[str]:
    """Get the pixel sprite name for a good_type, or None if not available."""
    sprite_name = good_type.lower().replace(" ", "_")
    if sprite_name in PIXEL_SPRITE_ITEMS:
        return sprite_name
    return None


# Double-line Unicode box-drawing characters for workshop walls
WALL_CHARS = {
    "top_left": "╔",
    "top_right": "╗",
    "bottom_left": "╚",
    "bottom_right": "╝",
    "horizontal": "═",
    "vertical": "║",
}

# Workshop interior icons by type
WORKSHOP_INTERIOR_ICONS = {
    "spinning": "~",
    "weaving": "#",
    "dyeing": "▒",
    "sericulture": "@",
    "smithing": "▲",
    "casting": "▲",
    "blacksmithing": "▲",
    "pottery": "○",
    "milling": ":",
    "confectionery": "o",
    "carpentry": "-",
    "default": "·",
}

# Spot markers for designated workshop areas
SPOT_MARKERS = {
    "input": "▫",     # Small white square
    "output": "▪",    # Small black square
    "crafting": "✦",  # Star for crafting position
}


# Monster sprites (1x1)
MONSTER_SPRITES = {
    "cyclops": {"player": "@", "other": "C"},
    "elf": {"player": "@", "other": "E"},
    "goblin": {"player": "@", "other": "G"},
    "orc": {"player": "@", "other": "O"},
    "troll": {"player": "@", "other": "T"},
}

MONSTER_COLORS = {
    "cyclops": {"player": Color.PLAYER_CYCLOPS, "other": Color.OTHER_CYCLOPS},
    "elf": {"player": Color.PLAYER_ELF, "other": Color.OTHER_ELF},
    "goblin": {"player": Color.PLAYER_GOBLIN, "other": Color.OTHER_GOBLIN},
    "orc": {"player": Color.PLAYER_ORC, "other": Color.OTHER_ORC},
    "troll": {"player": Color.PLAYER_TROLL, "other": Color.OTHER_TROLL},
}


# Item sprites (2x1) - matched by type tags or name
# Format: (pattern, default_color)
ITEM_SPRITE_MAP = {
    # Fibers and raw materials
    "cotton": ("()", Color.ITEM_COTTON),
    "silk": ("@@", Color.ITEM_SILK),
    "silkworm": ("@@", Color.ITEM_SILK),
    "cocoon": ("@@", Color.ITEM_SILK),
    "stalk": ("||", Color.ITEM_STALKS),
    "hemp": ("||", Color.ITEM_STALKS),
    "ramie": ("||", Color.ITEM_STALKS),
    "kudzu": ("||", Color.ITEM_STALKS),
    "velvetleaf": ("||", Color.ITEM_STALKS),
    "hempvine": ("||", Color.ITEM_STALKS),
    "fiber": ("||", Color.ITEM_STALKS),
    "bast": ("||", Color.ITEM_STALKS),

    # Grains
    "grain": ("{{", Color.ITEM_GRAIN),
    "wheat": ("{{", Color.ITEM_GRAIN),
    "rice": ("{{", Color.ITEM_GRAIN),
    "barley": ("{{", Color.ITEM_GRAIN),
    "sorghum": ("{{", Color.ITEM_GRAIN),
    "millet": ("{{", Color.ITEM_GRAIN),
    "malt": ("%%", (184, 134, 11)),

    # Thread and fabric
    "thread": ("~~", Color.ITEM_THREAD),
    "sliver": ("~~", Color.ITEM_THREAD),
    "fabric": ("##", Color.ITEM_FABRIC),

    # Dyes
    "dye": ("[]", None),  # Color determined by dye type
    "crimson": ("[]", Color.DYE_CRIMSON),
    "pink": ("[]", Color.DYE_PINK),
    "purple": ("[]", Color.DYE_PURPLE),
    "canary": ("[]", Color.DYE_CANARY_YELLOW),
    "golden": ("[]", Color.DYE_GOLDEN_YELLOW),
    "indigo": ("[]", Color.DYE_INDIGO),
    "tea brown": ("[]", Color.DYE_TEA_BROWN),
    "dark green": ("[]", Color.DYE_DARK_GREEN),
    "bright green": ("[]", Color.DYE_BRIGHT_GREEN),
    "light green": ("[]", Color.DYE_LIGHT_GREEN),
    "deep sky": ("[]", Color.DYE_DEEP_SKY_BLUE),
    "eggshell": ("[]", Color.DYE_EGGSHELL_BLUE),
    "black dye": ("[]", Color.DYE_BLACK),
    "wood red": ("[]", Color.DYE_WOOD_RED),

    # Foods
    "flour": ("..", Color.ITEM_FLOUR),
    "sugar": ("''", Color.ITEM_SUGAR),
    "salt": ("++", (248, 248, 255)),
    "candy": ("oo", (255, 182, 193)),

    # Clay and ceramics
    "clay": ("<>", None),  # Color by clay type
    "red clay": ("<>", Color.ITEM_CLAY_RED),
    "yellow clay": ("<>", Color.ITEM_CLAY_YELLOW),
    "blue clay": ("<>", Color.ITEM_CLAY_BLUE),
    "white clay": ("<>", Color.ITEM_CLAY_WHITE),
    "black clay": ("<>", Color.ITEM_CLAY_BLACK),
    "brick": ("==", Color.ITEM_BRICK),
    "tile": ("[]", Color.ITEM_BRICK),
    "ceramic": ("{}", Color.ITEM_CERAMIC),
    "porcelain": ("{}", (250, 250, 255)),
    "pot": ("{}", Color.ITEM_CERAMIC),
    "cup": ("{}", Color.ITEM_CERAMIC),

    # Metals
    "metal": ("[]", Color.ITEM_METAL),
    "ingot": ("[]", Color.ITEM_METAL),
    "wire": ("--", Color.ITEM_METAL),
    "sycee": ("[]", Color.ITEM_SILK),  # Gold color
    "tool": ("|-", Color.ITEM_TOOL),
    "hammer": ("|-", Color.ITEM_TOOL),
    "anvil": ("__", (64, 64, 64)),
    "knife": ("/\\", Color.ITEM_TOOL),
    "needle": ("..", (211, 211, 211)),

    # Plants and flowers
    "blossom": ("**", (255, 182, 193)),
    "flower": ("**", (255, 182, 193)),
    "safflower": ("**", (255, 69, 0)),
    "lotus": ("**", (255, 105, 180)),
    "plum": ("oo", (128, 0, 128)),
    "fruit": ("oo", (255, 165, 0)),
    "bud": ("oo", (144, 238, 144)),
    "leaf": ("%%", (34, 139, 34)),
    "leaves": ("%%", (34, 139, 34)),
    "gallnut": ("oo", (139, 90, 43)),

    # Minerals
    "vitriol": ("<>", (0, 128, 0)),
    "alum": ("<>", (200, 200, 200)),
    "charcoal": ("##", (40, 40, 40)),
    "lye": ("[]", (200, 200, 150)),

    # Misc
    "glaze": ("[]", (200, 200, 255)),
    "pattern": ("[]", (150, 150, 150)),
    "die": ("[]", (192, 192, 192)),
    "mirror": ("[]", (220, 220, 255)),
    "bell": ("()", (218, 165, 32)),
    "statue": ("[]", (192, 192, 192)),

    # Textile equipment
    "spinner": ("~~", (139, 90, 43)),
    "loom": ("##", (139, 90, 43)),
    "basket": ("()", (139, 90, 43)),
    "spool": ("()", (200, 200, 200)),
    "cauldron": ("{}", (64, 64, 64)),
    "brazier": ("{}", (255, 100, 50)),
}


# Workshop sprites (4x4)
WORKSHOP_PATTERNS = {
    "spinning": """+--+
|~~|
|~~|
+--+""",
    "weaving": """+--+
|##|
|##|
+--+""",
    "dyeing": """+--+
|[]|
|[]|
+--+""",
    "sericulture": """+--+
|@@|
|@@|
+--+""",
    "smithing": """+--+
|/\\|
|__|
+--+""",
    "casting": """+--+
|/\\|
|__|
+--+""",
    "blacksmithing": """+--+
|/\\|
|__|
+--+""",
    "pottery": """+--+
|<>|
|<>|
+--+""",
    "milling": """+--+
|::|
|::|
+--+""",
    "confectionery": """+--+
|oo|
|oo|
+--+""",
    "carpentry": """+--+
|--|
|--|
+--+""",
    "default": """+--+
|**|
|**|
+--+""",
}

WORKSHOP_COLORS = {
    "spinning": Color.WORKSHOP_SPINNING,
    "weaving": Color.WORKSHOP_WEAVING,
    "dyeing": Color.WORKSHOP_DYEING,
    "sericulture": Color.WORKSHOP_SERICULTURE,
    "smithing": Color.WORKSHOP_SMITHING,
    "casting": Color.WORKSHOP_SMITHING,
    "blacksmithing": Color.WORKSHOP_SMITHING,
    "pottery": Color.WORKSHOP_POTTERY,
    "milling": Color.WORKSHOP_MILLING,
    "confectionery": (255, 192, 203),
    "carpentry": (139, 90, 43),
    "default": Color.WORKSHOP_GENERAL,
}


# Gathering spot pattern (4x4)
GATHERING_SPOT_PATTERN = """....
.XX.
.XX.
...."""


# Wagon sprites (3x2)
WAGON_EMPTY = """[==]
 oo """

WAGON_LOADED = """[##]
 oo """


# Other entity sprites
OTHER_SPRITES = {
    "dispenser": ("D", Color.DISPENSER),
    "container": ("▣", Color.CONTAINER),
    "signpost": ("!", Color.SIGNPOST),
    "terrain_block": ("#", Color.TERRAIN),
    "commune": ("*", Color.COMMUNE),
}

DELIVERY_PATTERN = """>>\n>>"""


def get_monster_sprite_def(
    monster_type: str,
    is_player: bool,
) -> Tuple[str, Tuple[int, int, int]]:
    """Get sprite definition for a monster.

    Args:
        monster_type: Type of monster (goblin, elf, etc.)
        is_player: Whether this is the player's monster

    Returns:
        Tuple of (character, color)
    """
    key = "player" if is_player else "other"

    sprites = MONSTER_SPRITES.get(monster_type, MONSTER_SPRITES["goblin"])
    colors = MONSTER_COLORS.get(monster_type, MONSTER_COLORS["goblin"])

    return sprites[key], colors[key]


def get_item_pixel_sprite_name(metadata: Dict[str, Any]) -> Optional[str]:
    """Get pixel sprite name for an item if available.

    Args:
        metadata: Entity metadata containing good_type

    Returns:
        Sprite name if pixel sprite exists, None otherwise
    """
    good_type = metadata.get("good_type", "")
    return get_pixel_sprite_name(good_type)


def get_item_sprite_def(metadata: Dict[str, Any]) -> Tuple[str, Tuple[int, int, int]]:
    """Get sprite definition for an item (Unicode fallback).

    Args:
        metadata: Entity metadata containing good_type, type_tags, etc.

    Returns:
        Tuple of (pattern, color)
    """
    good_type = metadata.get("good_type", "").lower()
    type_tags = metadata.get("type_tags", [])

    # Check type tags first (more specific)
    for tag in type_tags:
        tag_lower = tag.lower()
        if tag_lower in ITEM_SPRITE_MAP:
            pattern, color = ITEM_SPRITE_MAP[tag_lower]
            if color is None:
                color = _derive_item_color(metadata, good_type)
            return pattern, color

    # Check good type name
    for key, (pattern, color) in ITEM_SPRITE_MAP.items():
        if key in good_type:
            if color is None:
                color = _derive_item_color(metadata, good_type)
            return pattern, color

    # Default
    return "**", Color.ITEM_DEFAULT


def _derive_item_color(metadata: Dict, good_type: str) -> Tuple[int, int, int]:
    """Derive color from item metadata when not explicitly mapped."""
    good_type_lower = good_type.lower()

    # Dyed fabric - extract dye color
    if "dyed" in good_type_lower:
        for dye_name, (_, color) in ITEM_SPRITE_MAP.items():
            if dye_name in good_type_lower and color:
                return color
        return Color.ITEM_FABRIC

    # Clay types
    if "red" in good_type_lower:
        return Color.ITEM_CLAY_RED
    if "yellow" in good_type_lower:
        return Color.ITEM_CLAY_YELLOW
    if "blue" in good_type_lower:
        return Color.ITEM_CLAY_BLUE
    if "white" in good_type_lower:
        return Color.ITEM_CLAY_WHITE
    if "black" in good_type_lower:
        return Color.ITEM_CLAY_BLACK

    return Color.ITEM_DEFAULT


def generate_workshop_pattern(
    width: int,
    height: int,
    workshop_type: str,
    doors: List[Dict[str, Any]],
    input_spots: Optional[List[Dict[str, int]]] = None,
    output_spots: Optional[List[Dict[str, int]]] = None,
    crafting_spot: Optional[Dict[str, int]] = None,
) -> str:
    """Generate a workshop pattern with walls and designated spots.

    Args:
        width: Workshop width in cells
        height: Workshop height in cells
        workshop_type: Type of workshop for interior icon
        doors: List of door definitions [{"side": "bottom", "offset": 2, "width": 2}]
        input_spots: List of input spot positions [{"x": 1, "y": 1}]
        output_spots: List of output spot positions [{"x": 4, "y": 4}]
        crafting_spot: Position of crafting spot {"x": 2, "y": 2}

    Returns:
        Multi-line pattern string with Unicode box-drawing walls
    """
    interior_icon = WORKSHOP_INTERIOR_ICONS.get(workshop_type, WORKSHOP_INTERIOR_ICONS["default"])

    # Build door cell lookup
    door_cells = set()
    for door in doors:
        side = door.get("side", "bottom")
        offset = door.get("offset", 0)
        door_width = door.get("width", 2)

        for i in range(door_width):
            if side == "top":
                door_cells.add((offset + i, 0))
            elif side == "bottom":
                door_cells.add((offset + i, height - 1))
            elif side == "left":
                door_cells.add((0, offset + i))
            elif side == "right":
                door_cells.add((width - 1, offset + i))

    # Build spot lookups (positions are relative to workshop top-left)
    input_cells = set()
    for spot in (input_spots or []):
        input_cells.add((spot.get("x", 0), spot.get("y", 0)))

    output_cells = set()
    for spot in (output_spots or []):
        output_cells.add((spot.get("x", 0), spot.get("y", 0)))

    crafting_cell = None
    if crafting_spot:
        crafting_cell = (crafting_spot.get("x", 0), crafting_spot.get("y", 0))

    rows = []
    for y in range(height):
        row = ""
        for x in range(width):
            is_door = (x, y) in door_cells
            is_corner = (x == 0 or x == width - 1) and (y == 0 or y == height - 1)
            is_top = y == 0
            is_bottom = y == height - 1
            is_left = x == 0
            is_right = x == width - 1

            if is_door:
                row += " "
            elif is_corner:
                if x == 0 and y == 0:
                    row += WALL_CHARS["top_left"]
                elif x == width - 1 and y == 0:
                    row += WALL_CHARS["top_right"]
                elif x == 0 and y == height - 1:
                    row += WALL_CHARS["bottom_left"]
                else:
                    row += WALL_CHARS["bottom_right"]
            elif is_top or is_bottom:
                row += WALL_CHARS["horizontal"]
            elif is_left or is_right:
                row += WALL_CHARS["vertical"]
            elif (x, y) == crafting_cell:
                row += SPOT_MARKERS["crafting"]
            elif (x, y) in input_cells:
                row += SPOT_MARKERS["input"]
            elif (x, y) in output_cells:
                row += SPOT_MARKERS["output"]
            else:
                # Interior cell
                row += interior_icon

        rows.append(row)

    return "\n".join(rows)


def get_workshop_sprite_def(
    metadata: Dict[str, Any],
    width: int = 4,
    height: int = 4,
) -> Tuple[str, Tuple[int, int, int]]:
    """Get sprite definition for a workshop.

    Args:
        metadata: Entity metadata
        width: Workshop width in cells
        height: Workshop height in cells

    Returns:
        Tuple of (pattern, color)
    """
    # Try to determine workshop type from various metadata fields
    workshop_type = None

    # Check for explicit workshop type
    if "workshop_type" in metadata:
        workshop_type = metadata["workshop_type"].lower()

    # Check selected recipe skill
    elif "selected_recipe_id" in metadata:
        recipe = metadata.get("selected_recipe_id", "").lower()
        if "thread" in recipe or "silk" in recipe:
            workshop_type = "spinning"
        elif "fabric" in recipe:
            workshop_type = "weaving"
        elif "dye" in recipe:
            workshop_type = "dyeing"

    # Check primary applied skill from recipe
    elif "primary_applied_skill" in metadata:
        skill = metadata["primary_applied_skill"].lower()
        skill_to_type = {
            "spinning": "spinning",
            "weaving": "weaving",
            "dyeing": "dyeing",
            "sericulture": "sericulture",
            "blacksmithing": "smithing",
            "casting": "casting",
            "pottery": "pottery",
            "milling": "milling",
            "confectionery": "confectionery",
            "carpentry": "carpentry",
        }
        workshop_type = skill_to_type.get(skill, "default")

    if workshop_type is None:
        workshop_type = "default"

    color = WORKSHOP_COLORS.get(workshop_type, WORKSHOP_COLORS["default"])

    # Check if workshop has walls (use dynamic pattern generation)
    if metadata.get("has_walls", False):
        doors = metadata.get("doors", [])
        input_spots = metadata.get("input_spots", [])
        output_spots = metadata.get("output_spots", [])
        crafting_spot = metadata.get("crafting_spot")
        pattern = generate_workshop_pattern(
            width,
            height,
            workshop_type,
            doors,
            input_spots,
            output_spots,
            crafting_spot,
        )
    else:
        pattern = WORKSHOP_PATTERNS.get(workshop_type, WORKSHOP_PATTERNS["default"])

    return pattern, color


def get_gathering_spot_sprite_def(metadata: Dict[str, Any]) -> Tuple[str, Tuple[int, int, int]]:
    """Get sprite definition for a gathering spot.

    Args:
        metadata: Entity metadata

    Returns:
        Tuple of (pattern, color)
    """
    # Get the gathered good type (try both key names)
    good_type = metadata.get("gathered_good_type", "") or metadata.get("gathering_good_type", "")
    good_type = good_type.lower()

    # Determine center icon based on good type
    if "cotton" in good_type:
        center = "()"
        color = Color.ITEM_COTTON
    elif "silk" in good_type or "cocoon" in good_type:
        center = "@@"
        color = Color.ITEM_SILK
    elif "grain" in good_type or "wheat" in good_type or "rice" in good_type:
        center = "{{"
        color = Color.ITEM_GRAIN
    elif "clay" in good_type:
        center = "<>"
        color = Color.WORKSHOP_POTTERY
    else:
        center = "**"
        color = Color.GATHERING_SPOT

    pattern = GATHERING_SPOT_PATTERN.replace("XX", center)
    return pattern, color


def get_wagon_sprite_def(metadata: Dict[str, Any]) -> Tuple[str, Tuple[int, int, int]]:
    """Get sprite definition for a wagon.

    Args:
        metadata: Entity metadata

    Returns:
        Tuple of (pattern, color)
    """
    loaded_items = metadata.get("loaded_item_ids", [])

    if loaded_items:
        return WAGON_LOADED, Color.WAGON
    else:
        return WAGON_EMPTY, Color.WAGON


def get_delivery_sprite_def() -> Tuple[str, Tuple[int, int, int]]:
    """Get sprite definition for a delivery zone."""
    return DELIVERY_PATTERN, Color.DELIVERY


def get_sprite_def(entity: Dict[str, Any], player_id: Optional[str] = None) -> Tuple[str, Tuple[int, int, int]]:
    """Get sprite definition for any entity.

    Args:
        entity: Full entity data dict
        player_id: Current player's ID (for monster ownership check)

    Returns:
        Tuple of (pattern, color)
    """
    metadata = entity.get("metadata", {})
    kind = metadata.get("kind", "unknown")

    if kind == "monster":
        monster_type = metadata.get("monster_type", "goblin")
        is_player = entity.get("owner_id") == player_id
        return get_monster_sprite_def(monster_type, is_player)

    elif kind == "item":
        return get_item_sprite_def(metadata)

    elif kind == "workshop":
        width = entity.get("width", 4)
        height = entity.get("height", 4)
        return get_workshop_sprite_def(metadata, width, height)

    elif kind == "gathering_spot":
        return get_gathering_spot_sprite_def(metadata)

    elif kind == "wagon":
        return get_wagon_sprite_def(metadata)

    elif kind == "delivery":
        return get_delivery_sprite_def()

    elif kind in OTHER_SPRITES:
        return OTHER_SPRITES[kind]

    else:
        return ("?", Color.GRAY)


def get_item_color(metadata: Dict[str, Any]) -> Tuple[int, int, int]:
    """Get just the color for an item (for UI display)."""
    _, color = get_item_sprite_def(metadata)
    return color
