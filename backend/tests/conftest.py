"""Test fixtures for Monster Workshop game module."""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4, UUID

import pytest

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Mock the grid_backend imports before importing game module
@dataclass
class MockEntity:
    """Mock Entity class matching grid_backend.models.entity.Entity interface."""
    x: int
    y: int
    id: UUID = None  # Will be auto-generated if not provided
    width: int = 1
    height: int = 1
    owner_id: UUID | None = None
    metadata_: dict[str, Any] | None = None
    zone_id: UUID | None = None
    created_at: Any = None
    updated_at: Any = None

    def __post_init__(self):
        if self.id is None:
            self.id = uuid4()


@dataclass
class MockIntent:
    """Mock Intent class matching grid_backend.game_logic.protocol.Intent interface."""
    player_id: UUID
    data: dict[str, Any]
    zone_id: UUID | None = None


@dataclass
class MockEntityCreate:
    """Mock EntityCreate for verifying creates."""
    x: int
    y: int
    width: int = 1
    height: int = 1
    owner_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MockEntityUpdate:
    """Mock EntityUpdate for verifying updates."""
    id: UUID
    x: int | None = None
    y: int | None = None
    width: int | None = None
    height: int | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class MockTickResult:
    """Mock TickResult for game logic returns."""
    entity_creates: list = field(default_factory=list)
    entity_updates: list = field(default_factory=list)
    entity_deletes: list = field(default_factory=list)
    extras: dict = field(default_factory=dict)


# Patch grid_backend before importing game module
class MockProtocolModule:
    Intent = MockIntent
    TickResult = MockTickResult
    EntityCreate = MockEntityCreate
    EntityUpdate = MockEntityUpdate
    FrameworkAPI = None


class MockEntityModule:
    Entity = MockEntity


class MockGridBackend:
    pass


# Install mocks
sys.modules['grid_backend'] = type(sys)('grid_backend')
sys.modules['grid_backend.game_logic'] = type(sys)('grid_backend.game_logic')
sys.modules['grid_backend.game_logic.protocol'] = MockProtocolModule
sys.modules['grid_backend.models'] = type(sys)('grid_backend.models')
sys.modules['grid_backend.models.entity'] = MockEntityModule

# Now we can import the game module
from monster_workshop_game.main import MonsterWorkshopGame


@pytest.fixture
def game() -> MonsterWorkshopGame:
    """Create a fresh game instance for testing."""
    return MonsterWorkshopGame()


@pytest.fixture
def zone_id() -> UUID:
    """Generate a unique zone ID for testing."""
    return uuid4()


@pytest.fixture
def player_id() -> UUID:
    """Generate a unique player ID for testing."""
    return uuid4()


@pytest.fixture
def zone_def() -> dict[str, Any]:
    """Default zone definition for testing."""
    return {
        "name": "Test Zone",
        "width": 60,
        "height": 20,
        "spawn_points": [{"x": 3, "y": 3}],
        "static_entities": [],
    }


@pytest.fixture
def setup_zone(game: MonsterWorkshopGame, zone_id: UUID, zone_def: dict[str, Any]):
    """Configure game instance with a test zone."""
    game._zone_id_to_def[zone_id] = zone_def
    game._zone_sizes[zone_id] = (zone_def["width"], zone_def["height"])
    game._initialized_zones.add(zone_id)
    return zone_def


def make_monster(
    x: int,
    y: int,
    owner_id: UUID,
    monster_type: str = "goblin",
    name: str = "Test Monster",
    **extra_metadata
) -> MockEntity:
    """Helper to create a monster entity."""
    metadata = {
        "kind": "monster",
        "monster_type": monster_type,
        "name": name,
        "stats": get_monster_stats(monster_type),
        "skills": {"applied": {}, "specific": {}, "transferable": []},
        **extra_metadata,
    }
    return MockEntity(
        x=x,
        y=y,
        width=1,
        height=1,
        owner_id=owner_id,
        metadata_=metadata,
    )


def make_item(
    x: int,
    y: int,
    good_type: str,
    quality: float = 1.0,
    owner_id: UUID | None = None,
    **extra_metadata
) -> MockEntity:
    """Helper to create an item entity."""
    metadata = {
        "kind": "item",
        "good_type": good_type,
        "quality": quality,
        **extra_metadata,
    }
    return MockEntity(
        x=x,
        y=y,
        width=2,
        height=1,
        owner_id=owner_id,
        metadata_=metadata,
    )


def make_workshop(
    x: int,
    y: int,
    workshop_type: str = "spinning",
    width: int = 4,
    height: int = 4,
    **extra_metadata
) -> MockEntity:
    """Helper to create a workshop entity."""
    metadata = {
        "kind": "workshop",
        "workshop_type": workshop_type,
        "blocks_movement": False,
        "input_slots": [],
        "output_slots": [],
        **extra_metadata,
    }
    return MockEntity(
        x=x,
        y=y,
        width=width,
        height=height,
        owner_id=None,
        metadata_=metadata,
    )


def make_gathering_spot(
    x: int,
    y: int,
    gathering_good_type: str,
    width: int = 4,
    height: int = 4,
    **extra_metadata
) -> MockEntity:
    """Helper to create a gathering spot entity."""
    metadata = {
        "kind": "gathering_spot",
        "gathering_good_type": gathering_good_type,
        "blocks_movement": False,
        **extra_metadata,
    }
    return MockEntity(
        x=x,
        y=y,
        width=width,
        height=height,
        owner_id=None,
        metadata_=metadata,
    )


def make_dispenser(
    x: int,
    y: int,
    stored_good_type: str,
    capacity: int = 10,
    **extra_metadata
) -> MockEntity:
    """Helper to create a dispenser entity."""
    metadata = {
        "kind": "dispenser",
        "stored_good_type": stored_good_type,
        "capacity": capacity,
        **extra_metadata,
    }
    return MockEntity(
        x=x,
        y=y,
        width=1,
        height=1,
        owner_id=None,
        metadata_=metadata,
    )


def make_wagon(
    x: int,
    y: int,
    capacity: int = 100,
    owner_id: UUID | None = None,
    **extra_metadata
) -> MockEntity:
    """Helper to create a wagon entity."""
    metadata = {
        "kind": "wagon",
        "capacity": capacity,
        **extra_metadata,
    }
    return MockEntity(
        x=x,
        y=y,
        width=3,
        height=2,
        owner_id=owner_id,
        metadata_=metadata,
    )


def make_delivery(x: int, y: int, width: int = 2, height: int = 2) -> MockEntity:
    """Helper to create a delivery building entity."""
    metadata = {
        "kind": "delivery",
    }
    return MockEntity(
        x=x,
        y=y,
        width=width,
        height=height,
        owner_id=None,
        metadata_=metadata,
    )


def make_terrain(x: int, y: int, width: int = 1, height: int = 1) -> MockEntity:
    """Helper to create a terrain block entity."""
    metadata = {
        "kind": "terrain_block",
    }
    return MockEntity(
        x=x,
        y=y,
        width=width,
        height=height,
        owner_id=None,
        metadata_=metadata,
    )


def get_monster_stats(monster_type: str) -> dict[str, int]:
    """Get default stats for a monster type."""
    stats_map = {
        "cyclops": {"str": 18, "dex": 10, "con": 16, "int": 8, "wis": 10, "cha": 8},
        "elf": {"str": 8, "dex": 16, "con": 10, "int": 18, "wis": 12, "cha": 10},
        "goblin": {"str": 8, "dex": 18, "con": 10, "int": 10, "wis": 8, "cha": 16},
        "orc": {"str": 16, "dex": 10, "con": 18, "int": 8, "wis": 10, "cha": 8},
        "troll": {"str": 12, "dex": 8, "con": 14, "int": 8, "wis": 10, "cha": 8},
    }
    return stats_map.get(monster_type, {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10})


def make_intent(player_id: UUID, action: str, **data) -> MockIntent:
    """Helper to create an intent."""
    return MockIntent(player_id=player_id, data={"action": action, **data})


def find_update_for(result, entity_id: UUID) -> MockEntityUpdate | None:
    """Find an entity update in a TickResult by entity ID."""
    for update in result.entity_updates:
        if update.id == entity_id:
            return update
    return None


def find_position_update_for(result, entity_id: UUID) -> MockEntityUpdate | None:
    """Find an entity position update (one with x or y set) by entity ID."""
    for update in result.entity_updates:
        if update.id == entity_id and (update.x is not None or update.y is not None):
            return update
    return None


def find_all_updates_for(result, entity_id: UUID) -> list[MockEntityUpdate]:
    """Find all entity updates for a given entity ID."""
    return [u for u in result.entity_updates if u.id == entity_id]


def find_event(result, event_type: str) -> dict | None:
    """Find an event in a TickResult by type."""
    events = result.extras.get("events", [])
    for event in events:
        if event.get("type") == event_type:
            return event
    return None


def find_all_events(result, event_type: str) -> list[dict]:
    """Find all events of a given type in a TickResult."""
    events = result.extras.get("events", [])
    return [e for e in events if e.get("type") == event_type]
