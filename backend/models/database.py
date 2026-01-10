"""Database configuration and connection management."""

import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

# Database URL - using SQLite for simplicity
DATABASE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "monster_workshop.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DATABASE_PATH}"

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL logging
    future=True
)

# Create session factory
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Base class for all models
Base = declarative_base()


async def init_db():
    """Initialize the database, creating all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Run migrations for schema updates
    await run_migrations()


async def run_migrations():
    """Run database migrations for schema updates."""
    async with async_session() as session:
        # Migration 1: Add skill_last_used column to monsters table if it doesn't exist
        try:
            await session.execute(text("SELECT skill_last_used FROM monsters LIMIT 1"))
        except Exception:
            # Column doesn't exist, add it
            try:
                await session.execute(
                    text("ALTER TABLE monsters ADD COLUMN skill_last_used TEXT DEFAULT '{}'")
                )
                await session.commit()
                print("Migration: Added skill_last_used column to monsters table")
            except Exception as e:
                print(f"Migration warning: {e}")


async def get_session() -> AsyncSession:
    """Get a database session."""
    async with async_session() as session:
        yield session
