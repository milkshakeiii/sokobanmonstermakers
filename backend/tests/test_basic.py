"""Basic sanity tests to verify test infrastructure works."""

import pytest
from uuid import uuid4

from conftest import (
    make_monster,
    make_item,
    make_intent,
    MockIntent,
)


def test_game_instantiation(game):
    """Verify game module can be instantiated."""
    assert game is not None
    assert hasattr(game, 'on_tick')
    assert hasattr(game, '_good_types')
    assert hasattr(game, '_monster_types')


def test_zone_setup(game, zone_id, setup_zone):
    """Verify zone can be configured for testing."""
    assert zone_id in game._zone_id_to_def
    assert zone_id in game._zone_sizes
    assert zone_id in game._initialized_zones


def test_empty_tick(game, zone_id, player_id, setup_zone):
    """Verify empty tick returns valid result."""
    result = game.on_tick(zone_id, [], [], tick_number=1)
    assert result is not None
    assert hasattr(result, 'entity_creates')
    assert hasattr(result, 'entity_updates')
    assert hasattr(result, 'entity_deletes')


def test_make_monster_helper(player_id):
    """Verify monster creation helper works."""
    monster = make_monster(5, 5, player_id)
    assert monster.x == 5
    assert monster.y == 5
    assert monster.owner_id == player_id
    assert monster.metadata_["kind"] == "monster"
    assert monster.metadata_["monster_type"] == "goblin"


def test_make_item_helper():
    """Verify item creation helper works."""
    item = make_item(10, 10, "cotton_bolls", quality=0.8)
    assert item.x == 10
    assert item.y == 10
    assert item.metadata_["kind"] == "item"
    assert item.metadata_["good_type"] == "cotton_bolls"
    assert item.metadata_["quality"] == 0.8


def test_make_intent_helper(player_id):
    """Verify intent creation helper works."""
    intent = make_intent(player_id, "move", entity_id="abc", direction="up")
    assert intent.player_id == player_id
    assert intent.data["action"] == "move"
    assert intent.data["entity_id"] == "abc"
    assert intent.data["direction"] == "up"
