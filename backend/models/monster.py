"""Monster model and related entities."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.sqlite import JSON

from .database import Base


class Monster(Base):
    """Monster entity controlled by player."""

    __tablename__ = "monsters"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    commune_id = Column(String(36), ForeignKey("communes.id"), nullable=False)
    monster_type = Column(String(20), nullable=False)  # Cyclops, Elf, Goblin, Orc, Troll
    name = Column(String(100), nullable=False)

    # Ability scores (1-18 scale)
    str_ = Column("str", Integer, default=10)  # str is reserved keyword
    dex = Column(Integer, default=10)
    con = Column(Integer, default=10)
    int_ = Column("int", Integer, default=10)  # int is reserved keyword
    wis = Column(Integer, default=10)
    cha = Column(Integer, default=10)

    # Equipment capacity
    body_fitting_used = Column(Integer, default=0)
    mind_fitting_used = Column(Integer, default=0)

    # Skills (stored as JSON)
    transferable_skills = Column(JSON, default=list)  # Array of 3 skill names
    applied_skills = Column(JSON, default=dict)  # skill_name -> value (0-1)
    specific_skills = Column(JSON, default=dict)  # good_type -> value (0-1)
    skill_last_used = Column(JSON, default=dict)  # skill_name -> ISO timestamp of last use

    # Position and state
    current_zone_id = Column(String(36), ForeignKey("zones.id"), nullable=True)
    x = Column(Integer, default=0)
    y = Column(Integer, default=0)
    current_task = Column(JSON, nullable=True)  # Recording, auto-repeat state

    created_at = Column(DateTime, default=datetime.utcnow)  # For aging calculation

    # Relationships
    commune = relationship("Commune", back_populates="monsters")
    zone = relationship("Zone", back_populates="monsters")

    def __repr__(self):
        return f"<Monster(id={self.id}, name={self.name}, type={self.monster_type})>"

    @property
    def age_days(self) -> int:
        """Calculate monster age in game days."""
        # Game time: 1 real second = 30 game seconds
        # So 1 real day = 30 game days (approximately)
        delta = datetime.utcnow() - self.created_at
        real_seconds = delta.total_seconds()
        game_seconds = real_seconds * 30  # GAME_TIME_MULTIPLIER
        game_days = game_seconds / (24 * 60 * 60)
        return int(game_days)

    @property
    def age_bonus(self) -> int:
        """Calculate stat bonus from aging."""
        days = self.age_days
        if days >= 60:
            return 2
        elif days >= 30:
            return 1
        return 0


# Transferable skills that can be chosen at monster creation
# Based on MonsterMakers economy - these are skills that provide bonuses to crafting
TRANSFERABLE_SKILLS = [
    "Weaving",
    "Dyeing",
    "Pottery",
    "Smithing",
    "Carpentry",
    "Cooking",
    "Mining",
    "Farming",
    "Fishing",
    "Hunting",
    "Tailoring",
    "Leatherworking",
    "Glassblowing",
    "Jewelcrafting",
    "Alchemy",
    "Brewing",
    "Masonry",
    "Woodcutting",
]

# Monster type definitions
MONSTER_TYPES = {
    "Cyclops": {
        "cost": 100,
        "body_cap": 100,
        "mind_cap": 100,
        "base_stats": {"str": 18, "dex": 10, "con": 16, "int": 8, "wis": 10, "cha": 8}
    },
    "Elf": {
        "cost": 150,
        "body_cap": 50,
        "mind_cap": 150,
        "base_stats": {"str": 8, "dex": 16, "con": 10, "int": 18, "wis": 12, "cha": 10}
    },
    "Goblin": {
        "cost": 50,
        "body_cap": 150,
        "mind_cap": 50,
        "base_stats": {"str": 8, "dex": 18, "con": 10, "int": 10, "wis": 8, "cha": 16}
    },
    "Orc": {
        "cost": 2000,
        "body_cap": 150,
        "mind_cap": 50,
        "base_stats": {"str": 16, "dex": 10, "con": 18, "int": 8, "wis": 10, "cha": 8}
    },
    "Troll": {
        "cost": 1,
        "body_cap": 1500,
        "mind_cap": 1500,
        "base_stats": {"str": 12, "dex": 8, "con": 14, "int": 8, "wis": 10, "cha": 8}
    }
}
