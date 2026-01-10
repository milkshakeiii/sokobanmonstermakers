"""Zone and Entity models."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.sqlite import JSON

from .database import Base


class Zone(Base):
    """Game zone/area model."""

    __tablename__ = "zones"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), unique=True, nullable=False, index=True)
    zone_type = Column(String(20), nullable=False)  # village, wilderness, raw_material
    width = Column(Integer, nullable=False, default=100)
    height = Column(Integer, nullable=False, default=100)
    terrain_data = Column(JSON, nullable=True)  # Grid of terrain types
    metadata = Column(JSON, nullable=True)  # Zone-specific data

    # Relationships
    entities = relationship("Entity", back_populates="zone", cascade="all, delete-orphan")
    monsters = relationship("Monster", back_populates="zone")

    def __repr__(self):
        return f"<Zone(id={self.id}, name={self.name}, type={self.zone_type})>"


class Entity(Base):
    """Grid entity model (items, workshops, dispensers, etc.)."""

    __tablename__ = "entities"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    zone_id = Column(String(36), ForeignKey("zones.id"), nullable=False, index=True)
    entity_type = Column(String(30), nullable=False)  # item, workshop, dispenser, etc.
    x = Column(Integer, nullable=False)
    y = Column(Integer, nullable=False)
    width = Column(Integer, default=1)  # In cells
    height = Column(Integer, default=1)  # In cells

    # Ownership for share tracking
    owner_id = Column(String(36), nullable=True)  # Commune ID

    # Entity-specific data
    metadata = Column(JSON, nullable=True)  # quality, durability, contents, good_type, etc.

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    zone = relationship("Zone", back_populates="entities")

    def __repr__(self):
        return f"<Entity(id={self.id}, type={self.entity_type}, pos=({self.x},{self.y}))>"


# Entity types
ENTITY_TYPES = {
    "item": "A movable item on the grid",
    "workshop": "A 4x4+ crafting workshop",
    "dispenser": "Holds one item type, push in/out",
    "gathering_spot": "Raw material source (well, mine, etc.)",
    "signpost": "Zone transition marker",
    "delivery": "Scoring/delivery location",
    "tool": "A tool item with durability",
    "wagon": "Multi-cell transport vehicle"
}


class GoodType(Base):
    """Tech tree good type definition."""

    __tablename__ = "good_types"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    type_tags = Column(JSON, default=list)  # Array of tags
    storage_volume = Column(Integer, default=1)
    has_quality = Column(Integer, default=1)  # 0 or 1
    is_fixed_quantity = Column(Integer, default=0)  # 0 or 1
    requires_workshop = Column(String(100), nullable=True)
    relevant_ability_score = Column(String(3), nullable=True)  # STR, DEX, etc.
    transferable_skills = Column(JSON, default=list)
    primary_applied_skill = Column(String(100), nullable=True)
    secondary_applied_skills = Column(JSON, default=list)
    difficulty_rating = Column(Integer, default=1)
    production_time = Column(Integer, default=60)  # In game seconds
    value_added_shares = Column(Integer, default=1)
    quantity = Column(Integer, default=1)
    input_goods_tags_required = Column(JSON, default=list)
    tools_required_tags = Column(JSON, default=list)
    tools_weights = Column(JSON, default=dict)

    # Raw material fields
    raw_material_base_value = Column(Integer, nullable=True)
    raw_material_rarity = Column(Integer, nullable=True)
    raw_material_density = Column(Integer, nullable=True)

    def __repr__(self):
        return f"<GoodType(id={self.id}, name={self.name})>"


class EquipmentType(Base):
    """Equipment type definition."""

    __tablename__ = "equipment_types"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    cost = Column(Integer, default=0)
    body_fitting = Column(Integer, default=0)
    mind_fitting = Column(Integer, default=0)
    slot_type = Column(String(20), default="worn")  # worn, personal, internal
    effect = Column(JSON, default=dict)  # stat bonuses, production bonuses, etc.

    def __repr__(self):
        return f"<EquipmentType(id={self.id}, name={self.name})>"


class Share(Base):
    """Share tracking for economy system."""

    __tablename__ = "shares"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    entity_id = Column(String(36), nullable=False)  # The good's entity ID
    commune_id = Column(String(36), nullable=False)
    share_count = Column(Integer, default=1)
    contribution_type = Column(String(30), nullable=False)  # producer, tool_creator, transporter, input_supplier

    def __repr__(self):
        return f"<Share(entity={self.entity_id}, commune={self.commune_id}, type={self.contribution_type})>"
