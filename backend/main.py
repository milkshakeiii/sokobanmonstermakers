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
from models.monster import Monster, MONSTER_TYPES, TRANSFERABLE_SKILLS
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
                terrain_data={
                    "default": "grass",
                    "blocked": [[1, 0], [0, 1], [2, 0], [0, 2]]  # Some blocked cells near origin for testing
                },
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


class UpdateZoneTerrainRequest(BaseModel):
    terrain_data: dict


@app.put("/api/zones/{zone_id}/terrain", tags=["Zones"])
async def update_zone_terrain(zone_id: str, request: UpdateZoneTerrainRequest):
    """Update zone terrain data (for testing/admin purposes)."""
    async with async_session() as session:
        result = await session.execute(
            select(Zone).where(Zone.id == zone_id)
        )
        zone = result.scalar_one_or_none()

        if not zone:
            raise HTTPException(status_code=404, detail="Zone not found")

        zone.terrain_data = request.terrain_data
        await session.commit()

        return {"message": "Terrain updated", "zone_id": zone_id}


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


@app.get("/api/monsters/skills", tags=["Monsters"])
async def get_transferable_skills():
    """Get all available transferable skills that can be chosen at monster creation."""
    return {"skills": TRANSFERABLE_SKILLS}


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

        # Validate transferable skills
        if len(request.transferable_skills) > 3:
            raise HTTPException(
                status_code=400,
                detail="Cannot select more than 3 transferable skills"
            )

        # Check for invalid skills
        invalid_skills = [s for s in request.transferable_skills if s not in TRANSFERABLE_SKILLS]
        if invalid_skills:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid transferable skills: {', '.join(invalid_skills)}"
            )

        # Check for duplicate skills
        if len(request.transferable_skills) != len(set(request.transferable_skills)):
            raise HTTPException(
                status_code=400,
                detail="Cannot select the same skill twice"
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

        # Get starting zone (first village zone)
        result = await session.execute(
            select(Zone).where(Zone.zone_type == "village").limit(1)
        )
        starting_zone = result.scalar_one_or_none()

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
            transferable_skills=request.transferable_skills[:3],  # Max 3 skills
            current_zone_id=starting_zone.id if starting_zone else None,
            x=5,  # Start at position (5,5) to avoid blocked cells at origin
            y=5
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


class MoveMonsterRequest(BaseModel):
    monster_id: str
    direction: str  # up, down, left, right


def is_terrain_blocked(terrain_data: dict, x: int, y: int) -> bool:
    """Check if a terrain cell is blocked (not walkable)."""
    # Terrain data can be:
    # - {"default": "grass"} - simple default for entire zone
    # - {"default": "grass", "blocked": [[x1,y1], [x2,y2]...]} - default + blocked cells
    # - {"grid": [[row0], [row1]...]} - full grid of terrain types

    blocked_types = ["wall", "water", "blocked", "rock", "void"]

    if not terrain_data:
        return False

    # Check if there's a list of blocked cells
    if "blocked" in terrain_data:
        blocked_cells = terrain_data.get("blocked", [])
        for cell in blocked_cells:
            if len(cell) >= 2 and cell[0] == x and cell[1] == y:
                return True

    # Check if there's a full grid
    if "grid" in terrain_data:
        grid = terrain_data["grid"]
        if 0 <= y < len(grid) and 0 <= x < len(grid[y]):
            return grid[y][x] in blocked_types

    return False


@app.post("/api/monsters/move", response_model=MonsterInfo, tags=["Monsters"])
async def move_monster(request: MoveMonsterRequest, token: str):
    """Move a monster one cell in the specified direction."""
    async with async_session() as session:
        player = await get_current_player(token, session)

        # Validate direction
        valid_directions = ["up", "down", "left", "right"]
        if request.direction not in valid_directions:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid direction. Must be one of: {', '.join(valid_directions)}"
            )

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

        # Calculate new position (one cell at a time)
        new_x, new_y = monster.x, monster.y
        if request.direction == "up":
            new_y -= 1
        elif request.direction == "down":
            new_y += 1
        elif request.direction == "left":
            new_x -= 1
        elif request.direction == "right":
            new_x += 1

        # Get zone for collision detection
        zone = None
        if monster.current_zone_id:
            result = await session.execute(
                select(Zone).where(Zone.id == monster.current_zone_id)
            )
            zone = result.scalar_one_or_none()

        # Get zone dimensions (default 100x100)
        zone_width = zone.width if zone else 100
        zone_height = zone.height if zone else 100

        # Boundary checking
        if new_x < 0 or new_y < 0 or new_x >= zone_width or new_y >= zone_height:
            # Can't move outside zone bounds - return current position
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

        # Check terrain collision
        terrain_data = zone.terrain_data if zone else None
        if is_terrain_blocked(terrain_data, new_x, new_y):
            # Can't move into blocked terrain - return current position
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

        # Check for item at target position (for pushing)
        if monster.current_zone_id:
            result = await session.execute(
                select(Entity).where(
                    Entity.zone_id == monster.current_zone_id,
                    Entity.x == new_x,
                    Entity.y == new_y,
                    Entity.entity_type == "item"
                )
            )
            item_at_target = result.scalar_one_or_none()

            if item_at_target:
                # Calculate where the item would be pushed to
                push_x, push_y = new_x, new_y
                if request.direction == "up":
                    push_y -= 1
                elif request.direction == "down":
                    push_y += 1
                elif request.direction == "left":
                    push_x -= 1
                elif request.direction == "right":
                    push_x += 1

                # Check if push destination is valid
                # 1. Not out of bounds
                if push_x < 0 or push_y < 0 or push_x >= zone_width or push_y >= zone_height:
                    # Can't push item outside zone
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

                # 2. Not blocked terrain
                if is_terrain_blocked(terrain_data, push_x, push_y):
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

                # 3. No other item at push destination
                result = await session.execute(
                    select(Entity).where(
                        Entity.zone_id == monster.current_zone_id,
                        Entity.x == push_x,
                        Entity.y == push_y,
                        Entity.entity_type == "item"
                    )
                )
                item_blocking_push = result.scalar_one_or_none()
                if item_blocking_push:
                    # Can't push into another item
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

                # Push is valid - move the item first
                item_at_target.x = push_x
                item_at_target.y = push_y

        # Update position
        monster.x = new_x
        monster.y = new_y
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


class InteractRequest(BaseModel):
    monster_id: str


class InteractResponse(BaseModel):
    message: str
    action: Optional[str] = None  # 'zone_transition', 'workshop_menu', etc.
    new_zone_id: Optional[str] = None
    new_zone_name: Optional[str] = None
    new_x: Optional[int] = None
    new_y: Optional[int] = None
    entity_type: Optional[str] = None
    entity_name: Optional[str] = None


@app.post("/api/monsters/interact", response_model=InteractResponse, tags=["Monsters"])
async def interact(request: InteractRequest, token: str):
    """Interact with an adjacent entity (signpost, workshop, dispenser, etc.)."""
    async with async_session() as session:
        player = await get_current_player(token, session)

        # Get the monster
        result = await session.execute(
            select(Monster).where(Monster.id == request.monster_id)
        )
        monster = result.scalar_one_or_none()

        if not monster:
            raise HTTPException(status_code=404, detail="Monster not found")

        # Verify ownership
        result = await session.execute(
            select(Commune).where(Commune.player_id == player.id)
        )
        commune = result.scalar_one_or_none()
        if not commune or monster.commune_id != commune.id:
            raise HTTPException(status_code=403, detail="You can only control your own monsters")

        if not monster.current_zone_id:
            raise HTTPException(status_code=400, detail="Monster is not in a zone")

        # Look for interactable entities at monster position or adjacent cells
        adjacent_positions = [
            (monster.x, monster.y),      # Same cell
            (monster.x, monster.y - 1),  # Up
            (monster.x, monster.y + 1),  # Down
            (monster.x - 1, monster.y),  # Left
            (monster.x + 1, monster.y),  # Right
        ]

        # Find entities at adjacent positions
        result = await session.execute(
            select(Entity).where(Entity.zone_id == monster.current_zone_id)
        )
        entities = result.scalars().all()

        interactable = None
        for entity in entities:
            for pos in adjacent_positions:
                if entity.x == pos[0] and entity.y == pos[1]:
                    # Found an entity at or adjacent to monster
                    if entity.entity_type in ['signpost', 'workshop', 'dispenser', 'gathering_spot']:
                        interactable = entity
                        break
            if interactable:
                break

        if not interactable:
            return InteractResponse(
                message="Nothing to interact with here",
                action=None
            )

        # Handle based on entity type
        if interactable.entity_type == 'signpost':
            # Zone transition
            metadata = interactable.entity_metadata or {}
            dest_zone_id = metadata.get('destination_zone_id')
            dest_x = metadata.get('destination_x', 5)
            dest_y = metadata.get('destination_y', 5)
            dest_zone_name = metadata.get('destination_zone_name', 'Unknown')

            if not dest_zone_id:
                return InteractResponse(
                    message="This signpost doesn't lead anywhere",
                    action=None,
                    entity_type='signpost',
                    entity_name=metadata.get('name', 'Signpost')
                )

            # Verify destination zone exists
            result = await session.execute(
                select(Zone).where(Zone.id == dest_zone_id)
            )
            dest_zone = result.scalar_one_or_none()

            if not dest_zone:
                return InteractResponse(
                    message="The destination zone no longer exists",
                    action=None,
                    entity_type='signpost'
                )

            # Perform the zone transition
            monster.current_zone_id = dest_zone_id
            monster.x = dest_x
            monster.y = dest_y
            await session.commit()

            return InteractResponse(
                message=f"Traveled to {dest_zone.name}",
                action='zone_transition',
                new_zone_id=dest_zone_id,
                new_zone_name=dest_zone.name,
                new_x=dest_x,
                new_y=dest_y,
                entity_type='signpost',
                entity_name=metadata.get('name', 'Signpost')
            )

        elif interactable.entity_type == 'workshop':
            metadata = interactable.entity_metadata or {}
            return InteractResponse(
                message=f"This is a {metadata.get('name', 'Workshop')}",
                action='workshop_menu',
                entity_type='workshop',
                entity_name=metadata.get('name', 'Workshop')
            )

        elif interactable.entity_type == 'dispenser':
            metadata = interactable.entity_metadata or {}
            return InteractResponse(
                message=f"This is a {metadata.get('name', 'Dispenser')}",
                action='dispenser_info',
                entity_type='dispenser',
                entity_name=metadata.get('name', 'Dispenser')
            )

        else:
            metadata = interactable.entity_metadata or {}
            return InteractResponse(
                message=f"Interacted with {metadata.get('name', interactable.entity_type)}",
                action=None,
                entity_type=interactable.entity_type,
                entity_name=metadata.get('name', interactable.entity_type)
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

class SetMonsterZoneRequest(BaseModel):
    monster_id: str
    zone_id: str
    x: int = 5
    y: int = 5


@app.post("/api/debug/monster/set-zone", tags=["Debug"])
async def set_monster_zone(request: SetMonsterZoneRequest):
    """Set a monster's zone and position (for testing)."""
    async with async_session() as session:
        result = await session.execute(
            select(Monster).where(Monster.id == request.monster_id)
        )
        monster = result.scalar_one_or_none()

        if not monster:
            raise HTTPException(status_code=404, detail="Monster not found")

        monster.current_zone_id = request.zone_id
        monster.x = request.x
        monster.y = request.y
        await session.commit()

        return {"message": "Monster zone updated", "monster_id": request.monster_id, "zone_id": request.zone_id, "x": request.x, "y": request.y}


class CreateItemRequest(BaseModel):
    zone_id: str
    x: int
    y: int
    name: str = "Test Item"


@app.post("/api/debug/item/create", tags=["Debug"])
async def create_item(request: CreateItemRequest):
    """Create an item in a zone (for testing)."""
    async with async_session() as session:
        item = Entity(
            zone_id=request.zone_id,
            entity_type="item",
            x=request.x,
            y=request.y,
            entity_metadata={"name": request.name}
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)

        return {"message": "Item created", "id": item.id, "x": item.x, "y": item.y, "name": request.name}


class CreateSignpostRequest(BaseModel):
    zone_id: str
    x: int
    y: int
    name: str = "Signpost"
    destination_zone_id: str
    destination_zone_name: str
    destination_x: int = 5
    destination_y: int = 5


@app.post("/api/debug/signpost/create", tags=["Debug"])
async def create_signpost(request: CreateSignpostRequest):
    """Create a signpost for zone transitions (for testing)."""
    async with async_session() as session:
        signpost = Entity(
            zone_id=request.zone_id,
            entity_type="signpost",
            x=request.x,
            y=request.y,
            entity_metadata={
                "name": request.name,
                "destination_zone_id": request.destination_zone_id,
                "destination_zone_name": request.destination_zone_name,
                "destination_x": request.destination_x,
                "destination_y": request.destination_y
            }
        )
        session.add(signpost)
        await session.commit()
        await session.refresh(signpost)

        return {
            "message": "Signpost created",
            "id": signpost.id,
            "x": signpost.x,
            "y": signpost.y,
            "name": request.name,
            "destination": request.destination_zone_name
        }


@app.get("/api/zones/{zone_id}/entities", tags=["Zones"])
async def get_zone_entities(zone_id: str):
    """Get all entities in a zone."""
    async with async_session() as session:
        result = await session.execute(
            select(Entity).where(Entity.zone_id == zone_id)
        )
        entities = result.scalars().all()

        return [
            {
                "id": e.id,
                "entity_type": e.entity_type,
                "x": e.x,
                "y": e.y,
                "metadata": e.entity_metadata
            }
            for e in entities
        ]


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


# Game time tracking
game_start_time = datetime.utcnow()


@app.get("/api/debug/time", tags=["Debug"])
async def get_game_time():
    """Get current game time information."""
    now = datetime.utcnow()
    real_elapsed = (now - game_start_time).total_seconds()
    game_elapsed = real_elapsed * GAME_TIME_MULTIPLIER

    return {
        "real_elapsed_seconds": real_elapsed,
        "game_elapsed_seconds": game_elapsed,
        "game_time_multiplier": GAME_TIME_MULTIPLIER,
        "server_time_utc": now.isoformat(),
        "game_start_utc": game_start_time.isoformat()
    }


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
