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
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from pydantic import BaseModel, Field, field_validator
import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import init_db, get_session, async_session
from models.player import Player, Session, Commune
from models.monster import Monster, MONSTER_TYPES
from models.zone import Zone, Entity


# Password hashing functions using bcrypt directly
def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a hash."""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

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

# Static files serving
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Game configuration
GAME_TIME_MULTIPLIER = 30  # 1 real second = 30 game seconds


# =============================================================================
# Pydantic Models for API
# =============================================================================

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)

    @field_validator('username')
    @classmethod
    def username_not_whitespace(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError('Username cannot be empty or whitespace only')
        return stripped


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


class MonsterTypeInfo(BaseModel):
    name: str
    cost: int
    body_cap: int
    mind_cap: int
    base_stats: dict


class MonsterInfo(BaseModel):
    id: str
    name: str
    monster_type: str
    str_: int
    dex: int
    con: int
    int_: int
    wis: int
    cha: int
    body_fitting_used: int
    mind_fitting_used: int
    current_zone_id: Optional[str]
    x: int
    y: int


class CreateMonsterRequest(BaseModel):
    monster_type: str
    name: str = Field(..., min_length=1, max_length=100)
    transferable_skills: list[str] = Field(default_factory=list, max_length=3)

    @field_validator('name')
    @classmethod
    def name_not_whitespace(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError('Monster name cannot be empty or whitespace only')
        return stripped


class SwitchMonsterRequest(BaseModel):
    monster_id: str


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

    # Create default starting zone if none exists
    async with async_session() as session:
        result = await session.execute(select(Zone))
        zones = result.scalars().all()

        if not zones:
            print("Creating default zones...")
            # Starting village
            starting_zone = Zone(
                name="Starting Village",
                zone_type="village",
                width=100,
                height=100,
                terrain_data={"default": "grass"},
                zone_metadata={"description": "A peaceful village to begin your journey"}
            )
            session.add(starting_zone)

            # Wilderness area
            wilderness_zone = Zone(
                name="Eastern Wilderness",
                zone_type="wilderness",
                width=150,
                height=150,
                terrain_data={"default": "forest"},
                zone_metadata={"description": "A dangerous wilderness area with rare materials"}
            )
            session.add(wilderness_zone)

            await session.commit()
            print(f"Created zones: {starting_zone.name}, {wilderness_zone.name}")

    print("Monster Workshop server started!")
    print(f"Game time multiplier: {GAME_TIME_MULTIPLIER}x")


@app.get("/", tags=["Root"])
async def root():
    """Serve the main web interface."""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


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
        password_hash = hash_password(request.password)
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

        if not player or not verify_password(request.password, player.password_hash):
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
            metadata=zone.zone_metadata
        )


# =============================================================================
# Monster Endpoints
# =============================================================================

@app.get("/api/monsters/types", response_model=list[MonsterTypeInfo], tags=["Monsters"])
async def get_monster_types():
    """Get all available monster types with their stats and costs."""
    return [
        MonsterTypeInfo(
            name=name,
            cost=data["cost"],
            body_cap=data["body_cap"],
            mind_cap=data["mind_cap"],
            base_stats=data["base_stats"]
        )
        for name, data in MONSTER_TYPES.items()
    ]


@app.get("/api/monsters", response_model=list[MonsterInfo], tags=["Monsters"])
async def get_player_monsters(token: str):
    """Get all monsters belonging to the current player's commune."""
    async with async_session() as session:
        player = await get_current_player(token, session)

        # Get player's commune
        result = await session.execute(
            select(Commune).where(Commune.player_id == player.id)
        )
        commune = result.scalar_one_or_none()

        if not commune:
            return []

        # Get all monsters for this commune
        result = await session.execute(
            select(Monster).where(Monster.commune_id == commune.id)
        )
        monsters = result.scalars().all()

        return [
            MonsterInfo(
                id=m.id,
                name=m.name,
                monster_type=m.monster_type,
                str_=m.str_,
                dex=m.dex,
                con=m.con,
                int_=m.int_,
                wis=m.wis,
                cha=m.cha,
                body_fitting_used=m.body_fitting_used,
                mind_fitting_used=m.mind_fitting_used,
                current_zone_id=m.current_zone_id,
                x=m.x,
                y=m.y
            )
            for m in monsters
        ]


@app.post("/api/monsters", response_model=MonsterInfo, tags=["Monsters"])
async def create_monster(request: CreateMonsterRequest, token: str):
    """Create a new monster for the player's commune."""
    async with async_session() as session:
        player = await get_current_player(token, session)

        # Validate monster type
        if request.monster_type not in MONSTER_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid monster type. Must be one of: {', '.join(MONSTER_TYPES.keys())}"
            )

        # Get player's commune
        result = await session.execute(
            select(Commune).where(Commune.player_id == player.id)
        )
        commune = result.scalar_one_or_none()

        if not commune:
            raise HTTPException(status_code=400, detail="Player has no commune")

        # Check if player has enough renown
        monster_cost = MONSTER_TYPES[request.monster_type]["cost"]
        current_renown = int(commune.renown)

        if current_renown < monster_cost:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough renown. Need {monster_cost}, have {current_renown}"
            )

        # Deduct cost
        commune.renown = str(current_renown - monster_cost)

        # Create the monster with base stats
        base_stats = MONSTER_TYPES[request.monster_type]["base_stats"]
        monster = Monster(
            commune_id=commune.id,
            monster_type=request.monster_type,
            name=request.name,
            str_=base_stats["str"],
            dex=base_stats["dex"],
            con=base_stats["con"],
            int_=base_stats["int"],
            wis=base_stats["wis"],
            cha=base_stats["cha"],
            transferable_skills=request.transferable_skills[:3]  # Max 3 skills
        )
        session.add(monster)
        await session.commit()
        await session.refresh(monster)

        return MonsterInfo(
            id=monster.id,
            name=monster.name,
            monster_type=monster.monster_type,
            str_=monster.str_,
            dex=monster.dex,
            con=monster.con,
            int_=monster.int_,
            wis=monster.wis,
            cha=monster.cha,
            body_fitting_used=monster.body_fitting_used,
            mind_fitting_used=monster.mind_fitting_used,
            current_zone_id=monster.current_zone_id,
            x=monster.x,
            y=monster.y
        )


@app.post("/api/monsters/switch", response_model=MonsterInfo, tags=["Monsters"])
async def switch_monster(request: SwitchMonsterRequest, token: str):
    """Switch to controlling a different monster. Players can only control their own monsters."""
    async with async_session() as session:
        player = await get_current_player(token, session)

        # Get the monster
        result = await session.execute(
            select(Monster).where(Monster.id == request.monster_id)
        )
        monster = result.scalar_one_or_none()

        if not monster:
            raise HTTPException(status_code=404, detail="Monster not found")

        # Get player's commune
        result = await session.execute(
            select(Commune).where(Commune.player_id == player.id)
        )
        commune = result.scalar_one_or_none()

        # Security check: Verify ownership
        if not commune or monster.commune_id != commune.id:
            raise HTTPException(
                status_code=403,
                detail="You can only control monsters belonging to your commune"
            )

        # TODO: Update active monster tracking
        # For now, just return the monster info to confirm the switch

        return MonsterInfo(
            id=monster.id,
            name=monster.name,
            monster_type=monster.monster_type,
            str_=monster.str_,
            dex=monster.dex,
            con=monster.con,
            int_=monster.int_,
            wis=monster.wis,
            cha=monster.cha,
            body_fitting_used=monster.body_fitting_used,
            mind_fitting_used=monster.mind_fitting_used,
            current_zone_id=monster.current_zone_id,
            x=monster.x,
            y=monster.y
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


class CreateZoneRequest(BaseModel):
    name: str
    zone_type: str = "village"
    width: int = 100
    height: int = 100


@app.post("/api/debug/zones", tags=["Debug"])
async def create_zone(request: CreateZoneRequest):
    """Create a new zone (debug only)."""
    async with async_session() as session:
        zone = Zone(
            name=request.name,
            zone_type=request.zone_type,
            width=request.width,
            height=request.height,
            terrain_data={"default": "grass" if request.zone_type == "village" else "forest"},
            zone_metadata={"description": f"A {request.zone_type} zone"}
        )
        session.add(zone)
        await session.commit()
        await session.refresh(zone)

        return {
            "id": zone.id,
            "name": zone.name,
            "zone_type": zone.zone_type,
            "width": zone.width,
            "height": zone.height
        }


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
                    "metadata": e.entity_metadata
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
            "metadata": entity.entity_metadata,
            "created_at": entity.created_at.isoformat(),
            "updated_at": entity.updated_at.isoformat()
        }


@app.get("/api/debug/connections", tags=["Debug"])
async def get_connections():
    """Get list of connected players."""
    # TODO: Track actual WebSocket connections
    return {"connections": [], "count": 0}


class CreateEntityRequest(BaseModel):
    zone_id: str
    entity_type: str
    x: int
    y: int
    width: int = 1
    height: int = 1
    metadata: Optional[dict] = None


@app.post("/api/debug/entities", tags=["Debug"])
async def create_entity(request: CreateEntityRequest):
    """Create an entity in a zone (debug only)."""
    async with async_session() as session:
        # Verify zone exists
        result = await session.execute(
            select(Zone).where(Zone.id == request.zone_id)
        )
        zone = result.scalar_one_or_none()

        if not zone:
            raise HTTPException(status_code=404, detail="Zone not found")

        entity = Entity(
            zone_id=request.zone_id,
            entity_type=request.entity_type,
            x=request.x,
            y=request.y,
            width=request.width,
            height=request.height,
            entity_metadata=request.metadata
        )
        session.add(entity)
        await session.commit()
        await session.refresh(entity)

        return {
            "id": entity.id,
            "zone_id": entity.zone_id,
            "entity_type": entity.entity_type,
            "x": entity.x,
            "y": entity.y,
            "width": entity.width,
            "height": entity.height,
            "metadata": entity.entity_metadata,
            "created_at": entity.created_at.isoformat(),
            "updated_at": entity.updated_at.isoformat()
        }


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
