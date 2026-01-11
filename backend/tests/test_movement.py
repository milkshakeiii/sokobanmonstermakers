"""Tests for movement and push intents."""

import pytest
from uuid import uuid4

from conftest import (
    make_monster,
    make_item,
    make_terrain,
    make_workshop,
    make_dispenser,
    make_intent,
    find_update_for,
    find_position_update_for,
    find_event,
    MockIntent,
)


class TestBasicMovement:
    """Tests for basic monster movement."""

    def test_move_right(self, game, zone_id, player_id, setup_zone):
        """Monster can move right in empty space."""
        monster = make_monster(5, 5, player_id)
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="right")

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        update = find_update_for(result, monster.id)
        assert update is not None
        assert update.x == 6

    def test_move_left(self, game, zone_id, player_id, setup_zone):
        """Monster can move left in empty space."""
        monster = make_monster(5, 5, player_id)
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="left")

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        update = find_update_for(result, monster.id)
        assert update is not None
        assert update.x == 4

    def test_move_up(self, game, zone_id, player_id, setup_zone):
        """Monster can move up in empty space."""
        monster = make_monster(5, 5, player_id)
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="up")

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        update = find_update_for(result, monster.id)
        assert update is not None
        assert update.y == 4

    def test_move_down(self, game, zone_id, player_id, setup_zone):
        """Monster can move down in empty space."""
        monster = make_monster(5, 5, player_id)
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="down")

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        update = find_update_for(result, monster.id)
        assert update is not None
        assert update.y == 6

    def test_move_with_dx_dy(self, game, zone_id, player_id, setup_zone):
        """Monster can move using dx/dy instead of direction."""
        monster = make_monster(5, 5, player_id)
        intent = make_intent(player_id, "move", entity_id=str(monster.id), dx=1, dy=0)

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        update = find_update_for(result, monster.id)
        assert update is not None
        assert update.x == 6


class TestMovementBoundaries:
    """Tests for movement at zone boundaries."""

    def test_move_blocked_at_left_edge(self, game, zone_id, player_id, setup_zone):
        """Monster cannot move past left zone boundary."""
        monster = make_monster(0, 5, player_id)
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="left")

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        # Should not have any position updates
        update = find_update_for(result, monster.id)
        assert update is None or update.x is None or update.x == 0

    def test_move_blocked_at_right_edge(self, game, zone_id, player_id, setup_zone):
        """Monster cannot move past right zone boundary."""
        zone_width = setup_zone["width"]
        monster = make_monster(zone_width - 1, 5, player_id)
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="right")

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        update = find_update_for(result, monster.id)
        assert update is None or update.x is None or update.x == zone_width - 1

    def test_move_blocked_at_top_edge(self, game, zone_id, player_id, setup_zone):
        """Monster cannot move past top zone boundary."""
        monster = make_monster(5, 0, player_id)
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="up")

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        update = find_update_for(result, monster.id)
        assert update is None or update.y is None or update.y == 0

    def test_move_blocked_at_bottom_edge(self, game, zone_id, player_id, setup_zone):
        """Monster cannot move past bottom zone boundary."""
        zone_height = setup_zone["height"]
        monster = make_monster(5, zone_height - 1, player_id)
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="down")

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        update = find_update_for(result, monster.id)
        assert update is None or update.y is None or update.y == zone_height - 1


class TestMovementOwnership:
    """Tests for ownership validation during movement."""

    def test_cannot_move_other_players_monster(self, game, zone_id, player_id, setup_zone):
        """Player cannot move a monster owned by another player."""
        other_player = uuid4()
        monster = make_monster(5, 5, other_player)
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="right")

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        # Monster should not move
        update = find_update_for(result, monster.id)
        assert update is None or update.x is None

    def test_cannot_move_unowned_monster(self, game, zone_id, player_id, setup_zone):
        """Player cannot move a monster with no owner."""
        monster = make_monster(5, 5, owner_id=None)
        monster.owner_id = None
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="right")

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        update = find_update_for(result, monster.id)
        assert update is None or update.x is None


class TestMovementBlocking:
    """Tests for entities blocking movement."""

    def test_move_blocked_by_terrain(self, game, zone_id, player_id, setup_zone):
        """Monster cannot move into terrain block."""
        monster = make_monster(5, 5, player_id)
        terrain = make_terrain(6, 5)
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="right")

        result = game.on_tick(zone_id, [monster, terrain], [intent], tick_number=1)

        update = find_update_for(result, monster.id)
        assert update is None or update.x is None

    def test_move_blocked_by_another_monster(self, game, zone_id, player_id, setup_zone):
        """Monster cannot move into space occupied by another monster."""
        monster1 = make_monster(5, 5, player_id)
        monster2 = make_monster(6, 5, player_id, name="Blocker")
        intent = make_intent(player_id, "move", entity_id=str(monster1.id), direction="right")

        result = game.on_tick(zone_id, [monster1, monster2], [intent], tick_number=1)

        update = find_update_for(result, monster1.id)
        assert update is None or update.x is None


class TestPushMechanics:
    """Tests for pushing items."""

    def test_push_item_right(self, game, zone_id, player_id, setup_zone):
        """Monster can push an item into empty space."""
        monster = make_monster(5, 5, player_id)
        item = make_item(6, 5, "cotton_bolls")
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="right")

        result = game.on_tick(zone_id, [monster, item], [intent], tick_number=1)

        monster_update = find_position_update_for(result, monster.id)
        item_update = find_position_update_for(result, item.id)

        # Both should have moved by 1 cell (items move 1 cell at a time, not by width)
        assert monster_update is not None and monster_update.x == 6
        assert item_update is not None and item_update.x == 7

    def test_push_blocked_by_wall(self, game, zone_id, player_id, setup_zone):
        """Cannot push item into zone boundary."""
        zone_width = setup_zone["width"]  # 60
        # Item is 2 wide, so at x=58 it occupies 58-59
        # After push it would be at x=59, occupying 59-60 (60 is out of bounds)
        monster = make_monster(zone_width - 3, 5, player_id)  # x=57
        item = make_item(zone_width - 2, 5, "cotton_bolls")   # x=58, width=2
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="right")

        result = game.on_tick(zone_id, [monster, item], [intent], tick_number=1)

        monster_update = find_update_for(result, monster.id)
        # Monster should not move if push is blocked
        assert monster_update is None or monster_update.x is None

    def test_push_blocked_by_terrain(self, game, zone_id, player_id, setup_zone):
        """Cannot push item into terrain block."""
        monster = make_monster(5, 5, player_id)
        item = make_item(6, 5, "cotton_bolls")
        terrain = make_terrain(8, 5)  # Item would need to move here (it's 2 wide)
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="right")

        result = game.on_tick(zone_id, [monster, item, terrain], [intent], tick_number=1)

        monster_update = find_update_for(result, monster.id)
        assert monster_update is None or monster_update.x is None

    def test_stored_items_dont_block_movement(self, game, zone_id, player_id, setup_zone):
        """Stored items (in containers) don't block movement - monster walks through."""
        monster = make_monster(5, 5, player_id)
        # This item is stored in a container (workshop/dispenser) - it shouldn't block
        item = make_item(6, 5, "cotton_bolls", is_stored=True, container_id=str(uuid4()))
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="right")

        result = game.on_tick(zone_id, [monster, item], [intent], tick_number=1)

        monster_update = find_update_for(result, monster.id)
        # Monster should move through the stored item
        assert monster_update is not None and monster_update.x == 6

    def test_push_chain_blocked(self, game, zone_id, player_id, setup_zone):
        """Cannot push item if another item blocks its destination."""
        monster = make_monster(5, 5, player_id)
        item1 = make_item(6, 5, "cotton_bolls")
        item2 = make_item(8, 5, "yarn")  # Blocking the destination
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="right")

        result = game.on_tick(zone_id, [monster, item1, item2], [intent], tick_number=1)

        monster_update = find_update_for(result, monster.id)
        assert monster_update is None or monster_update.x is None


class TestMoveNonMonster:
    """Tests for attempting to move non-monster entities."""

    def test_cannot_move_item_directly(self, game, zone_id, player_id, setup_zone):
        """Player cannot directly move an item (must push it)."""
        item = make_item(5, 5, "cotton_bolls", owner_id=player_id)
        intent = make_intent(player_id, "move", entity_id=str(item.id), direction="right")

        result = game.on_tick(zone_id, [item], [intent], tick_number=1)

        update = find_update_for(result, item.id)
        assert update is None or update.x is None

    def test_cannot_move_workshop(self, game, zone_id, player_id, setup_zone):
        """Player cannot move a workshop."""
        workshop = make_workshop(5, 5)
        intent = make_intent(player_id, "move", entity_id=str(workshop.id), direction="right")

        result = game.on_tick(zone_id, [workshop], [intent], tick_number=1)

        update = find_update_for(result, workshop.id)
        assert update is None or update.x is None


class TestInvalidMoveIntents:
    """Tests for invalid movement intents."""

    def test_move_invalid_entity_id(self, game, zone_id, player_id, setup_zone):
        """Move intent with invalid entity ID does nothing."""
        monster = make_monster(5, 5, player_id)
        intent = make_intent(player_id, "move", entity_id="not-a-uuid", direction="right")

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        # Should complete without error
        assert result is not None

    def test_move_nonexistent_entity(self, game, zone_id, player_id, setup_zone):
        """Move intent for entity not in zone does nothing."""
        monster = make_monster(5, 5, player_id)
        intent = make_intent(player_id, "move", entity_id=str(uuid4()), direction="right")

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        # Should complete without error
        assert result is not None

    def test_move_invalid_direction(self, game, zone_id, player_id, setup_zone):
        """Move intent with invalid direction does nothing."""
        monster = make_monster(5, 5, player_id)
        intent = make_intent(player_id, "move", entity_id=str(monster.id), direction="diagonal")

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        update = find_update_for(result, monster.id)
        # Should not move
        assert update is None or (update.x is None and update.y is None)

    def test_move_missing_direction(self, game, zone_id, player_id, setup_zone):
        """Move intent without direction does nothing."""
        monster = make_monster(5, 5, player_id)
        intent = make_intent(player_id, "move", entity_id=str(monster.id))

        result = game.on_tick(zone_id, [monster], [intent], tick_number=1)

        update = find_update_for(result, monster.id)
        assert update is None or (update.x is None and update.y is None)
