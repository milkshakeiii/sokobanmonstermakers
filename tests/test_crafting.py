"""Tests for crafting and recipe selection."""

import pytest
from uuid import uuid4

from conftest import (
    make_monster,
    make_item,
    make_workshop,
    make_gathering_spot,
    make_intent,
    find_event,
    find_update_for,
    find_all_events,
    MockEntity,
)


class TestSelectRecipe:
    """Tests for the select_recipe intent on workshops."""

    def test_select_recipe_on_gathering_spot(self, game, zone_id, player_id, setup_zone):
        """Can select a recipe on a gathering spot."""
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")

        # Set crafter
        gathering.metadata_["crafter_monster_id"] = str(monster.id)

        intent = make_intent(
            player_id, "select_recipe",
            workshop_id=str(gathering.id),
            recipe_id="Cotton Bolls",
        )

        result = game.on_tick(zone_id, [monster, gathering], [intent], tick_number=1)

        # Gathering spot should now have the recipe selected and be crafting
        update = find_update_for(result, gathering.id)
        assert update is not None
        assert update.metadata is not None
        assert update.metadata.get("selected_recipe_id") == "Cotton Bolls"
        assert update.metadata.get("is_crafting") == True

    def test_select_recipe_unknown(self, game, zone_id, player_id, setup_zone):
        """Selecting unknown recipe returns error."""
        workshop = make_workshop(10, 4)
        intent = make_intent(
            player_id, "select_recipe",
            workshop_id=str(workshop.id),
            recipe_id="nonexistent_recipe",
        )

        result = game.on_tick(zone_id, [workshop], [intent], tick_number=1)

        error_event = find_event(result, "error")
        assert error_event is not None
        assert "Unknown recipe" in error_event["message"]

    def test_select_recipe_wrong_workshop_type(self, game, zone_id, player_id, setup_zone):
        """Selecting recipe requiring different workshop type fails."""
        monster = make_monster(5, 5, player_id)
        workshop = make_workshop(10, 4, workshop_type="spinning")

        # Silkworm Cacoons requires a workshop but different setup
        intent = make_intent(
            player_id, "select_recipe",
            workshop_id=str(workshop.id),
            recipe_id="Silkworm Cacoons",  # Requires specific inputs
        )

        result = game.on_tick(zone_id, [monster, workshop], [intent], tick_number=1)

        # Should have crafting_blocked event due to missing inputs
        blocked_event = find_event(result, "crafting_blocked")
        assert blocked_event is not None


class TestCraftingProgress:
    """Tests for crafting progress and completion."""

    def test_crafting_starts_when_requirements_met(self, game, zone_id, player_id, setup_zone):
        """Crafting starts automatically when requirements are met."""
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")

        # Set up gathering with recipe selected
        gathering.metadata_["crafter_monster_id"] = str(monster.id)
        gathering.metadata_["selected_recipe_id"] = "Cotton Bolls"
        gathering.metadata_["selected_recipe_name"] = "Cotton Bolls"

        result = game.on_tick(zone_id, [monster, gathering], [], tick_number=1)

        # Should start crafting
        update = find_update_for(result, gathering.id)
        assert update is not None
        if update.metadata:
            assert update.metadata.get("is_crafting") == True
            assert "crafting_started_tick" in update.metadata

    def test_crafting_completes_after_duration(self, game, zone_id, player_id, setup_zone):
        """Crafting completes after the duration passes."""
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")

        # Set up gathering as already crafting
        gathering.metadata_["crafter_monster_id"] = str(monster.id)
        gathering.metadata_["selected_recipe_id"] = "Cotton Bolls"
        gathering.metadata_["selected_recipe_name"] = "Cotton Bolls"
        gathering.metadata_["is_crafting"] = True
        gathering.metadata_["crafting_started_tick"] = 0
        gathering.metadata_["crafting_duration"] = 60  # Will complete at tick 60

        # Tick at 61 (past duration)
        result = game.on_tick(zone_id, [monster, gathering], [], tick_number=61)

        # Should have crafting_complete event
        complete_event = find_event(result, "crafting_complete")
        assert complete_event is not None

        # Should create output items
        item_creates = [c for c in result.entity_creates if c.metadata.get("kind") == "item"]
        assert len(item_creates) > 0

    def test_crafting_not_complete_before_duration(self, game, zone_id, player_id, setup_zone):
        """Crafting does not complete before duration passes."""
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")

        # Set up gathering as already crafting
        gathering.metadata_["crafter_monster_id"] = str(monster.id)
        gathering.metadata_["selected_recipe_id"] = "Cotton Bolls"
        gathering.metadata_["selected_recipe_name"] = "Cotton Bolls"
        gathering.metadata_["is_crafting"] = True
        gathering.metadata_["crafting_started_tick"] = 0
        gathering.metadata_["crafting_duration"] = 60

        # Tick at 30 (before duration)
        result = game.on_tick(zone_id, [monster, gathering], [], tick_number=30)

        # Should NOT have crafting_complete event
        complete_event = find_event(result, "crafting_complete")
        assert complete_event is None

        # Should still be crafting
        update = find_update_for(result, gathering.id)
        if update and update.metadata:
            assert update.metadata.get("is_crafting") == True


class TestCraftingOutput:
    """Tests for crafting output items."""

    def test_output_has_correct_good_type(self, game, zone_id, player_id, setup_zone):
        """Output item has the correct good_type from the recipe."""
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")

        gathering.metadata_["crafter_monster_id"] = str(monster.id)
        gathering.metadata_["selected_recipe_id"] = "Cotton Bolls"
        gathering.metadata_["selected_recipe_name"] = "Cotton Bolls"
        gathering.metadata_["is_crafting"] = True
        gathering.metadata_["crafting_started_tick"] = 0
        gathering.metadata_["crafting_duration"] = 1

        result = game.on_tick(zone_id, [monster, gathering], [], tick_number=2)

        item_creates = [c for c in result.entity_creates if c.metadata.get("kind") == "item"]
        assert len(item_creates) > 0
        # Check good_type matches recipe (normalized to lowercase with underscores)
        good_types = [c.metadata.get("good_type") for c in item_creates]
        assert any("cotton" in (g or "").lower() for g in good_types)

    def test_output_has_quality(self, game, zone_id, player_id, setup_zone):
        """Output item has a quality value."""
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")

        gathering.metadata_["crafter_monster_id"] = str(monster.id)
        gathering.metadata_["selected_recipe_id"] = "Cotton Bolls"
        gathering.metadata_["selected_recipe_name"] = "Cotton Bolls"
        gathering.metadata_["is_crafting"] = True
        gathering.metadata_["crafting_started_tick"] = 0
        gathering.metadata_["crafting_duration"] = 1

        result = game.on_tick(zone_id, [monster, gathering], [], tick_number=2)

        item_creates = [c for c in result.entity_creates if c.metadata.get("kind") == "item"]
        assert len(item_creates) > 0
        for item in item_creates:
            quality = item.metadata.get("quality")
            assert quality is not None
            assert isinstance(quality, (int, float))
            assert quality >= 0


class TestCraftingRequirements:
    """Tests for crafting requirement validation."""

    def test_missing_inputs_blocks_crafting(self, game, zone_id, player_id, setup_zone):
        """Crafting with missing inputs emits crafting_blocked event."""
        workshop = make_workshop(10, 4, workshop_type="sericulture")

        # Try to craft Silkworm Cacoons which requires inputs
        intent = make_intent(
            player_id, "select_recipe",
            workshop_id=str(workshop.id),
            recipe_id="Silkworm Cacoons",
        )

        result = game.on_tick(zone_id, [workshop], [intent], tick_number=1)

        # Should be blocked due to missing inputs
        blocked_event = find_event(result, "crafting_blocked")
        assert blocked_event is not None
        missing = blocked_event.get("missing_inputs", [])
        assert len(missing) > 0  # Should list the missing inputs

    def test_gathering_spot_no_inputs_required(self, game, zone_id, player_id, setup_zone):
        """Gathering spots can craft raw materials without inputs."""
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")
        gathering.metadata_["crafter_monster_id"] = str(monster.id)

        intent = make_intent(
            player_id, "select_recipe",
            workshop_id=str(gathering.id),
            recipe_id="Cotton Bolls",
        )

        result = game.on_tick(zone_id, [monster, gathering], [intent], tick_number=1)

        # Should start crafting (not blocked)
        update = find_update_for(result, gathering.id)
        assert update is not None
        assert update.metadata is not None
        assert update.metadata.get("is_crafting") == True


class TestCraftingWithCrafter:
    """Tests for crafter monster effects on crafting."""

    def test_crafter_set_on_recipe_select(self, game, zone_id, player_id, setup_zone):
        """Crafter monster ID is recorded when selecting a recipe."""
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")

        intent = make_intent(
            player_id, "select_recipe",
            workshop_id=str(gathering.id),
            recipe_id="Cotton Bolls",
            monster_id=str(monster.id),  # Need to specify monster to be recognized as crafter
        )

        result = game.on_tick(zone_id, [monster, gathering], [intent], tick_number=1)

        update = find_update_for(result, gathering.id)
        assert update is not None
        assert update.metadata is not None
        crafter_id = update.metadata.get("crafter_monster_id")
        assert crafter_id == str(monster.id)


class TestCraftingDuration:
    """Tests for crafting duration calculation."""

    def test_duration_based_on_recipe(self, game, zone_id, player_id, setup_zone):
        """Crafting duration is based on recipe production_time."""
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")
        gathering.metadata_["crafter_monster_id"] = str(monster.id)

        intent = make_intent(
            player_id, "select_recipe",
            workshop_id=str(gathering.id),
            recipe_id="Cotton Bolls",
        )

        result = game.on_tick(zone_id, [monster, gathering], [intent], tick_number=1)

        update = find_update_for(result, gathering.id)
        if update and update.metadata:
            duration = update.metadata.get("crafting_duration")
            # Cotton Bolls has production_time=180
            assert duration is not None
            assert duration > 0


class TestGatheringSpotBehavior:
    """Tests specific to gathering spots."""

    def test_gathering_spot_locked_to_good_type(self, game, zone_id, player_id, setup_zone):
        """Gathering spot is locked to its gathering_good_type."""
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")

        # Try to select a different recipe
        intent = make_intent(
            player_id, "select_recipe",
            workshop_id=str(gathering.id),
            recipe_id="Silkworm Cacoons",  # Different from Cotton Bolls
        )

        result = game.on_tick(zone_id, [gathering], [intent], tick_number=1)

        # Should get error
        error_event = find_event(result, "error")
        assert error_event is not None
        assert "locked to" in error_event["message"].lower() or "Cotton Bolls" in error_event["message"]

    def test_gathering_spot_only_raw_materials(self, game, zone_id, player_id, setup_zone):
        """Gathering spots can only produce raw materials."""
        # This test verifies the behavior when trying to craft non-raw at gathering spot
        # Cotton Bolls is a raw material so it should work
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")
        gathering.metadata_["crafter_monster_id"] = str(monster.id)

        intent = make_intent(
            player_id, "select_recipe",
            workshop_id=str(gathering.id),
            recipe_id="Cotton Bolls",
        )

        result = game.on_tick(zone_id, [monster, gathering], [intent], tick_number=1)

        # Should succeed
        update = find_update_for(result, gathering.id)
        assert update is not None
        if update.metadata:
            assert update.metadata.get("is_crafting") == True
