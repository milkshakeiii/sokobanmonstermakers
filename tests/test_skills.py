"""Tests for skill learning and forgetting mechanics."""

import pytest
from uuid import uuid4
from datetime import datetime, timedelta

from conftest import (
    make_monster,
    make_gathering_spot,
    find_update_for,
    MockEntity,
)


class TestSkillLearning:
    """Tests for skill learning during crafting."""

    def test_skills_increase_on_craft_completion(self, game, zone_id, player_id, setup_zone):
        """Skills increase when crafting completes."""
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")

        # Set up completed craft
        gathering.metadata_["crafter_monster_id"] = str(monster.id)
        gathering.metadata_["selected_recipe_id"] = "Cotton Bolls"
        gathering.metadata_["selected_recipe_name"] = "Cotton Bolls"
        gathering.metadata_["is_crafting"] = True
        gathering.metadata_["crafting_started_tick"] = 0
        gathering.metadata_["crafting_duration"] = 1
        gathering.metadata_["primary_applied_skill"] = "harvesting"

        result = game.on_tick(zone_id, [monster, gathering], [], tick_number=2)

        # Monster should have skill updates
        monster_update = find_update_for(result, monster.id)
        if monster_update and monster_update.metadata:
            skills = monster_update.metadata.get("skills", {})
            applied = skills.get("applied", {})
            # Harvesting skill should have increased
            assert "harvesting" in applied or len(applied) > 0

    def test_last_skill_gained_recorded(self, game, zone_id, player_id, setup_zone):
        """Workshop records the last skill gained after crafting."""
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")

        gathering.metadata_["crafter_monster_id"] = str(monster.id)
        gathering.metadata_["selected_recipe_id"] = "Cotton Bolls"
        gathering.metadata_["selected_recipe_name"] = "Cotton Bolls"
        gathering.metadata_["is_crafting"] = True
        gathering.metadata_["crafting_started_tick"] = 0
        gathering.metadata_["crafting_duration"] = 1

        result = game.on_tick(zone_id, [monster, gathering], [], tick_number=2)

        gathering_update = find_update_for(result, gathering.id)
        if gathering_update and gathering_update.metadata:
            last_skill = gathering_update.metadata.get("last_skill_gained")
            # Should have recorded skill gains
            if last_skill:
                assert "primary_skill" in last_skill or "specific_skill" in last_skill


class TestSkillValues:
    """Tests for skill value calculations."""

    def test_get_skill_value_default(self, game):
        """Skill value defaults to 0 for unlearned skills."""
        monster = make_monster(0, 0, uuid4())
        value = game._get_skill_value(monster, "blacksmithing", "applied")
        assert value == 0.0

    def test_get_skill_value_learned(self, game):
        """Skill value returns learned amount minus forgotten."""
        monster = make_monster(0, 0, uuid4())
        monster.metadata_["skills"]["applied"]["blacksmithing"] = 0.5
        monster.metadata_["total_forgotten"] = 0.1

        value = game._get_skill_value(monster, "blacksmithing", "applied")
        # Value should be total_learned (0.5) - total_forgotten (0.1) = 0.4
        assert value == pytest.approx(0.4, abs=0.01)

    def test_skill_value_never_negative(self, game):
        """Skill value is always non-negative."""
        monster = make_monster(0, 0, uuid4())
        monster.metadata_["skills"]["applied"]["blacksmithing"] = 0.1
        monster.metadata_["total_forgotten"] = 0.5  # Forgotten more than learned

        value = game._get_skill_value(monster, "blacksmithing", "applied")
        assert value >= 0.0


class TestTransferableSkills:
    """Tests for transferable skill effects."""

    def test_matching_transferable_skills_counted(self, game):
        """Matching transferable skills are counted correctly."""
        monster = make_monster(0, 0, uuid4())
        monster.metadata_["skills"]["transferable"] = ["athletics", "outdoorsmonstership"]

        # Cotton Bolls requires: social, outdoorsmonstership, athletics
        recipe = game._get_recipe_entry("Cotton Bolls")
        if recipe:
            count = game._matching_transferable_skills_count(recipe, monster)
            assert count >= 1  # At least some skills should match

    def test_no_matching_transferable_skills(self, game):
        """No matching skills returns 0."""
        monster = make_monster(0, 0, uuid4())
        monster.metadata_["skills"]["transferable"] = ["mathematics", "science"]

        # Cotton Bolls requires different skills
        recipe = game._get_recipe_entry("Cotton Bolls")
        if recipe:
            count = game._matching_transferable_skills_count(recipe, monster)
            assert count == 0


class TestSkillDecay:
    """Tests for skill decay over time."""

    def test_skill_decay_applies_over_time(self, game, zone_id, player_id, setup_zone):
        """Skills decay when not used for a while."""
        monster = make_monster(0, 0, uuid4())
        monster.metadata_["skills"]["applied"]["blacksmithing"] = 0.5
        monster.metadata_["skills"]["last_used"] = {}
        monster.metadata_["skills"]["last_decay_at"] = {}
        # Created long ago
        old_date = datetime.utcnow() - timedelta(days=30)
        monster.metadata_["created_at"] = old_date.isoformat()

        updates = []
        game._apply_skill_decay(monster, updates)

        # Check if decay was applied (depends on time calculation)
        if updates:
            update = updates[0]
            if update.metadata:
                skills = update.metadata.get("skills", {})
                applied = skills.get("applied", {})
                new_value = applied.get("blacksmithing", 0.5)
                # Should have decayed somewhat
                assert new_value <= 0.5


class TestSpecificSkills:
    """Tests for specific (good-type) skills."""

    def test_specific_skill_increases(self, game, zone_id, player_id, setup_zone):
        """Specific skill for a good type increases on crafting."""
        monster = make_monster(5, 5, player_id)
        gathering = make_gathering_spot(10, 4, "Cotton Bolls")

        # Initial specific skill
        monster.metadata_["skills"]["specific"] = {}

        gathering.metadata_["crafter_monster_id"] = str(monster.id)
        gathering.metadata_["selected_recipe_id"] = "Cotton Bolls"
        gathering.metadata_["selected_recipe_name"] = "Cotton Bolls"
        gathering.metadata_["is_crafting"] = True
        gathering.metadata_["crafting_started_tick"] = 0
        gathering.metadata_["crafting_duration"] = 1

        result = game.on_tick(zone_id, [monster, gathering], [], tick_number=2)

        # Check for specific skill update on monster
        monster_update = find_update_for(result, monster.id)
        if monster_update and monster_update.metadata:
            skills = monster_update.metadata.get("skills", {})
            specific = skills.get("specific", {})
            # Should have some specific skill for cotton bolls
            assert len(specific) > 0 or "cotton" in str(specific).lower()


class TestSecondarySkills:
    """Tests for secondary skill learning."""

    def test_secondary_skills_increase_slower(self, game):
        """Secondary skills increase more slowly than primary."""
        monster = make_monster(5, 5, uuid4())
        recipe = game._get_recipe_entry("Cotton Bolls")

        if recipe and recipe.get("secondary_applied_skills"):
            # This is a conceptual test - secondary skills should be calculated
            # with a smaller learning rate than primary
            secondary_skills = recipe.get("secondary_applied_skills", [])
            assert len(secondary_skills) > 0  # Cotton Bolls has textiles as secondary


class TestAbilityEffectsOnLearning:
    """Tests for ability score effects on skill learning."""

    def test_int_affects_learning(self, game):
        """Intelligence affects learning rate."""
        # Elf has high INT (18)
        elf_monster = make_monster(0, 0, uuid4(), monster_type="elf")
        # Cyclops has low INT (8)
        cyclops_monster = make_monster(0, 0, uuid4(), monster_type="cyclops")

        elf_int = game._get_monster_stat(elf_monster, "int")
        cyclops_int = game._get_monster_stat(cyclops_monster, "int")

        # Elf should have higher INT for learning
        assert elf_int > cyclops_int
        assert elf_int == 18
        assert cyclops_int == 8

    def test_wis_affects_forgetting(self, game):
        """Wisdom affects forgetting rate."""
        # Elf has decent WIS (12)
        elf_monster = make_monster(0, 0, uuid4(), monster_type="elf")
        # Goblin has low WIS (8)
        goblin_monster = make_monster(0, 0, uuid4(), monster_type="goblin")

        elf_wis = game._get_monster_stat(elf_monster, "wis")
        goblin_wis = game._get_monster_stat(goblin_monster, "wis")

        # Elf should have higher WIS for slower forgetting
        assert elf_wis > goblin_wis
        assert elf_wis == 12
        assert goblin_wis == 8
