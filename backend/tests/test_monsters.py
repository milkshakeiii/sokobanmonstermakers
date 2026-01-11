"""Tests for monster spawning and stats."""

import pytest
from uuid import uuid4
from datetime import datetime, timedelta

from conftest import (
    make_monster,
    make_intent,
    find_event,
    get_monster_stats,
    MockEntity,
)

VALID_TRANSFERABLE = ["handcrafts", "athletics", "outdoorsmonstership"]


class TestSpawnMonster:
    """Tests for the spawn_monster intent."""

    def test_spawn_goblin(self, game, zone_id, player_id, setup_zone):
        """Spawn a goblin with correct base stats."""
        intent = make_intent(
            player_id, "spawn_monster",
            monster_type="goblin",
            name="TestGoblin",
            transferable_skills=VALID_TRANSFERABLE,
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        # Should create monster and commune
        assert len(result.entity_creates) >= 1
        monster_create = next(
            (c for c in result.entity_creates if c.metadata.get("kind") == "monster"),
            None
        )
        assert monster_create is not None
        assert monster_create.metadata["monster_type"] == "goblin"
        assert monster_create.metadata["name"] == "TestGoblin"
        stats = monster_create.metadata["stats"]
        assert stats["dex"] == 18  # Goblin primary stat
        assert stats["cha"] == 16  # Goblin secondary stat

    def test_spawn_cyclops(self, game, zone_id, player_id, setup_zone):
        """Spawn a cyclops with correct base stats."""
        intent = make_intent(
            player_id, "spawn_monster",
            monster_type="cyclops",
            name="BigGuy",
            transferable_skills=VALID_TRANSFERABLE,
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        monster_create = next(
            (c for c in result.entity_creates if c.metadata.get("kind") == "monster"),
            None
        )
        assert monster_create is not None
        stats = monster_create.metadata["stats"]
        assert stats["str"] == 18  # Cyclops primary stat
        assert stats["con"] == 16  # Cyclops secondary stat

    def test_spawn_elf(self, game, zone_id, player_id, setup_zone):
        """Spawn an elf with correct base stats."""
        intent = make_intent(
            player_id, "spawn_monster",
            monster_type="elf",
            name="Legolas",
            transferable_skills=VALID_TRANSFERABLE,
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        monster_create = next(
            (c for c in result.entity_creates if c.metadata.get("kind") == "monster"),
            None
        )
        assert monster_create is not None
        stats = monster_create.metadata["stats"]
        assert stats["int"] == 18  # Elf primary stat
        assert stats["dex"] == 16  # Elf secondary stat

    def test_spawn_orc_requires_high_renown(self, game, zone_id, player_id, setup_zone):
        """Spawning an orc requires 2000 renown (more than starting 1000)."""
        intent = make_intent(
            player_id, "spawn_monster",
            monster_type="orc",
            name="Grommash",
            transferable_skills=VALID_TRANSFERABLE,
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        # Orc costs 2000, starting renown is 1000, so should fail
        error_event = find_event(result, "error")
        assert error_event is not None
        assert "Not enough renown" in error_event["message"]

    def test_spawn_troll(self, game, zone_id, player_id, setup_zone):
        """Spawn a troll with correct base stats."""
        intent = make_intent(
            player_id, "spawn_monster",
            monster_type="troll",
            name="BigTroll",
            transferable_skills=VALID_TRANSFERABLE,
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        monster_create = next(
            (c for c in result.entity_creates if c.metadata.get("kind") == "monster"),
            None
        )
        assert monster_create is not None
        stats = monster_create.metadata["stats"]
        assert stats["str"] == 12
        assert stats["con"] == 14

    def test_spawn_invalid_type(self, game, zone_id, player_id, setup_zone):
        """Spawning unknown monster type returns error."""
        intent = make_intent(
            player_id, "spawn_monster",
            monster_type="dragon",
            name="Smaug",
            transferable_skills=VALID_TRANSFERABLE,
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        # Should have no monster created
        monster_creates = [c for c in result.entity_creates if c.metadata.get("kind") == "monster"]
        assert len(monster_creates) == 0

        # Should have error event
        error_event = find_event(result, "error")
        assert error_event is not None
        assert "Unknown monster type" in error_event["message"]

    def test_spawn_default_type(self, game, zone_id, player_id, setup_zone):
        """Spawning without type defaults to goblin."""
        intent = make_intent(
            player_id, "spawn_monster",
            name="DefaultMonster",
            transferable_skills=VALID_TRANSFERABLE,
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        monster_create = next(
            (c for c in result.entity_creates if c.metadata.get("kind") == "monster"),
            None
        )
        assert monster_create is not None
        assert monster_create.metadata["monster_type"] == "goblin"


class TestTransferableSkills:
    """Tests for transferable skills on spawn."""

    def test_spawn_with_valid_skills(self, game, zone_id, player_id, setup_zone):
        """Monster can be spawned with valid transferable skills."""
        intent = make_intent(
            player_id, "spawn_monster",
            monster_type="goblin",
            transferable_skills=["handcrafts", "athletics", "outdoorsmonstership"],
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        monster_create = next(
            (c for c in result.entity_creates if c.metadata.get("kind") == "monster"),
            None
        )
        assert monster_create is not None
        skills = monster_create.metadata.get("skills", {})
        transferable = skills.get("transferable", [])
        assert len(transferable) == 3
        assert "handcrafts" in transferable
        assert "athletics" in transferable

    def test_spawn_with_invalid_skills(self, game, zone_id, player_id, setup_zone):
        """Spawning with invalid skills returns error."""
        intent = make_intent(
            player_id, "spawn_monster",
            monster_type="goblin",
            transferable_skills=["flying", "telekinesis", "handcrafts"],
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        # Should have no monster created
        monster_creates = [c for c in result.entity_creates if c.metadata.get("kind") == "monster"]
        assert len(monster_creates) == 0

        # Should have error event
        error_event = find_event(result, "error")
        assert error_event is not None
        assert "Invalid transferable skills" in error_event["message"]

    def test_spawn_too_many_skills(self, game, zone_id, player_id, setup_zone):
        """Cannot spawn with more than 3 transferable skills."""
        intent = make_intent(
            player_id, "spawn_monster",
            monster_type="goblin",
            transferable_skills=["handcrafts", "athletics", "outdoorsmonstership", "mathematics"],
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        # Should have error event
        error_event = find_event(result, "error")
        assert error_event is not None
        assert "exactly 3" in error_event["message"]

    def test_spawn_duplicate_skills(self, game, zone_id, player_id, setup_zone):
        """Cannot spawn with duplicate transferable skills."""
        intent = make_intent(
            player_id, "spawn_monster",
            monster_type="goblin",
            transferable_skills=["handcrafts", "handcrafts", "athletics"],
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        error_event = find_event(result, "error")
        assert error_event is not None
        assert "Duplicate" in error_event["message"]

    def test_spawn_skills_not_list(self, game, zone_id, player_id, setup_zone):
        """Transferable skills must be a list."""
        intent = make_intent(
            player_id, "spawn_monster",
            monster_type="goblin",
            transferable_skills="handcrafts",  # String instead of list
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        error_event = find_event(result, "error")
        assert error_event is not None
        assert "must be a list" in error_event["message"]


class TestMonsterOwnership:
    """Tests for monster ownership."""

    def test_monster_owned_by_spawner(self, game, zone_id, player_id, setup_zone):
        """Spawned monster is owned by the spawning player."""
        intent = make_intent(
            player_id,
            "spawn_monster",
            monster_type="goblin",
            transferable_skills=VALID_TRANSFERABLE,
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        monster_create = next(
            (c for c in result.entity_creates if c.metadata.get("kind") == "monster"),
            None
        )
        assert monster_create is not None
        assert monster_create.owner_id == player_id


class TestMonsterStats:
    """Tests for monster stat calculations."""

    # ABILITY_KEYS = ("str", "dex", "con", "int", "wis", "cha")
    # Indices:         0      1      2      3      4      5

    def test_get_monster_stat(self, game):
        """Test direct stat retrieval."""
        monster = make_monster(0, 0, uuid4(), monster_type="cyclops")
        stat = game._get_monster_stat(monster, "str")
        assert stat == 18

    def test_effective_ability_no_age_bonus(self, game):
        """Monster under 30 days gets no age bonus."""
        monster = make_monster(0, 0, uuid4(), monster_type="goblin")
        # Set created_at to now (less than 30 days old)
        monster.metadata_["created_at"] = datetime.utcnow().isoformat()

        # _effective_ability takes an index: 1 = dex
        effective = game._effective_ability(monster, 1)
        assert effective == 18  # Base stat (goblin dex=18), no bonus

    def test_effective_ability_30_day_bonus(self, game):
        """Monster 30+ days old gets +1 to all stats."""
        monster = make_monster(0, 0, uuid4(), monster_type="goblin")
        # Set created_at to 31 days ago
        old_date = datetime.utcnow() - timedelta(days=31)
        monster.metadata_["created_at"] = old_date.isoformat()

        effective = game._effective_ability(monster, 1)  # dex
        assert effective == 19  # Base 18 + 1 age bonus

    def test_effective_ability_60_day_bonus(self, game):
        """Monster 60+ days old gets +2 to all stats."""
        monster = make_monster(0, 0, uuid4(), monster_type="goblin")
        # Set created_at to 61 days ago
        old_date = datetime.utcnow() - timedelta(days=61)
        monster.metadata_["created_at"] = old_date.isoformat()

        effective = game._effective_ability(monster, 1)  # dex
        assert effective == 20  # Base 18 + 2 age bonus


class TestMonsterCapacity:
    """Tests for monster body/mind capacity."""

    def test_cyclops_capacity(self, game, zone_id, player_id, setup_zone):
        """Cyclops has balanced body/mind capacity."""
        intent = make_intent(
            player_id,
            "spawn_monster",
            monster_type="cyclops",
            transferable_skills=VALID_TRANSFERABLE,
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        monster_create = next(
            (c for c in result.entity_creates if c.metadata.get("kind") == "monster"),
            None
        )
        assert monster_create is not None
        # Cyclops: body_cap=100, mind_cap=100

    def test_troll_high_capacity(self, game, zone_id, player_id, setup_zone):
        """Troll has very high capacity for equipment."""
        intent = make_intent(
            player_id,
            "spawn_monster",
            monster_type="troll",
            transferable_skills=VALID_TRANSFERABLE,
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        monster_create = next(
            (c for c in result.entity_creates if c.metadata.get("kind") == "monster"),
            None
        )
        assert monster_create is not None
        # Troll: body_cap=1500, mind_cap=1500 (from monster_types.json)


class TestSpawnEvent:
    """Tests for spawn events."""

    def test_spawn_emits_event(self, game, zone_id, player_id, setup_zone):
        """Successful spawn emits a spawned event."""
        intent = make_intent(
            player_id,
            "spawn_monster",
            monster_type="goblin",
            name="TestGob",
            transferable_skills=VALID_TRANSFERABLE,
        )

        result = game.on_tick(zone_id, [], [intent], tick_number=1)

        spawned_event = find_event(result, "spawned")
        assert spawned_event is not None
        assert "TestGob" in spawned_event["message"]
        assert spawned_event["target_player_id"] == str(player_id)
