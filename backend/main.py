"""Monster Workshop - Main FastAPI Application.

A cooperative crafting game with roguelike/ASCII aesthetic.
Server-authoritative architecture using gridtickmultiplayer patterns.
"""

import asyncio
import secrets
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import init_db, get_session, async_session
from models.player import Player, Session, Commune
from models.monster import Monster, MONSTER_TYPES
from models.zone import Zone, Entity

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# FastAPI app
app = FastAPI(
    title="Monster Workshop",
    description="A cooperative crafting game with Sokoban-like mechanics",
    version="0.1.0"
)

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Game configuration
GAME_TIME_MULTIPLIER = 30  # 1 real second = 30 game seconds


# =============================================================================
# Pydantic Models for API
# =============================================================================

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    player_id: str
    username: str


class PlayerInfo(BaseModel):
    id: str
    username: str
    commune_id: Optional[str]
    commune_name: Optional[str]
    renown: Optional[str]


class ZoneInfo(BaseModel):
    id: str
    name: str
    zone_type: str
    width: int
    height: int


class ZoneDetail(ZoneInfo):
    terrain_data: Optional[dict]
    metadata: Optional[dict]


class ErrorResponse(BaseModel):
    detail: str


# =============================================================================
# Dependency: Get current player from session token
# =============================================================================

async def get_current_player(token: str, session: AsyncSession) -> Player:
    """Validate session token and return the associated player."""
    result = await session.execute(
        select(Session).where(Session.token == token)
    )
    db_session = result.scalar_one_or_none()

    if not db_session:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Check expiration if set
    if db_session.expires_at and db_session.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Token expired")

    result = await session.execute(
        select(Player).where(Player.id == db_session.player_id)
    )
    player = result.scalar_one_or_none()

    if not player:
        raise HTTPException(status_code=401, detail="Player not found")

    return player


# =============================================================================
# Startup Event
# =============================================================================

@app.on_event("startup")
async def startup():
    """Initialize database and game state on startup."""
    await init_db()
    print("Monster Workshop server started!")
    print(f"Game time multiplier: {GAME_TIME_MULTIPLIER}x")


# =============================================================================
# Authentication Endpoints
# =============================================================================

@app.post("/api/auth/register", response_model=AuthResponse, tags=["Authentication"])
async def register(request: RegisterRequest):
    """Register a new player account."""
    async with async_session() as session:
        # Check if username exists
        result = await session.execute(
            select(Player).where(Player.username == request.username)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already exists"
            )

        # Create player
        password_hash = pwd_context.hash(request.password)
        player = Player(
            username=request.username,
            password_hash=password_hash
        )
        session.add(player)
        await session.flush()

        # Create commune for player
        commune = Commune(
            player_id=player.id,
            name=f"{request.username}'s Commune",
            renown="1000"
        )
        session.add(commune)

        # Create session token
        token = secrets.token_hex(32)
        db_session = Session(
            player_id=player.id,
            token=token
        )
        session.add(db_session)

        await session.commit()

        return AuthResponse(
            token=token,
            player_id=player.id,
            username=player.username
        )


@app.post("/api/auth/login", response_model=AuthResponse, tags=["Authentication"])
async def login(request: LoginRequest):
    """Login with username and password."""
    async with async_session() as session:
        result = await session.execute(
            select(Player).where(Player.username == request.username)
        )
        player = result.scalar_one_or_none()

        if not player or not pwd_context.verify(request.password, player.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )

        # Update last login
        player.last_login = datetime.utcnow()

        # Create new session token
        token = secrets.token_hex(32)
        db_session = Session(
            player_id=player.id,
            token=token
        )
        session.add(db_session)
        await session.commit()

        return AuthResponse(
            token=token,
            player_id=player.id,
            username=player.username
        )


@app.post("/api/auth/logout", tags=["Authentication"])
async def logout(token: str):
    """Logout and invalidate session token."""
    async with async_session() as session:
        result = await session.execute(
            select(Session).where(Session.token == token)
        )
        db_session = result.scalar_one_or_none()

        if db_session:
            await session.delete(db_session)
            await session.commit()

        return {"message": "Logged out successfully"}


@app.get("/api/auth/me", response_model=PlayerInfo, tags=["Authentication"])
async def get_me(token: str):
    """Get current player information."""
    async with async_session() as session:
        player = await get_current_player(token, session)

        # Get commune info
        result = await session.execute(
            select(Commune).where(Commune.player_id == player.id)
        )
        commune = result.scalar_one_or_none()

        return PlayerInfo(
            id=player.id,
            username=player.username,
            commune_id=commune.id if commune else None,
            commune_name=commune.name if commune else None,
            renown=commune.renown if commune else None
        )


# =============================================================================
# Zone Endpoints
# =============================================================================

@app.get("/api/zones", response_model=list[ZoneInfo], tags=["Zones"])
async def list_zones():
    """List all available zones."""
    async with async_session() as session:
        result = await session.execute(select(Zone))
        zones = result.scalars().all()

        return [
            ZoneInfo(
                id=zone.id,
                name=zone.name,
                zone_type=zone.zone_type,
                width=zone.width,
                height=zone.height
            )
            for zone in zones
        ]


@app.get("/api/zones/{zone_id}", response_model=ZoneDetail, tags=["Zones"])
async def get_zone(zone_id: str):
    """Get detailed zone information."""
    async with async_session() as session:
        result = await session.execute(
            select(Zone).where(Zone.id == zone_id)
        )
        zone = result.scalar_one_or_none()

        if not zone:
            raise HTTPException(status_code=404, detail="Zone not found")

        return ZoneDetail(
            id=zone.id,
            name=zone.name,
            zone_type=zone.zone_type,
            width=zone.width,
            height=zone.height,
            terrain_data=zone.terrain_data,
            metadata=zone.metadata
        )


# =============================================================================
# Debug Endpoints (Development Only)
# =============================================================================

# Tick engine state
tick_engine_running = True
current_tick = 0


@app.post("/api/debug/tick/pause", tags=["Debug"])
async def pause_tick():
    """Pause the tick engine."""
    global tick_engine_running
    tick_engine_running = False
    return {"message": "Tick engine paused", "running": False}


@app.post("/api/debug/tick/resume", tags=["Debug"])
async def resume_tick():
    """Resume the tick engine."""
    global tick_engine_running
    tick_engine_running = True
    return {"message": "Tick engine resumed", "running": True}


@app.post("/api/debug/tick/step", tags=["Debug"])
async def step_tick():
    """Advance by a single tick."""
    global current_tick
    current_tick += 1
    # TODO: Process tick logic
    return {"message": "Stepped one tick", "tick_number": current_tick}


@app.get("/api/debug/zones/{zone_id}/state", tags=["Debug"])
async def get_zone_state(zone_id: str):
    """Get complete zone state for debugging."""
    async with async_session() as session:
        result = await session.execute(
            select(Zone).where(Zone.id == zone_id)
        )
        zone = result.scalar_one_or_none()

        if not zone:
            raise HTTPException(status_code=404, detail="Zone not found")

        # Get all entities in zone
        result = await session.execute(
            select(Entity).where(Entity.zone_id == zone_id)
        )
        entities = result.scalars().all()

        # Get all monsters in zone
        result = await session.execute(
            select(Monster).where(Monster.current_zone_id == zone_id)
        )
        monsters = result.scalars().all()

        return {
            "zone": {
                "id": zone.id,
                "name": zone.name,
                "zone_type": zone.zone_type,
                "width": zone.width,
                "height": zone.height
            },
            "entities": [
                {
                    "id": e.id,
                    "type": e.entity_type,
                    "x": e.x,
                    "y": e.y,
                    "width": e.width,
                    "height": e.height,
                    "metadata": e.metadata
                }
                for e in entities
            ],
            "monsters": [
                {
                    "id": m.id,
                    "name": m.name,
                    "type": m.monster_type,
                    "x": m.x,
                    "y": m.y
                }
                for m in monsters
            ]
        }


@app.get("/api/debug/entities/{entity_id}", tags=["Debug"])
async def get_entity(entity_id: str):
    """Get detailed entity information."""
    async with async_session() as session:
        result = await session.execute(
            select(Entity).where(Entity.id == entity_id)
        )
        entity = result.scalar_one_or_none()

        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")

        return {
            "id": entity.id,
            "zone_id": entity.zone_id,
            "entity_type": entity.entity_type,
            "x": entity.x,
            "y": entity.y,
            "width": entity.width,
            "height": entity.height,
            "owner_id": entity.owner_id,
            "metadata": entity.metadata,
            "created_at": entity.created_at.isoformat(),
            "updated_at": entity.updated_at.isoformat()
        }


@app.get("/api/debug/connections", tags=["Debug"])
async def get_connections():
    """Get list of connected players."""
    # TODO: Track actual WebSocket connections
    return {"connections": [], "count": 0}


# =============================================================================
# WebSocket Game Connection
# =============================================================================

# Track active connections
active_connections: dict[str, WebSocket] = {}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = None):
    """Main WebSocket connection for game communication."""
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    async with async_session() as session:
        try:
            player = await get_current_player(token, session)
        except HTTPException:
            await websocket.close(code=4001, reason="Invalid token")
            return

        await websocket.accept()
        active_connections[player.id] = websocket

        try:
            await websocket.send_json({
                "type": "connected",
                "player_id": player.id,
                "username": player.username
            })

            while True:
                data = await websocket.receive_json()
                await handle_websocket_message(player.id, data, websocket, session)

        except WebSocketDisconnect:
            pass
        finally:
            if player.id in active_connections:
                del active_connections[player.id]


async def handle_websocket_message(player_id: str, data: dict, websocket: WebSocket, session: AsyncSession):
    """Handle incoming WebSocket messages."""
    msg_type = data.get("type")

    if msg_type == "subscribe":
        zone_id = data.get("zone_id")
        # TODO: Implement zone subscription
        await websocket.send_json({
            "type": "subscribed",
            "zone_id": zone_id
        })

    elif msg_type == "intent":
        intent_data = data.get("data", {})
        action = intent_data.get("action")

        # TODO: Process intents through game logic module
        # For now, acknowledge receipt
        await websocket.send_json({
            "type": "intent_received",
            "action": action
        })

    else:
        await websocket.send_json({
            "type": "error",
            "message": f"Unknown message type: {msg_type}"
        })


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
