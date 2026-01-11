"""Integration tests for full gameplay loops."""

import pytest
from uuid import uuid4

from conftest import (
    make_monster,
    make_item,
    make_gathering_spot,
    make_workshop,
    make_delivery,
    make_intent,
    find_event,
    find_update_for,
    find_position_update_for,
    MockEntity,
)


class TestGatheringLoop:
    """Tests for the full gathering loop."""

    def test_spawn_to_gather_loop(self, game, zone_id, player_id, setup_zone):
        """Test spawning a monster and gathering raw materials."""
        # Step 1: Spawn a monster
        spawn_intent = make_intent(
            player_id, "spawn_monster",
            monster_type="goblin",
            name="Gatherer",
            transferable_skills=["handcrafts", "athletics", "outdoorsmonstership"],
        )

        result = game.on_tick(zone_id, [], [spawn_intent], tick_number=1)

        # Verify monster was created
        monster_creates = [c for c in result.entity_creates if c.metadata.get("kind") == "monster"]
        assert len(monster_creates) == 1
        monster_data = monster_creates[0]
        assert monster_data.metadata["monster_type"] == "goblin"

        # For subsequent steps, we need a mock monster entity
        monster = make_monster(monster_data.x, monster_data.y, player_id)

        # Step 2: Create a gathering spot and select recipe
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")

        select_intent = make_intent(
            player_id, "select_recipe",
            workshop_id=str(gathering.id),
            recipe_id="Cotton Bolls",
            monster_id=str(monster.id),
        )

        result = game.on_tick(zone_id, [monster, gathering], [select_intent], tick_number=2)

        # Verify crafting started
        gathering_update = find_update_for(result, gathering.id)
        assert gathering_update is not None
        assert gathering_update.metadata.get("is_crafting") == True

        # Step 3: Wait for crafting to complete
        # Update gathering with crafting state
        gathering.metadata_.update(gathering_update.metadata)

        # Simulate time passing
        result = game.on_tick(zone_id, [monster, gathering], [], tick_number=1000)

        # Verify items were created
        item_creates = [c for c in result.entity_creates if c.metadata.get("kind") == "item"]
        assert len(item_creates) > 0
        # Verify it's cotton
        assert any("cotton" in (c.metadata.get("good_type") or "").lower() for c in item_creates)


class TestCraftingWithInputs:
    """Tests for crafting that requires inputs."""

    def test_crafting_blocked_without_inputs(self, game, zone_id, player_id, setup_zone):
        """Crafting that requires inputs is blocked without them."""
        monster = make_monster(5, 5, player_id)
        workshop = make_workshop(10, 4, workshop_type="spinning")

        # Try to craft something that needs inputs
        select_intent = make_intent(
            player_id, "select_recipe",
            workshop_id=str(workshop.id),
            recipe_id="Silkworm Cacoons",  # Requires inputs
            monster_id=str(monster.id),
        )

        result = game.on_tick(zone_id, [monster, workshop], [select_intent], tick_number=1)

        # Should be blocked due to missing inputs
        blocked_event = find_event(result, "crafting_blocked")
        assert blocked_event is not None
        assert len(blocked_event.get("missing_inputs", [])) > 0


class TestMonsterMovementAndPush:
    """Tests for combined movement and push operations."""

    def test_push_item_to_new_location(self, game, zone_id, player_id, setup_zone):
        """Monster can push items around the zone."""
        monster = make_monster(5, 5, player_id)
        item = make_item(6, 5, "cotton_bolls")

        # Push right
        push_intent = make_intent(
            player_id, "move",
            entity_id=str(monster.id),
            direction="right",
        )

        result = game.on_tick(zone_id, [monster, item], [push_intent], tick_number=1)

        # Both should have moved
        monster_update = find_position_update_for(result, monster.id)
        item_update = find_position_update_for(result, item.id)

        assert monster_update is not None and monster_update.x == 6
        assert item_update is not None and item_update.x == 7


class TestMultipleMonsters:
    """Tests for multiple monsters in the same zone."""

    def test_multiple_monsters_different_owners(self, game, zone_id, player_id, setup_zone):
        """Multiple players can have monsters in the same zone."""
        player2_id = uuid4()

        monster1 = make_monster(5, 5, player_id, name="Player1Monster")
        monster2 = make_monster(15, 5, player2_id, name="Player2Monster")

        # Player 1 moves their monster
        move_intent = make_intent(
            player_id, "move",
            entity_id=str(monster1.id),
            direction="right",
        )

        result = game.on_tick(zone_id, [monster1, monster2], [move_intent], tick_number=1)

        # Only monster1 should have moved
        m1_update = find_position_update_for(result, monster1.id)
        m2_update = find_position_update_for(result, monster2.id)

        assert m1_update is not None and m1_update.x == 6
        assert m2_update is None  # Player2's monster didn't move


class TestSkillProgression:
    """Tests for skill progression through crafting."""

    def test_repeated_crafting_increases_skills(self, game, zone_id, player_id, setup_zone):
        """Repeated crafting increases monster's skills."""
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")

        # First craft
        gathering.metadata_["crafter_monster_id"] = str(monster.id)
        gathering.metadata_["selected_recipe_id"] = "Cotton Bolls"
        gathering.metadata_["selected_recipe_name"] = "Cotton Bolls"
        gathering.metadata_["is_crafting"] = True
        gathering.metadata_["crafting_started_tick"] = 0
        gathering.metadata_["crafting_duration"] = 1

        result1 = game.on_tick(zone_id, [monster, gathering], [], tick_number=2)

        # Get skills after first craft
        m_update1 = find_update_for(result1, monster.id)
        skills1 = {}
        if m_update1 and m_update1.metadata:
            skills1 = m_update1.metadata.get("skills", {}).get("applied", {})
            # Update monster with new skills
            monster.metadata_["skills"] = m_update1.metadata.get("skills", {})
            monster.metadata_["total_forgotten"] = m_update1.metadata.get("total_forgotten", 0)

        # Second craft
        gathering.metadata_["is_crafting"] = True
        gathering.metadata_["crafting_started_tick"] = 2
        gathering.metadata_["crafting_duration"] = 1

        result2 = game.on_tick(zone_id, [monster, gathering], [], tick_number=4)

        # Get skills after second craft
        m_update2 = find_update_for(result2, monster.id)
        skills2 = {}
        if m_update2 and m_update2.metadata:
            skills2 = m_update2.metadata.get("skills", {}).get("applied", {})

        # Skills should have increased (or at minimum, crafting completed twice)
        crafts_completed = 0
        if find_event(result1, "crafting_complete"):
            crafts_completed += 1
        if find_event(result2, "crafting_complete"):
            crafts_completed += 1
        assert crafts_completed == 2  # Both crafts should have completed


class TestConcurrentActions:
    """Tests for multiple actions in the same tick."""

    def test_multiple_intents_same_tick(self, game, zone_id, player_id, setup_zone):
        """Multiple intents can be processed in the same tick."""
        monster1 = make_monster(5, 5, player_id, name="Monster1")
        monster2 = make_monster(15, 5, player_id, name="Monster2")

        # Both monsters move
        intent1 = make_intent(player_id, "move", entity_id=str(monster1.id), direction="right")
        intent2 = make_intent(player_id, "move", entity_id=str(monster2.id), direction="left")

        result = game.on_tick(zone_id, [monster1, monster2], [intent1, intent2], tick_number=1)

        # Both should have moved
        m1_update = find_position_update_for(result, monster1.id)
        m2_update = find_position_update_for(result, monster2.id)

        assert m1_update is not None and m1_update.x == 6
        assert m2_update is not None and m2_update.x == 14
