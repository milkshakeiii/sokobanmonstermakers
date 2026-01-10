"""Player and authentication models."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.sqlite import JSON

from .database import Base


class Player(Base):
    """Player account model."""

    __tablename__ = "players"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)

    # Relationships
    sessions = relationship("Session", back_populates="player", cascade="all, delete-orphan")
    commune = relationship("Commune", back_populates="player", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Player(id={self.id}, username={self.username})>"


class Session(Base):
    """Player session for authentication."""

    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    player_id = Column(String(36), ForeignKey("players.id"), nullable=False)
    token = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)  # None = never expires

    # Relationships
    player = relationship("Player", back_populates="sessions")

    def __repr__(self):
        return f"<Session(id={self.id}, player_id={self.player_id})>"


class Commune(Base):
    """Player's commune - holds monsters and renown."""

    __tablename__ = "communes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    player_id = Column(String(36), ForeignKey("players.id"), nullable=False)
    name = Column(String(100), nullable=False)
    renown = Column(String(20), default="1000")  # Stored as string for precision
    total_renown_spent = Column(String(20), default="0")
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    player = relationship("Player", back_populates="commune")
    monsters = relationship("Monster", back_populates="commune", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Commune(id={self.id}, name={self.name})>"
