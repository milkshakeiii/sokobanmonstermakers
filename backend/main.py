"""Monster Workshop - Main FastAPI Application.

A cooperative crafting game with roguelike/ASCII aesthetic.
Server-authoritative architecture using gridtickmultiplayer patterns.
Version 0.1.1 - Added monster upkeep system.
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
from sqlalchemy import select, text, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from models.database import init_db, get_session, async_session
from models.player import Player, Session, Commune
from models.monster import Monster, MONSTER_TYPES, TRANSFERABLE_SKILLS
from models.zone import Zone, Entity, GoodType, Share


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
    transferable_skills: list[str] = []
    applied_skills: dict = {}


class DepositInfo(BaseModel):
    """Info about an item deposited into a workshop input slot."""
    workshop_id: str
    workshop_name: str
    item_name: str
    slot_x: int
    slot_y: int


class MoveResult(BaseModel):
    """Result of a monster move action, including any push/deposit effects."""
    monster: MonsterInfo
    pushed_item: Optional[str] = None  # Item name if an item was pushed
    deposit: Optional[DepositInfo] = None  # Info if item was deposited into workshop


class RecordingAction(BaseModel):
    """A single recorded action in a recording sequence."""
    action_type: str  # "move", "push", "interact", "deposit"
    direction: Optional[str] = None  # For move/push actions
    entity_id: Optional[str] = None  # Entity interacted with
    timestamp: str  # ISO timestamp


class RecordingState(BaseModel):
    """Current state of a recording in progress."""
    is_recording: bool
    started_at: Optional[str] = None
    workshop_id: Optional[str] = None  # Workshop being crafted at
    recipe_id: Optional[int] = None  # Selected recipe
    actions: list[RecordingAction] = []


class StartRecordingRequest(BaseModel):
    monster_id: str
    workshop_id: Optional[str] = None  # Optional - workshop to associate with
    recipe_id: Optional[int] = None  # Optional - recipe selected


class StopRecordingRequest(BaseModel):
    monster_id: str


class StartAutorepeatRequest(BaseModel):
    monster_id: str


class StopAutorepeatRequest(BaseModel):
    monster_id: str


class AutorepeatState(BaseModel):
    """Current state of autorepeat playback."""
    is_playing: bool
    current_action_index: int = 0
    total_actions: int = 0
    recorded_sequence: list[RecordingAction] = []


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
async def get_monster_types(token: str = None):
    """Get all available monster types with their stats and costs.

    If a token is provided, costs are adjusted based on the player's spending history.
    """
    # If token provided, get commune for cost multiplier
    commune = None
    if token:
        async with async_session() as session:
            try:
                player = await get_current_player(token, session)
                result = await session.execute(
                    select(Commune).where(Commune.player_id == player.id)
                )
                commune = result.scalar_one_or_none()
            except HTTPException:
                pass  # Invalid token, use base costs

    result = []
    for name, data in MONSTER_TYPES.items():
        base_cost = data["cost"]
        adjusted_cost = get_adjusted_cost(base_cost, commune) if commune else base_cost
        result.append(MonsterTypeInfo(
            name=name,
            cost=adjusted_cost,
            body_cap=data["body_cap"],
            mind_cap=data["mind_cap"],
            base_stats=data["base_stats"]
        ))
    return result


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

        # Return monsters with skill decay applied
        return [monster_to_info(m) for m in monsters]


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

        # Check if player has enough renown (applying cost multiplier)
        base_cost = MONSTER_TYPES[request.monster_type]["cost"]
        adjusted_cost = get_adjusted_cost(base_cost, commune)
        current_renown = int(commune.renown)

        if current_renown < adjusted_cost:
            raise HTTPException(
                status_code=400,
                detail=f"Not enough renown. Need {adjusted_cost}, have {current_renown}"
            )

        # Deduct cost and track spending
        commune.renown = str(current_renown - adjusted_cost)
        current_spent = int(commune.total_renown_spent or "0")
        commune.total_renown_spent = str(current_spent + adjusted_cost)

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
            y=monster.y,
            transferable_skills=monster.transferable_skills or [],
            applied_skills=monster.applied_skills or {}
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


async def get_entity_at_position(session, zone_id: str, x: int, y: int, entity_type: str = None) -> "Entity | None":
    """Get an entity occupying a specific position, handling multi-cell entities.

    This function checks if any entity's bounding box (x to x+width-1, y to y+height-1)
    contains the target position.

    Args:
        session: Database session
        zone_id: Zone to search in
        x, y: Target position to check
        entity_type: Optional filter for entity type (e.g., "item", "wagon")

    Returns:
        The Entity occupying that position, or None
    """
    # Build base query
    query = select(Entity).where(Entity.zone_id == zone_id)
    if entity_type:
        query = query.where(Entity.entity_type == entity_type)

    result = await session.execute(query)
    entities = result.scalars().all()

    for entity in entities:
        entity_width = entity.width or 1
        entity_height = entity.height or 1

        # Check if position is within entity bounds
        if (entity.x <= x < entity.x + entity_width and
            entity.y <= y < entity.y + entity_height):
            return entity

    return None


async def is_position_blocked_by_entity(session, zone_id: str, x: int, y: int,
                                         entity_types: list = None, exclude_entity_id: str = None) -> bool:
    """Check if a position is blocked by any entity (including multi-cell entities).

    Args:
        session: Database session
        zone_id: Zone to check in
        x, y: Target position
        entity_types: Optional list of entity types to check (default: ["item", "wagon"])
        exclude_entity_id: Optional entity ID to exclude from check (e.g., the entity being moved)

    Returns:
        True if position is blocked, False otherwise
    """
    if entity_types is None:
        entity_types = ["item", "wagon"]

    query = select(Entity).where(
        Entity.zone_id == zone_id,
        Entity.entity_type.in_(entity_types)
    )

    result = await session.execute(query)
    entities = result.scalars().all()

    for entity in entities:
        if exclude_entity_id and entity.id == exclude_entity_id:
            continue

        entity_width = entity.width or 1
        entity_height = entity.height or 1

        # Check if position is within entity bounds
        if (entity.x <= x < entity.x + entity_width and
            entity.y <= y < entity.y + entity_height):
            return True

    return False


def calculate_cost_multiplier(total_renown_spent: int) -> float:
    """Calculate cost multiplier based on total renown spent by a commune.

    Cost multiplier formula:
    - Base multiplier: 1.0
    - Every 1000 renown spent adds 0.1 to the multiplier (10% increase)
    - Example: 0 spent = 1.0x, 1000 spent = 1.1x, 5000 spent = 1.5x, 10000 spent = 2.0x
    - Cap at 3.0x (at 20000 spent)
    """
    multiplier = 1.0 + (total_renown_spent / 1000) * 0.1
    return min(3.0, multiplier)


def get_adjusted_cost(base_cost: int, commune: Commune) -> int:
    """Get adjusted cost after applying cost multiplier."""
    total_spent = int(commune.total_renown_spent or "0")
    multiplier = calculate_cost_multiplier(total_spent)
    return int(base_cost * multiplier)


def get_item_weight(entity: Entity) -> int:
    """Get the weight of an item entity.

    Weight is determined by:
    1. Explicit weight in metadata
    2. storage_volume from good type (if available)
    3. Default weight of 1

    Wagons have a base weight of 10 but can carry additional items.
    """
    metadata = entity.entity_metadata or {}

    # Check for explicit weight in metadata
    if 'weight' in metadata:
        return metadata['weight']

    # Wagons have higher base weight
    if entity.entity_type == "wagon":
        return 10

    # Default weight for items
    return 1


def get_monster_transport_capacity(monster: Monster) -> int:
    """Calculate monster's transport capacity based on STR.

    Transport capacity formula:
    - Base capacity: STR score
    - Example: Monster with STR 10 can push items up to weight 10
    - Monster with STR 18 can push items up to weight 18

    Wagons allow transporting items beyond normal capacity when hitched.
    """
    # Base capacity from STR (including age bonus already applied)
    return monster.str_ + monster.age_bonus


def can_monster_push_item(monster: Monster, entity: Entity) -> tuple[bool, str]:
    """Check if a monster can push an item based on weight.

    Args:
        monster: The monster attempting to push
        entity: The entity being pushed

    Returns:
        Tuple of (can_push, reason) where reason explains why if can't push
    """
    item_weight = get_item_weight(entity)
    capacity = get_monster_transport_capacity(monster)

    if item_weight > capacity:
        return False, f"Item weight ({item_weight}) exceeds transport capacity ({capacity})"

    return True, ""


def calculate_skill_decay(monster: Monster) -> dict:
    """Calculate decayed skill values based on time since last use.

    Skill decay formula:
    - Base decay rate: 0.001 per game day (0.1% per day)
    - WIS reduces decay: decay_reduction = (WIS - 10) * 0.1 (percentage reduction)
    - Monster with WIS 10: no reduction
    - Monster with WIS 18: 80% reduction (only 20% of normal decay)
    - Monster with WIS 8: 20% increase (120% of normal decay)
    - Skills can't decay below 0

    Game time: 1 real second = 30 game seconds
    """
    applied_skills = monster.applied_skills or {}
    skill_last_used = monster.skill_last_used or {}

    if not applied_skills:
        return {}

    decayed_skills = {}
    now = datetime.utcnow()

    # Calculate WIS-based decay modifier
    # WIS 10 = 1.0x decay, WIS 18 = 0.2x decay, WIS 8 = 1.2x decay
    wis_modifier = 1.0 - (monster.wis - 10) * 0.1
    wis_modifier = max(0.1, min(2.0, wis_modifier))  # Clamp between 0.1 and 2.0

    # Base decay rate per game day
    base_decay_per_game_day = 0.001  # 0.1% per game day

    # Game time multiplier (1 real second = 30 game seconds)
    game_time_multiplier = GAME_TIME_MULTIPLIER

    for skill_name, skill_level in applied_skills.items():
        last_used_str = skill_last_used.get(skill_name)

        if last_used_str:
            try:
                last_used = datetime.fromisoformat(last_used_str)
                real_seconds_since_use = (now - last_used).total_seconds()

                # Convert to game days
                game_seconds_since_use = real_seconds_since_use * game_time_multiplier
                game_days_since_use = game_seconds_since_use / (24 * 60 * 60)

                # Calculate decay
                decay_amount = base_decay_per_game_day * game_days_since_use * wis_modifier
                new_level = max(0, skill_level - decay_amount)
                decayed_skills[skill_name] = round(new_level, 3)
            except (ValueError, TypeError):
                # If timestamp is invalid, use current skill level
                decayed_skills[skill_name] = skill_level
        else:
            # If never used (shouldn't happen), decay from monster creation time
            real_seconds_since_creation = (now - monster.created_at).total_seconds()
            game_seconds_since_creation = real_seconds_since_creation * game_time_multiplier
            game_days_since_creation = game_seconds_since_creation / (24 * 60 * 60)

            decay_amount = base_decay_per_game_day * game_days_since_creation * wis_modifier
            new_level = max(0, skill_level - decay_amount)
            decayed_skills[skill_name] = round(new_level, 3)

    return decayed_skills


async def calculate_upkeep_due(monster: Monster, session) -> dict:
    """Calculate if upkeep is due for a monster.

    Upkeep is due every 28 game days.
    Returns dict with:
        - upkeep_due: bool - whether upkeep is due
        - upkeep_cost: int - cost in renown (based on monster type cost)
        - days_since_payment: float - game days since last upkeep
        - days_until_due: float - game days until next upkeep (negative if overdue)
    """
    now = datetime.utcnow()

    # Read last_upkeep_paid from database via raw SQL (column not in ORM model)
    result = await session.execute(
        text("SELECT last_upkeep_paid FROM monsters WHERE id = :monster_id"),
        {"monster_id": monster.id}
    )
    row = result.fetchone()
    last_paid_str = row[0] if row else None

    # Parse the timestamp or use created_at as fallback
    if last_paid_str:
        try:
            last_paid = datetime.fromisoformat(last_paid_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            last_paid = monster.created_at
    else:
        last_paid = monster.created_at

    # Calculate game days since last payment
    real_seconds = (now - last_paid).total_seconds()
    game_seconds = real_seconds * GAME_TIME_MULTIPLIER
    game_days = game_seconds / (24 * 60 * 60)

    # Upkeep is due every 28 game days
    UPKEEP_CYCLE_DAYS = 28
    days_until_due = UPKEEP_CYCLE_DAYS - game_days
    upkeep_due = game_days >= UPKEEP_CYCLE_DAYS

    # Upkeep cost is based on monster type creation cost
    # (could be a fraction of creation cost, using same for simplicity)
    monster_type_info = MONSTER_TYPES.get(monster.monster_type, {})
    upkeep_cost = monster_type_info.get("cost", 50)  # Default to 50 if unknown type

    return {
        "upkeep_due": upkeep_due,
        "upkeep_cost": upkeep_cost,
        "days_since_payment": round(game_days, 2),
        "days_until_due": round(days_until_due, 2),
        "last_upkeep_paid": last_paid.isoformat() if last_paid != monster.created_at else None
    }


async def process_monster_upkeep(monster: Monster, commune, session) -> dict:
    """Process upkeep payment for a monster if due.

    Returns dict with:
        - upkeep_collected: bool
        - amount: int
        - new_renown: int
        - error: str (if insufficient renown)
    """
    upkeep_info = await calculate_upkeep_due(monster, session)

    if not upkeep_info["upkeep_due"]:
        return {"upkeep_collected": False, "reason": "not_due"}

    upkeep_cost = upkeep_info["upkeep_cost"]
    current_renown = int(commune.renown)

    if current_renown < upkeep_cost:
        return {
            "upkeep_collected": False,
            "reason": "insufficient_renown",
            "required": upkeep_cost,
            "available": current_renown
        }

    # Deduct upkeep from commune renown
    new_renown = current_renown - upkeep_cost
    commune.renown = str(new_renown)

    # Update last upkeep paid timestamp using raw SQL (column added via migration)
    now = datetime.utcnow()
    await session.execute(
        text("UPDATE monsters SET last_upkeep_paid = :now WHERE id = :monster_id"),
        {"now": now.isoformat(), "monster_id": monster.id}
    )

    return {
        "upkeep_collected": True,
        "amount": upkeep_cost,
        "new_renown": new_renown
    }


def monster_to_info(monster: Monster, apply_skill_decay: bool = True) -> MonsterInfo:
    """Convert a Monster ORM object to a MonsterInfo Pydantic model.

    Args:
        monster: The Monster ORM object
        apply_skill_decay: If True, calculate current skill levels with decay applied

    Note: Applies age bonus (+1 at 30 days, +2 at 60 days) to all ability scores.
    """
    applied_skills = monster.applied_skills or {}

    if apply_skill_decay and applied_skills:
        applied_skills = calculate_skill_decay(monster)

    # Apply age bonus to ability scores
    age_bonus = monster.age_bonus

    return MonsterInfo(
        id=monster.id,
        name=monster.name,
        monster_type=monster.monster_type,
        str_=monster.str_ + age_bonus,
        dex=monster.dex + age_bonus,
        con=monster.con + age_bonus,
        int_=monster.int_ + age_bonus,
        wis=monster.wis + age_bonus,
        cha=monster.cha + age_bonus,
        body_fitting_used=monster.body_fitting_used,
        mind_fitting_used=monster.mind_fitting_used,
        current_zone_id=monster.current_zone_id,
        x=monster.x,
        y=monster.y,
        transferable_skills=monster.transferable_skills or [],
        applied_skills=applied_skills
    )


def is_workshop_input_slot(workshop: Entity, x: int, y: int) -> bool:
    """Check if position (x, y) is an input slot of the workshop.

    Input slots are the cells just inside the workshop walls (the first interior row/column).
    For a 4x4 workshop at (wx, wy), the input slots are at positions like (wx+1, wy+1).
    """
    if not workshop or workshop.entity_type != 'workshop':
        return False

    width = workshop.width or 4
    height = workshop.height or 4

    # Calculate relative position within workshop
    rel_x = x - workshop.x
    rel_y = y - workshop.y

    # Check if inside workshop bounds
    if rel_x < 0 or rel_y < 0 or rel_x >= width or rel_y >= height:
        return False

    # Check if on the edge (not an input slot, that's the wall)
    if rel_x == 0 or rel_x == width - 1 or rel_y == 0 or rel_y == height - 1:
        return False

    # It's in the interior - consider it an input slot
    # The spec mentions input/output/tool slots - for now, all interior cells are input slots
    return True


def is_workshop_tool_slot(workshop: Entity, x: int, y: int) -> bool:
    """Check if position (x, y) is a tool slot of the workshop.

    Tool slots are the cells on the left side of the workshop interior.
    For a 4x4 workshop at (wx, wy), the tool slots are at (wx+1, wy+1) and (wx+1, wy+2).
    """
    if not workshop or workshop.entity_type != 'workshop':
        return False

    width = workshop.width or 4
    height = workshop.height or 4

    # Calculate relative position within workshop
    rel_x = x - workshop.x
    rel_y = y - workshop.y

    # Check if inside workshop bounds
    if rel_x < 0 or rel_y < 0 or rel_x >= width or rel_y >= height:
        return False

    # Check if on the edge (not a slot, that's the wall)
    if rel_x == 0 or rel_x == width - 1 or rel_y == 0 or rel_y == height - 1:
        return False

    # Tool slots are on the left side of the interior (rel_x == 1)
    return rel_x == 1


def is_tool_item(item_metadata: dict) -> bool:
    """Check if an item is a tool based on its metadata.

    Tools have good_type containing 'tool' or have is_tool flag.
    """
    if not item_metadata:
        return False

    good_type = item_metadata.get('good_type', '').lower()
    if 'tool' in good_type or 'hammer' in good_type or 'tongs' in good_type or 'anvil' in good_type or 'loom' in good_type:
        return True

    # Also check for explicit is_tool flag
    return item_metadata.get('is_tool', False)


def get_tool_tags(item_metadata: dict) -> list:
    """Get the tool tags for an item.

    Tool tags are used to match against recipe tool requirements.
    """
    if not item_metadata:
        return []

    tags = item_metadata.get('tool_tags', [])

    # Also derive tags from good_type
    good_type = item_metadata.get('good_type', '').lower()
    if 'hammer' in good_type:
        tags = tags + ['hammer'] if 'hammer' not in tags else tags
    if 'tongs' in good_type:
        tags = tags + ['tongs'] if 'tongs' not in tags else tags
    if 'anvil' in good_type:
        tags = tags + ['anvil'] if 'anvil' not in tags else tags
    if 'loom' in good_type:
        tags = tags + ['loom'] if 'loom' not in tags else tags

    return tags


@app.post("/api/monsters/move", response_model=MoveResult, tags=["Monsters"])
async def move_monster(request: MoveMonsterRequest, token: str):
    """Move a monster one cell in the specified direction. Can push items into workshop input slots."""
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
            return MoveResult(monster=monster_to_info(monster))

        # Check terrain collision
        terrain_data = zone.terrain_data if zone else None
        if is_terrain_blocked(terrain_data, new_x, new_y):
            # Can't move into blocked terrain - return current position
            return MoveResult(monster=monster_to_info(monster))

        # Initialize push result variables
        pushed_item_name = None
        deposit_info = None

        # Check for item at target position (for pushing)
        # Use multi-cell aware function to detect items including wagons
        item_at_target = None
        if monster.current_zone_id:
            item_at_target = await get_entity_at_position(
                session, monster.current_zone_id, new_x, new_y, entity_type="item"
            )
            # Also check for wagons which are multi-cell entities
            if not item_at_target:
                item_at_target = await get_entity_at_position(
                    session, monster.current_zone_id, new_x, new_y, entity_type="wagon"
                )

            if item_at_target:
                # Check if item is being actively pushed by another player
                item_metadata = item_at_target.entity_metadata or {}
                being_pushed_by = item_metadata.get('being_pushed_by')
                if being_pushed_by and being_pushed_by != str(monster.id):
                    # Item is being pushed by another player - reject this push
                    return MoveResult(monster=monster_to_info(monster))

                # Check if monster can push this item based on weight
                can_push, push_reason = can_monster_push_item(monster, item_at_target)
                if not can_push:
                    # Item is too heavy for this monster
                    return MoveResult(monster=monster_to_info(monster))

                # Mark item as being pushed by this monster (active-push protection)
                item_push_metadata = item_at_target.entity_metadata or {}
                item_push_metadata['being_pushed_by'] = str(monster.id)
                item_at_target.entity_metadata = item_push_metadata
                flag_modified(item_at_target, 'entity_metadata')

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
                    # Can't push item outside zone - clear push protection
                    item_push_metadata.pop('being_pushed_by', None)
                    item_at_target.entity_metadata = item_push_metadata
                    flag_modified(item_at_target, 'entity_metadata')
                    return MoveResult(monster=monster_to_info(monster))

                # 2. Not blocked terrain
                if is_terrain_blocked(terrain_data, push_x, push_y):
                    # Can't push into blocked terrain - clear push protection
                    item_push_metadata.pop('being_pushed_by', None)
                    item_at_target.entity_metadata = item_push_metadata
                    flag_modified(item_at_target, 'entity_metadata')
                    return MoveResult(monster=monster_to_info(monster))

                # 3. Check if push destination is a workshop input slot
                result = await session.execute(
                    select(Entity).where(
                        Entity.zone_id == monster.current_zone_id,
                        Entity.entity_type == "workshop"
                    )
                )
                workshops = result.scalars().all()

                # Find if push destination is inside any workshop
                target_workshop = None
                for ws in workshops:
                    if is_workshop_input_slot(ws, push_x, push_y):
                        target_workshop = ws
                        break

                if target_workshop:
                    # Deposit the item into the workshop
                    item_metadata = item_at_target.entity_metadata or {}
                    item_name = item_metadata.get('name', 'Unknown Item')
                    pushed_item_name = item_name

                    # Update workshop metadata to include the deposited item
                    workshop_metadata = target_workshop.entity_metadata or {}

                    # Check if this is a tool being deposited into a tool slot
                    is_tool = is_tool_item(item_metadata)
                    is_tool_slot = is_workshop_tool_slot(target_workshop, push_x, push_y)

                    if is_tool and is_tool_slot:
                        # Deposit as a tool
                        if 'tool_items' not in workshop_metadata:
                            workshop_metadata['tool_items'] = []

                        # Get or initialize durability
                        durability = item_metadata.get('durability', 10)  # Default 10 uses

                        workshop_metadata['tool_items'].append({
                            'name': item_name,
                            'good_type': item_metadata.get('good_type', 'unknown'),
                            'tool_tags': get_tool_tags(item_metadata),
                            'durability': durability,
                            'max_durability': item_metadata.get('max_durability', durability),
                            'deposited_at': datetime.utcnow().isoformat(),
                            'slot_x': push_x,
                            'slot_y': push_y,
                            'creator_commune_id': item_metadata.get('producer_commune_id')  # Track tool creator for shares
                        })
                    else:
                        # Deposit as an input ingredient
                        if 'input_items' not in workshop_metadata:
                            workshop_metadata['input_items'] = []

                        workshop_metadata['input_items'].append({
                            'name': item_name,
                            'good_type': item_metadata.get('good_type', 'unknown'),
                            'quality': item_metadata.get('quality', 1),
                            'deposited_at': datetime.utcnow().isoformat(),
                            'slot_x': push_x,
                            'slot_y': push_y
                        })

                    target_workshop.entity_metadata = workshop_metadata
                    # Mark JSON field as modified for SQLAlchemy to detect the change
                    flag_modified(target_workshop, 'entity_metadata')

                    # Get workshop name
                    workshop_name = workshop_metadata.get('name', 'Workshop')

                    # Delete the item entity (it's now in the workshop)
                    await session.delete(item_at_target)

                    deposit_info = DepositInfo(
                        workshop_id=target_workshop.id,
                        workshop_name=workshop_name,
                        item_name=item_name,
                        slot_x=push_x,
                        slot_y=push_y
                    )
                else:
                    # 4. Check if pushing into a dispenser
                    dispenser_result = await session.execute(
                        select(Entity).where(
                            Entity.zone_id == monster.current_zone_id,
                            Entity.x == push_x,
                            Entity.y == push_y,
                            Entity.entity_type == "dispenser"
                        )
                    )
                    target_dispenser = dispenser_result.scalar_one_or_none()

                    if target_dispenser:
                        # Depositing item into dispenser
                        item_metadata = item_at_target.entity_metadata or {}
                        item_name = item_metadata.get('name', 'Unknown Item')
                        item_good_type = item_metadata.get('good_type', 'unknown')
                        pushed_item_name = item_name

                        dispenser_metadata = target_dispenser.entity_metadata or {}
                        dispenser_good_type = dispenser_metadata.get('good_type', '')

                        # Check if item matches dispenser type (optional - can accept any)
                        if 'stored_count' not in dispenser_metadata:
                            dispenser_metadata['stored_count'] = 0

                        # Deposit the item
                        dispenser_metadata['stored_count'] = dispenser_metadata.get('stored_count', 0) + 1
                        target_dispenser.entity_metadata = dispenser_metadata
                        flag_modified(target_dispenser, 'entity_metadata')

                        # Delete the item (it's now in the dispenser)
                        await session.delete(item_at_target)

                        # Spawn a new item on top of dispenser if there are stored items
                        if dispenser_metadata.get('stored_count', 0) > 0:
                            spawn_good_type = dispenser_metadata.get('good_type', 'item')
                            spawned_item = Entity(
                                zone_id=monster.current_zone_id,
                                entity_type="item",
                                x=push_x,
                                y=push_y,
                                entity_metadata={
                                    'name': spawn_good_type.replace('_', ' ').title(),
                                    'good_type': spawn_good_type,
                                    'quality': 5,
                                    'from_dispenser': True
                                }
                            )
                            session.add(spawned_item)

                        dispenser_name = dispenser_metadata.get('name', 'Dispenser')
                        deposit_info = DepositInfo(
                            workshop_id=target_dispenser.id,
                            workshop_name=dispenser_name,
                            item_name=item_name,
                            slot_x=push_x,
                            slot_y=push_y
                        )
                    else:
                        # 5. Check if pushing into a delivery location
                        delivery_result = await session.execute(
                            select(Entity).where(
                                Entity.zone_id == monster.current_zone_id,
                                Entity.x == push_x,
                                Entity.y == push_y,
                                Entity.entity_type == "delivery"
                            )
                        )
                        target_delivery = delivery_result.scalar_one_or_none()

                        if target_delivery:
                            # Score the item at delivery location
                            item_metadata = item_at_target.entity_metadata or {}
                            item_name = item_metadata.get('name', 'Unknown Item')
                            item_quality = item_metadata.get('quality', 1)
                            pushed_item_name = item_name

                            delivery_metadata = target_delivery.entity_metadata or {}
                            delivery_name = delivery_metadata.get('name', 'Delivery')

                            # Calculate renown based on item quality and transporter's CHA
                            base_renown = item_quality * 10  # 10 renown per quality point
                            # CHA bonus: +5% per point above 10
                            cha_bonus_percent = max(0, monster.cha - 10) * 0.05
                            base_renown = int(base_renown * (1 + cha_bonus_percent))

                            # Distribute shares to all contributors
                            contributors = {}  # commune_id -> {types: [], shares: 0}

                            # Producer gets shares
                            producer_commune_id = item_metadata.get('producer_commune_id')
                            if producer_commune_id:
                                if producer_commune_id not in contributors:
                                    contributors[producer_commune_id] = {'types': [], 'shares': 0}
                                contributors[producer_commune_id]['types'].append('producer')
                                contributors[producer_commune_id]['shares'] += 1

                            # Tool creators get shares
                            tool_creator_communes = item_metadata.get('tool_creator_commune_ids', [])
                            for tool_commune_id in tool_creator_communes:
                                if tool_commune_id:
                                    if tool_commune_id not in contributors:
                                        contributors[tool_commune_id] = {'types': [], 'shares': 0}
                                    if 'tool_creator' not in contributors[tool_commune_id]['types']:
                                        contributors[tool_commune_id]['types'].append('tool_creator')
                                    contributors[tool_commune_id]['shares'] += 1

                            # Transporter gets shares (the one who pushed to delivery)
                            transporter_commune_id = monster.commune_id
                            if transporter_commune_id:
                                if transporter_commune_id not in contributors:
                                    contributors[transporter_commune_id] = {'types': [], 'shares': 0}
                                contributors[transporter_commune_id]['types'].append('transporter')
                                contributors[transporter_commune_id]['shares'] += 1

                            # Calculate total shares and distribute renown
                            total_shares = sum(c['shares'] for c in contributors.values())
                            total_shares = max(1, total_shares)  # Avoid division by zero
                            renown_per_share = base_renown / total_shares

                            share_distribution = []
                            for commune_id, contrib_info in contributors.items():
                                commune_renown = int(renown_per_share * contrib_info['shares'])
                                if commune_renown > 0:
                                    commune_result = await session.execute(
                                        select(Commune).where(Commune.id == commune_id)
                                    )
                                    commune = commune_result.scalar_one_or_none()
                                    if commune:
                                        current_renown = int(commune.renown or "0")
                                        commune.renown = str(current_renown + commune_renown)
                                        share_distribution.append({
                                            'commune_id': commune_id,
                                            'commune_name': commune.name,
                                            'contribution_types': contrib_info['types'],
                                            'shares': contrib_info['shares'],
                                            'renown': commune_renown
                                        })

                                        # Create Share records for tracking
                                        for contrib_type in contrib_info['types']:
                                            share_record = Share(
                                                entity_id=item_at_target.id,
                                                commune_id=commune_id,
                                                share_count=contrib_info['shares'],
                                                contribution_type=contrib_type
                                            )
                                            session.add(share_record)

                            renown_gained = base_renown

                            # Delete the item (it's been delivered/scored)
                            await session.delete(item_at_target)

                            deposit_info = DepositInfo(
                                workshop_id=target_delivery.id,
                                workshop_name=delivery_name,
                                item_name=f"{item_name} (Scored! +{renown_gained} renown, {len(contributors)} contributors)",
                                slot_x=push_x,
                                slot_y=push_y
                            )
                        else:
                            # 6. No other item at push destination (handles multi-cell entities)
                            is_blocked = await is_position_blocked_by_entity(
                                session, monster.current_zone_id, push_x, push_y,
                                entity_types=["item", "wagon"],
                                exclude_entity_id=item_at_target.id  # Don't count the item being pushed
                            )
                            if is_blocked:
                                # Can't push into another item or wagon - clear push protection
                                item_push_metadata.pop('being_pushed_by', None)
                                item_at_target.entity_metadata = item_push_metadata
                                flag_modified(item_at_target, 'entity_metadata')
                                return MoveResult(monster=monster_to_info(monster))

                            # Check if item was ON a dispenser (pushing FROM dispenser)
                            # new_x, new_y is where the item currently is (source position)
                            dispenser_at_source = await session.execute(
                                select(Entity).where(
                                    Entity.zone_id == monster.current_zone_id,
                                    Entity.x == new_x,
                                    Entity.y == new_y,
                                    Entity.entity_type == "dispenser"
                                )
                            )
                            source_dispenser = dispenser_at_source.scalar_one_or_none()

                            # Push is valid - move the item
                            item_metadata = item_at_target.entity_metadata or {}
                            pushed_item_name = item_metadata.get('name', 'Unknown Item')
                            item_at_target.x = push_x
                            item_at_target.y = push_y

                            # Update transporter for share tracking and clear push protection
                            item_metadata['last_transporter_commune_id'] = monster.commune_id
                            item_metadata.pop('being_pushed_by', None)  # Clear active-push protection
                            item_at_target.entity_metadata = item_metadata
                            flag_modified(item_at_target, 'entity_metadata')

                            # If pushing from a dispenser, spawn a new item if it has more
                            if source_dispenser:
                                dispenser_metadata = source_dispenser.entity_metadata or {}
                                stored_count = dispenser_metadata.get('stored_count', 0)

                                if stored_count > 0:
                                    # Decrement count and spawn new item
                                    dispenser_metadata['stored_count'] = stored_count - 1
                                    source_dispenser.entity_metadata = dispenser_metadata
                                    flag_modified(source_dispenser, 'entity_metadata')

                                    # Create new item at dispenser location
                                    new_item = Entity(
                                        zone_id=monster.current_zone_id,
                                        entity_type="item",
                                        x=new_x,
                                        y=new_y,
                                        entity_metadata={
                                            'name': dispenser_metadata.get('good_type', 'Item').replace('_', ' ').title(),
                                            'good_type': dispenser_metadata.get('good_type', 'unknown'),
                                            'quality': 5,
                                            'from_dispenser': True
                                        }
                                    )
                                    session.add(new_item)

        # Update position
        old_x, old_y = monster.x, monster.y
        monster.x = new_x
        monster.y = new_y

        # Move hitched wagon if any (wagon follows the monster)
        current_task = monster.current_task or {}
        hitched_wagon_id = current_task.get('hitched_wagon_id')
        if hitched_wagon_id:
            result = await session.execute(
                select(Entity).where(Entity.id == hitched_wagon_id)
            )
            wagon = result.scalar_one_or_none()
            if wagon:
                # Wagon moves to where the monster was (follows behind)
                wagon.x = old_x
                wagon.y = old_y

        # Record the action if recording is active
        if current_task.get('is_recording'):
            action_type = "push" if pushed_item_name else "move"
            if deposit_info:
                action_type = "deposit"

            new_action = {
                'action_type': action_type,
                'direction': request.direction,
                'entity_id': deposit_info.workshop_id if deposit_info else None,
                'timestamp': datetime.utcnow().isoformat()
            }
            current_task['actions'].append(new_action)
            monster.current_task = current_task
            flag_modified(monster, 'current_task')

        await session.commit()
        await session.refresh(monster)

        return MoveResult(
            monster=monster_to_info(monster),
            pushed_item=pushed_item_name,
            deposit=deposit_info
        )


class InteractRequest(BaseModel):
    monster_id: str


class RecipeInfo(BaseModel):
    id: int
    name: str
    production_time: int
    difficulty_rating: int


class InteractResponse(BaseModel):
    message: str
    action: Optional[str] = None  # 'zone_transition', 'workshop_menu', etc.
    new_zone_id: Optional[str] = None
    new_zone_name: Optional[str] = None
    new_x: Optional[int] = None
    new_y: Optional[int] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None  # Entity ID (e.g., workshop_id for crafting)
    entity_name: Optional[str] = None
    workshop_type: Optional[str] = None
    recipes: Optional[list[RecipeInfo]] = None


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
            # Get entity dimensions (default to 1x1)
            entity_width = entity.width or 1
            entity_height = entity.height or 1

            for pos in adjacent_positions:
                # Check if position is within entity bounds (for multi-cell entities)
                if (entity.x <= pos[0] < entity.x + entity_width and
                    entity.y <= pos[1] < entity.y + entity_height):
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
            workshop_type = metadata.get('workshop_type', 'general')
            workshop_name = metadata.get('name', 'Workshop')

            # Fetch recipes for this workshop type
            result = await session.execute(
                select(GoodType).where(GoodType.requires_workshop == workshop_type)
            )
            recipes = result.scalars().all()

            recipe_list = [
                RecipeInfo(
                    id=r.id,
                    name=r.name,
                    production_time=r.production_time,
                    difficulty_rating=r.difficulty_rating
                )
                for r in recipes
            ]

            return InteractResponse(
                message=f"Select a recipe at {workshop_name}" if recipe_list else f"No recipes available at {workshop_name}",
                action='workshop_menu',
                entity_type='workshop',
                entity_id=interactable.id,  # Workshop ID for crafting API calls
                entity_name=workshop_name,
                workshop_type=workshop_type,
                recipes=recipe_list
            )

        elif interactable.entity_type == 'dispenser':
            metadata = interactable.entity_metadata or {}
            return InteractResponse(
                message=f"This is a {metadata.get('name', 'Dispenser')}",
                action='dispenser_info',
                entity_type='dispenser',
                entity_name=metadata.get('name', 'Dispenser')
            )

        elif interactable.entity_type == 'gathering_spot':
            metadata = interactable.entity_metadata or {}
            spot_name = metadata.get('name', 'Gathering Spot')
            good_type_name = metadata.get('produces', 'resource')
            cooldown_seconds = metadata.get('cooldown', 60)  # Default 60 second cooldown
            last_gathered = metadata.get('last_gathered_at')

            # Check cooldown
            import time
            current_time = time.time()
            if last_gathered and (current_time - last_gathered) < cooldown_seconds:
                remaining = int(cooldown_seconds - (current_time - last_gathered))
                return InteractResponse(
                    message=f"{spot_name} needs {remaining}s to regenerate",
                    action=None,
                    entity_type='gathering_spot',
                    entity_name=spot_name
                )

            # Look up the good type to produce
            result = await session.execute(
                select(GoodType).where(GoodType.name == good_type_name)
            )
            good_type = result.scalar_one_or_none()

            if not good_type:
                return InteractResponse(
                    message=f"{spot_name} has nothing to gather",
                    action=None,
                    entity_type='gathering_spot',
                    entity_name=spot_name
                )

            # Find an empty adjacent position to place the item
            adjacent_positions = [
                (monster.x - 1, monster.y),
                (monster.x + 1, monster.y),
                (monster.x, monster.y - 1),
                (monster.x, monster.y + 1),
            ]

            # Get all entities to check for blocking
            entities_result = await session.execute(
                select(Entity).where(Entity.zone_id == monster.current_zone_id)
            )
            zone_entities = entities_result.scalars().all()

            # Get all monsters in zone
            monsters_result = await session.execute(
                select(Monster).where(Monster.current_zone_id == monster.current_zone_id)
            )
            zone_monsters = monsters_result.scalars().all()

            # Find first empty adjacent position (not blocked by entity or monster)
            spawn_pos = None
            for pos in adjacent_positions:
                blocked = False
                # Check if position is blocked by any entity
                for e in zone_entities:
                    e_width = e.width or 1
                    e_height = e.height or 1
                    if (e.x <= pos[0] < e.x + e_width and
                        e.y <= pos[1] < e.y + e_height):
                        blocked = True
                        break
                # Check if position is blocked by monster
                if not blocked:
                    for m in zone_monsters:
                        if m.x == pos[0] and m.y == pos[1]:
                            blocked = True
                            break
                if not blocked:
                    spawn_pos = pos
                    break

            if not spawn_pos:
                return InteractResponse(
                    message="No space to place gathered item",
                    action=None,
                    entity_type='gathering_spot',
                    entity_name=spot_name
                )

            # Create the gathered item
            import uuid
            new_item = Entity(
                id=str(uuid.uuid4()),
                zone_id=monster.current_zone_id,
                entity_type='item',
                x=spawn_pos[0],
                y=spawn_pos[1],
                width=1,
                height=1,
                entity_metadata={
                    'name': good_type_name,
                    'good_type': good_type_name,
                    'quality': 50,  # Base quality, could be modified by skills
                    'type_tags': good_type.type_tags or []
                }
            )
            session.add(new_item)

            # Update gathering spot cooldown
            metadata['last_gathered_at'] = current_time
            interactable.entity_metadata = metadata
            flag_modified(interactable, 'entity_metadata')

            await session.commit()

            return InteractResponse(
                message=f"Gathered {good_type_name} from {spot_name}",
                action='gathered',
                entity_type='gathering_spot',
                entity_name=spot_name
            )

        else:
            metadata = interactable.entity_metadata or {}
            return InteractResponse(
                message=f"Interacted with {metadata.get('name', interactable.entity_type)}",
                action=None,
                entity_type=interactable.entity_type,
                entity_name=metadata.get('name', interactable.entity_type)
            )


# =============================================================================
# Workshop Crafting Endpoints
# =============================================================================

class SelectRecipeRequest(BaseModel):
    workshop_id: str
    recipe_id: int
    monster_id: str  # Monster doing the crafting (for skill learning)


class SkillGainInfo(BaseModel):
    """Info about skill gained during crafting."""
    skill: str
    gain: float
    new_level: float


class CraftingStatus(BaseModel):
    """Current crafting status of a workshop."""
    is_crafting: bool
    recipe_id: Optional[int] = None
    recipe_name: Optional[str] = None
    workshop_type: Optional[str] = None  # Workshop type for particle effects
    progress: float = 0.0  # 0.0 to 1.0
    time_remaining: Optional[int] = None  # In game seconds
    input_items: list = []
    tool_items: list = []  # Tools with durability info
    missing_inputs: list = []
    missing_tools: list = []
    depleted_tools: list = []  # Tools that ran out of durability
    skill_gained: Optional[SkillGainInfo] = None  # Skill learned on completion


class SelectRecipeResponse(BaseModel):
    message: str
    crafting_status: CraftingStatus


@app.post("/api/workshops/{workshop_id}/select-recipe", response_model=SelectRecipeResponse, tags=["Crafting"])
async def select_recipe(workshop_id: str, request: SelectRecipeRequest, token: str):
    """Select a recipe at a workshop and start crafting if ingredients are available."""
    async with async_session() as session:
        player = await get_current_player(token, session)

        # Get the workshop
        result = await session.execute(
            select(Entity).where(Entity.id == workshop_id, Entity.entity_type == "workshop")
        )
        workshop = result.scalar_one_or_none()

        if not workshop:
            raise HTTPException(status_code=404, detail="Workshop not found")

        # Get the recipe
        result = await session.execute(
            select(GoodType).where(GoodType.id == request.recipe_id)
        )
        recipe = result.scalar_one_or_none()

        if not recipe:
            raise HTTPException(status_code=404, detail="Recipe not found")

        # Verify recipe is for this workshop type
        workshop_metadata = workshop.entity_metadata or {}
        workshop_type = workshop_metadata.get('workshop_type', 'general')
        if recipe.requires_workshop != workshop_type:
            raise HTTPException(
                status_code=400,
                detail=f"Recipe '{recipe.name}' requires a {recipe.requires_workshop} workshop, not {workshop_type}"
            )

        # Check what ingredients are in the workshop
        input_items = workshop_metadata.get('input_items', [])

        # Check required inputs (simplified - just check tags exist in any input)
        required_tags = recipe.input_goods_tags_required or []
        missing_inputs = []

        for tag_group in required_tags:
            # tag_group is a list like ["ore", "iron"] - input needs ALL these tags
            found = False
            for item in input_items:
                item_good_type = item.get('good_type', '')
                # Simplified matching - for now just check if good_type contains any tag
                if any(tag.lower() in item_good_type.lower() for tag in tag_group):
                    found = True
                    break
            if not found:
                missing_inputs.append(tag_group)

        # Check required tools
        required_tools = recipe.tools_required_tags or []
        tool_items = workshop_metadata.get('tool_items', [])
        missing_tools = []
        for required_tag in required_tools:
            # Check if any tool in workshop has this tag
            found = False
            for tool in tool_items:
                tool_tags = tool.get('tool_tags', [])
                if required_tag in tool_tags:
                    found = True
                    break
            if not found:
                missing_tools.append(required_tag)

        # Update workshop metadata with selected recipe
        workshop_metadata['selected_recipe_id'] = recipe.id
        workshop_metadata['selected_recipe_name'] = recipe.name

        # If we have all inputs (and no tools required or tools present), start crafting
        can_craft = len(missing_inputs) == 0 and len(missing_tools) == 0

        if can_craft:
            # Get monster's stats for crafting speed bonus
            result = await session.execute(
                select(Monster).where(Monster.id == request.monster_id)
            )
            crafter = result.scalar_one_or_none()

            # Calculate crafting duration with DEX/INT bonuses
            base_duration = recipe.production_time
            if crafter:
                # DEX bonus: Each point above 10 reduces time by 2%
                dex_bonus = max(0, crafter.dex - 10) * 0.02
                # INT bonus: Each point above 10 reduces time by 1%
                int_bonus = max(0, crafter.int_ - 10) * 0.01
                # Total reduction (capped at 50%)
                total_reduction = min(0.5, dex_bonus + int_bonus)
                crafting_duration = int(base_duration * (1 - total_reduction))
            else:
                crafting_duration = base_duration

            workshop_metadata['is_crafting'] = True
            workshop_metadata['crafting_started_at'] = datetime.utcnow().isoformat()
            workshop_metadata['crafting_duration'] = crafting_duration
            workshop_metadata['base_duration'] = base_duration  # Store original for comparison
            workshop_metadata['crafter_monster_id'] = request.monster_id  # Track who's crafting
            workshop_metadata['primary_applied_skill'] = recipe.primary_applied_skill  # Skill to learn
            message = f"Started crafting {recipe.name}! (Duration: {crafting_duration}s)"
        else:
            workshop_metadata['is_crafting'] = False
            workshop_metadata.pop('crafting_started_at', None)
            if missing_inputs:
                message = f"Selected {recipe.name}. Missing ingredients: {missing_inputs}"
            else:
                message = f"Selected {recipe.name}. Missing tools: {missing_tools}"

        workshop.entity_metadata = workshop_metadata
        flag_modified(workshop, 'entity_metadata')
        await session.commit()

        # Calculate progress if crafting
        progress = 0.0
        time_remaining = None
        if workshop_metadata.get('is_crafting'):
            started_at = datetime.fromisoformat(workshop_metadata['crafting_started_at'])
            elapsed = (datetime.utcnow() - started_at).total_seconds()
            duration = workshop_metadata.get('crafting_duration', 60)
            progress = min(1.0, elapsed / duration)
            time_remaining = max(0, int(duration - elapsed))

        return SelectRecipeResponse(
            message=message,
            crafting_status=CraftingStatus(
                is_crafting=workshop_metadata.get('is_crafting', False),
                recipe_id=recipe.id,
                recipe_name=recipe.name,
                workshop_type=workshop_metadata.get('workshop_type', 'general'),
                progress=progress,
                time_remaining=time_remaining,
                input_items=input_items,
                missing_inputs=missing_inputs,
                missing_tools=missing_tools
            )
        )


@app.get("/api/workshops/{workshop_id}/status", response_model=CraftingStatus, tags=["Crafting"])
async def get_workshop_status(workshop_id: str, token: str):
    """Get the current crafting status of a workshop."""
    async with async_session() as session:
        await get_current_player(token, session)

        # Get the workshop
        result = await session.execute(
            select(Entity).where(Entity.id == workshop_id, Entity.entity_type == "workshop")
        )
        workshop = result.scalar_one_or_none()

        if not workshop:
            raise HTTPException(status_code=404, detail="Workshop not found")

        workshop_metadata = workshop.entity_metadata or {}

        # Calculate progress if crafting
        progress = 0.0
        time_remaining = None
        recipe_id = workshop_metadata.get('selected_recipe_id')
        recipe_name = workshop_metadata.get('selected_recipe_name')

        if workshop_metadata.get('is_crafting'):
            started_at = datetime.fromisoformat(workshop_metadata['crafting_started_at'])
            elapsed = (datetime.utcnow() - started_at).total_seconds()
            duration = workshop_metadata.get('crafting_duration', 60)
            progress = min(1.0, elapsed / duration)
            time_remaining = max(0, int(duration - elapsed))

            # Check if crafting is complete
            if progress >= 1.0:
                # Crafting complete! Create output item
                result = await session.execute(
                    select(GoodType).where(GoodType.id == recipe_id)
                )
                recipe = result.scalar_one_or_none()

                if recipe:
                    # Create output item at workshop output position
                    output_x = workshop.x + (workshop.width or 4) - 2
                    output_y = workshop.y + (workshop.height or 4) - 2

                    # Get crafter info for share tracking and quality calculation
                    crafter_id = workshop_metadata.get('crafter_monster_id')
                    producer_commune_id = None
                    crafter_monster = None
                    if crafter_id:
                        crafter_result = await session.execute(
                            select(Monster).where(Monster.id == crafter_id)
                        )
                        crafter_monster = crafter_result.scalar_one_or_none()
                        if crafter_monster:
                            producer_commune_id = crafter_monster.commune_id

                    # Calculate quality based on WIS stat
                    # Base quality: 50, WIS bonus: +2 per point above 10, cap at 100
                    base_quality = 50
                    if crafter_monster:
                        wis_bonus = max(0, crafter_monster.wis - 10) * 2
                        calculated_quality = min(100, base_quality + wis_bonus)
                    else:
                        calculated_quality = base_quality

                    # Collect tool creator info for share tracking
                    tool_items = workshop_metadata.get('tool_items', [])
                    tool_creators = []
                    for tool in tool_items:
                        tool_creator_commune = tool.get('creator_commune_id')
                        if tool_creator_commune and tool_creator_commune not in tool_creators:
                            tool_creators.append(tool_creator_commune)

                    output_item = Entity(
                        zone_id=workshop.zone_id,
                        entity_type="item",
                        x=output_x,
                        y=output_y,
                        entity_metadata={
                            'name': recipe.name,
                            'good_type': recipe.name.lower().replace(' ', '_'),
                            'quality': calculated_quality,
                            'crafted_at': datetime.utcnow().isoformat(),
                            'producer_commune_id': producer_commune_id,  # Who crafted it
                            'tool_creator_commune_ids': tool_creators,  # Who made the tools
                            'last_transporter_commune_id': producer_commune_id  # Initially same as producer
                        }
                    )
                    session.add(output_item)

                    # Skill learning: improve monster's applied skill
                    primary_skill = workshop_metadata.get('primary_applied_skill')
                    if crafter_id and primary_skill:
                        crafter_result = await session.execute(
                            select(Monster).where(Monster.id == crafter_id)
                        )
                        crafter = crafter_result.scalar_one_or_none()
                        if crafter:
                            applied_skills = crafter.applied_skills or {}
                            current_skill_level = applied_skills.get(primary_skill, 0.0)

                            # Calculate skill gain: base 0.01, modified by INT
                            # INT bonus: (INT - 10) / 100 (so INT 18 = +0.08 bonus)
                            int_bonus = (crafter.int_ - 10) / 100
                            skill_gain = 0.01 + max(0, int_bonus)  # Min 0.01, bonus from INT

                            # Apply skill gain (cap at 1.0)
                            new_skill_level = min(1.0, current_skill_level + skill_gain)
                            applied_skills[primary_skill] = round(new_skill_level, 3)

                            crafter.applied_skills = applied_skills
                            flag_modified(crafter, 'applied_skills')

                            # Track when this skill was last used (for decay calculation)
                            skill_last_used = crafter.skill_last_used or {}
                            skill_last_used[primary_skill] = datetime.utcnow().isoformat()
                            crafter.skill_last_used = skill_last_used
                            flag_modified(crafter, 'skill_last_used')

                            # Store skill gain info for feedback
                            workshop_metadata['last_skill_gained'] = {
                                'skill': primary_skill,
                                'gain': round(skill_gain, 3),
                                'new_level': round(new_skill_level, 3)
                            }

                    # Consume tool durability
                    tool_items = workshop_metadata.get('tool_items', [])
                    depleted_tools = []
                    for tool in tool_items:
                        if tool.get('durability', 0) > 0:
                            tool['durability'] -= 1
                            if tool['durability'] <= 0:
                                depleted_tools.append(tool['name'])

                    # Remove depleted tools
                    workshop_metadata['tool_items'] = [
                        t for t in tool_items if t.get('durability', 0) > 0
                    ]

                    # Clear crafting state and consumed inputs
                    workshop_metadata['is_crafting'] = False
                    workshop_metadata['crafting_completed_at'] = datetime.utcnow().isoformat()
                    workshop_metadata['input_items'] = []  # Clear consumed ingredients
                    workshop_metadata.pop('crafting_started_at', None)

                    # Track depleted tools for feedback
                    if depleted_tools:
                        workshop_metadata['last_depleted_tools'] = depleted_tools

                    workshop.entity_metadata = workshop_metadata
                    flag_modified(workshop, 'entity_metadata')

                    await session.commit()

                    progress = 1.0
                    time_remaining = 0

        # Get depleted tools and skill gain from last crafting and clear
        depleted_tools = workshop_metadata.get('last_depleted_tools', [])
        skill_gained_data = workshop_metadata.get('last_skill_gained')
        skill_gained = None
        if skill_gained_data:
            skill_gained = SkillGainInfo(
                skill=skill_gained_data['skill'],
                gain=skill_gained_data['gain'],
                new_level=skill_gained_data['new_level']
            )

        # Clear one-time feedback after returning
        if (depleted_tools or skill_gained_data) and not workshop_metadata.get('is_crafting'):
            workshop_metadata.pop('last_depleted_tools', None)
            workshop_metadata.pop('last_skill_gained', None)
            workshop.entity_metadata = workshop_metadata
            flag_modified(workshop, 'entity_metadata')
            await session.commit()

        return CraftingStatus(
            is_crafting=workshop_metadata.get('is_crafting', False),
            recipe_id=recipe_id,
            recipe_name=recipe_name,
            workshop_type=workshop_metadata.get('workshop_type', 'general'),
            progress=progress,
            time_remaining=time_remaining,
            input_items=workshop_metadata.get('input_items', []),
            tool_items=workshop_metadata.get('tool_items', []),
            missing_inputs=[],
            missing_tools=[],
            depleted_tools=depleted_tools,
            skill_gained=skill_gained
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

        return monster_to_info(monster)


# =============================================================================
# Wagon Hitching Endpoints
# =============================================================================


class HitchWagonRequest(BaseModel):
    monster_id: str


class HitchWagonResponse(BaseModel):
    message: str
    hitched: bool
    wagon_id: Optional[str] = None
    wagon_position: Optional[dict] = None


@app.post("/api/monsters/hitch-wagon", response_model=HitchWagonResponse, tags=["Wagons"])
async def hitch_wagon(request: HitchWagonRequest, token: str):
    """Hitch a monster to an adjacent wagon for pulling."""
    async with async_session() as session:
        player = await get_current_player(token, session)

        # Get the monster
        result = await session.execute(
            select(Monster).where(Monster.id == request.monster_id)
        )
        monster = result.scalar_one_or_none()

        if not monster:
            raise HTTPException(status_code=404, detail="Monster not found")

        # Get player's commune for ownership check
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

        # Check if already hitched
        current_task = monster.current_task or {}
        if current_task.get('hitched_wagon_id'):
            return HitchWagonResponse(
                message="Monster is already hitched to a wagon",
                hitched=True,
                wagon_id=current_task.get('hitched_wagon_id')
            )

        # Find adjacent wagons
        adjacent_positions = [
            (monster.x - 1, monster.y),  # left
            (monster.x + 1, monster.y),  # right
            (monster.x, monster.y - 1),  # up
            (monster.x, monster.y + 1),  # down
        ]

        result = await session.execute(
            select(Entity).where(
                Entity.zone_id == monster.current_zone_id,
                Entity.entity_type == "wagon"
            )
        )
        wagons = result.scalars().all()

        adjacent_wagon = None
        for wagon in wagons:
            wagon_width = wagon.width or 2
            wagon_height = wagon.height or 2

            for pos in adjacent_positions:
                # Check if position is adjacent to any part of the wagon
                if (wagon.x <= pos[0] < wagon.x + wagon_width and
                    wagon.y <= pos[1] < wagon.y + wagon_height):
                    adjacent_wagon = wagon
                    break
            if adjacent_wagon:
                break

        if not adjacent_wagon:
            return HitchWagonResponse(
                message="No wagon adjacent to monster",
                hitched=False
            )

        # Check if wagon is already hitched by another monster
        wagon_metadata = adjacent_wagon.entity_metadata or {}
        if wagon_metadata.get('hitched_by') and wagon_metadata.get('hitched_by') != str(monster.id):
            return HitchWagonResponse(
                message="This wagon is already hitched by another monster",
                hitched=False
            )

        # Hitch the wagon
        current_task['hitched_wagon_id'] = str(adjacent_wagon.id)
        monster.current_task = current_task
        flag_modified(monster, 'current_task')

        # Mark wagon as hitched
        wagon_metadata['hitched_by'] = str(monster.id)
        adjacent_wagon.entity_metadata = wagon_metadata
        flag_modified(adjacent_wagon, 'entity_metadata')

        await session.commit()

        return HitchWagonResponse(
            message=f"Hitched to wagon at ({adjacent_wagon.x}, {adjacent_wagon.y})",
            hitched=True,
            wagon_id=str(adjacent_wagon.id),
            wagon_position={"x": adjacent_wagon.x, "y": adjacent_wagon.y}
        )


@app.post("/api/monsters/unhitch-wagon", response_model=HitchWagonResponse, tags=["Wagons"])
async def unhitch_wagon(request: HitchWagonRequest, token: str):
    """Unhitch a monster from its current wagon."""
    async with async_session() as session:
        player = await get_current_player(token, session)

        # Get the monster
        result = await session.execute(
            select(Monster).where(Monster.id == request.monster_id)
        )
        monster = result.scalar_one_or_none()

        if not monster:
            raise HTTPException(status_code=404, detail="Monster not found")

        # Get player's commune for ownership check
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

        # Check if hitched
        current_task = monster.current_task or {}
        hitched_wagon_id = current_task.get('hitched_wagon_id')

        if not hitched_wagon_id:
            return HitchWagonResponse(
                message="Monster is not hitched to any wagon",
                hitched=False
            )

        # Get the wagon to clear its hitched_by flag
        result = await session.execute(
            select(Entity).where(Entity.id == hitched_wagon_id)
        )
        wagon = result.scalar_one_or_none()

        if wagon:
            wagon_metadata = wagon.entity_metadata or {}
            wagon_metadata.pop('hitched_by', None)
            wagon.entity_metadata = wagon_metadata
            flag_modified(wagon, 'entity_metadata')

        # Unhitch
        current_task.pop('hitched_wagon_id', None)
        monster.current_task = current_task
        flag_modified(monster, 'current_task')

        await session.commit()

        return HitchWagonResponse(
            message="Unhitched from wagon",
            hitched=False
        )


@app.get("/api/monsters/{monster_id}/hitch-status", response_model=HitchWagonResponse, tags=["Wagons"])
async def get_hitch_status(monster_id: str, token: str):
    """Get the current hitch status of a monster."""
    async with async_session() as session:
        player = await get_current_player(token, session)

        # Get the monster
        result = await session.execute(
            select(Monster).where(Monster.id == monster_id)
        )
        monster = result.scalar_one_or_none()

        if not monster:
            raise HTTPException(status_code=404, detail="Monster not found")

        current_task = monster.current_task or {}
        hitched_wagon_id = current_task.get('hitched_wagon_id')

        if not hitched_wagon_id:
            return HitchWagonResponse(
                message="Monster is not hitched to any wagon",
                hitched=False
            )

        # Get wagon position
        result = await session.execute(
            select(Entity).where(Entity.id == hitched_wagon_id)
        )
        wagon = result.scalar_one_or_none()

        if wagon:
            return HitchWagonResponse(
                message=f"Hitched to wagon at ({wagon.x}, {wagon.y})",
                hitched=True,
                wagon_id=hitched_wagon_id,
                wagon_position={"x": wagon.x, "y": wagon.y}
            )
        else:
            # Wagon was deleted, clear hitch
            return HitchWagonResponse(
                message="Wagon no longer exists",
                hitched=False
            )


# =============================================================================
# Recording System Endpoints
# =============================================================================


@app.post("/api/monsters/recording/start", response_model=RecordingState, tags=["Recording"])
async def start_recording(request: StartRecordingRequest, token: str):
    """Start recording a sequence of actions for batch crafting playback."""
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

        # Check if already recording
        current_task = monster.current_task or {}
        if current_task.get('is_recording'):
            raise HTTPException(
                status_code=400,
                detail="Monster is already recording. Stop recording first."
            )

        # Start recording
        started_at = datetime.utcnow().isoformat()
        recording_state = {
            'is_recording': True,
            'started_at': started_at,
            'workshop_id': request.workshop_id,
            'recipe_id': request.recipe_id,
            'actions': []
        }

        monster.current_task = recording_state
        flag_modified(monster, 'current_task')
        await session.commit()

        return RecordingState(
            is_recording=True,
            started_at=started_at,
            workshop_id=request.workshop_id,
            recipe_id=request.recipe_id,
            actions=[]
        )


@app.post("/api/monsters/recording/stop", response_model=RecordingState, tags=["Recording"])
async def stop_recording(request: StopRecordingRequest, token: str):
    """Stop recording and return the recorded sequence."""
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

        # Check if currently recording
        current_task = monster.current_task or {}
        if not current_task.get('is_recording'):
            raise HTTPException(
                status_code=400,
                detail="Monster is not currently recording."
            )

        # Get the recorded actions before clearing
        recorded_state = RecordingState(
            is_recording=False,
            started_at=current_task.get('started_at'),
            workshop_id=current_task.get('workshop_id'),
            recipe_id=current_task.get('recipe_id'),
            actions=[RecordingAction(**a) for a in current_task.get('actions', [])]
        )

        # Clear the recording but keep the recorded sequence for playback
        monster.current_task = {
            'is_recording': False,
            'recorded_sequence': current_task.get('actions', []),
            'workshop_id': current_task.get('workshop_id'),
            'recipe_id': current_task.get('recipe_id')
        }
        flag_modified(monster, 'current_task')
        await session.commit()

        return recorded_state


@app.get("/api/monsters/{monster_id}/recording", response_model=RecordingState, tags=["Recording"])
async def get_recording_status(monster_id: str, token: str):
    """Get the current recording status for a monster."""
    async with async_session() as session:
        player = await get_current_player(token, session)

        # Get the monster
        result = await session.execute(
            select(Monster).where(Monster.id == monster_id)
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
                detail="You can only view recording status for your own monsters"
            )

        current_task = monster.current_task or {}

        if current_task.get('is_recording'):
            return RecordingState(
                is_recording=True,
                started_at=current_task.get('started_at'),
                workshop_id=current_task.get('workshop_id'),
                recipe_id=current_task.get('recipe_id'),
                actions=[RecordingAction(**a) for a in current_task.get('actions', [])]
            )
        else:
            return RecordingState(
                is_recording=False,
                started_at=None,
                workshop_id=None,
                recipe_id=None,
                actions=[]
            )


# =============================================================================
# Autorepeat System Endpoints
# =============================================================================


@app.post("/api/monsters/autorepeat/start", response_model=AutorepeatState, tags=["Autorepeat"])
async def start_autorepeat(request: StartAutorepeatRequest, token: str):
    """Start auto-repeating a previously recorded sequence."""
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

        current_task = monster.current_task or {}

        # Check if currently recording (can't autorepeat while recording)
        if current_task.get('is_recording'):
            raise HTTPException(
                status_code=400,
                detail="Cannot start autorepeat while recording. Stop recording first."
            )

        # Check if there's a recorded sequence
        recorded_sequence = current_task.get('recorded_sequence', [])
        if not recorded_sequence:
            raise HTTPException(
                status_code=400,
                detail="No recorded sequence available. Record a sequence first."
            )

        # Check if already playing
        if current_task.get('is_playing'):
            raise HTTPException(
                status_code=400,
                detail="Autorepeat is already running."
            )

        # Start autorepeat
        current_task['is_playing'] = True
        current_task['current_action_index'] = 0
        monster.current_task = current_task
        flag_modified(monster, 'current_task')
        await session.commit()

        return AutorepeatState(
            is_playing=True,
            current_action_index=0,
            total_actions=len(recorded_sequence),
            recorded_sequence=[RecordingAction(**a) for a in recorded_sequence]
        )


@app.post("/api/monsters/autorepeat/stop", response_model=AutorepeatState, tags=["Autorepeat"])
async def stop_autorepeat(request: StopAutorepeatRequest, token: str):
    """Stop auto-repeating the recorded sequence."""
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

        current_task = monster.current_task or {}

        # Stop autorepeat
        current_task['is_playing'] = False
        monster.current_task = current_task
        flag_modified(monster, 'current_task')
        await session.commit()

        recorded_sequence = current_task.get('recorded_sequence', [])
        return AutorepeatState(
            is_playing=False,
            current_action_index=current_task.get('current_action_index', 0),
            total_actions=len(recorded_sequence),
            recorded_sequence=[RecordingAction(**a) for a in recorded_sequence]
        )


@app.post("/api/monsters/autorepeat/step", tags=["Autorepeat"])
async def autorepeat_step(request: StartAutorepeatRequest, token: str):
    """Execute the next action in the autorepeat sequence. Returns the action taken."""
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

        current_task = monster.current_task or {}

        if not current_task.get('is_playing'):
            raise HTTPException(
                status_code=400,
                detail="Autorepeat is not running."
            )

        recorded_sequence = current_task.get('recorded_sequence', [])
        current_index = current_task.get('current_action_index', 0)

        if current_index >= len(recorded_sequence):
            # Sequence complete - loop back to start
            current_index = 0

        action = recorded_sequence[current_index]
        action_type = action.get('action_type')
        direction = action.get('direction')

        result_message = f"Executed action {current_index + 1}/{len(recorded_sequence)}: {action_type}"
        autorepeat_stopped = False
        stop_reason = None

        # Execute the action based on type
        if action_type == 'move' and direction:
            # Calculate new position
            new_x, new_y = monster.x, monster.y
            if direction == "up":
                new_y -= 1
            elif direction == "down":
                new_y += 1
            elif direction == "left":
                new_x -= 1
            elif direction == "right":
                new_x += 1

            # Update position
            monster.x = new_x
            monster.y = new_y
            result_message += f" {direction} -> ({new_x}, {new_y})"

        elif action_type == 'push' and direction:
            # For push actions, check if there's an item to push
            # Calculate target position (where the item should be)
            target_x, target_y = monster.x, monster.y
            if direction == "up":
                target_y -= 1
            elif direction == "down":
                target_y += 1
            elif direction == "left":
                target_x -= 1
            elif direction == "right":
                target_x += 1

            # Check if there's an item at target position
            item_result = await session.execute(
                select(Entity).where(
                    Entity.zone_id == monster.current_zone_id,
                    Entity.x == target_x,
                    Entity.y == target_y,
                    Entity.entity_type == "item"
                )
            )
            item_at_target = item_result.scalars().first()  # Use first() to handle multiple items

            if item_at_target:
                # There's an item - push it and move monster
                push_x, push_y = target_x, target_y
                if direction == "up":
                    push_y -= 1
                elif direction == "down":
                    push_y += 1
                elif direction == "left":
                    push_x -= 1
                elif direction == "right":
                    push_x += 1

                # Move item
                item_at_target.x = push_x
                item_at_target.y = push_y

                # Move monster to where item was
                monster.x = target_x
                monster.y = target_y
                result_message += f" pushed item {direction} -> monster at ({target_x}, {target_y})"
            else:
                # No item to push - stop autorepeat
                autorepeat_stopped = True
                stop_reason = "No ingredient available to push. Autorepeat stopped."
                current_task['is_playing'] = False
                result_message += f" - FAILED: no item at ({target_x}, {target_y})"

        elif action_type == 'deposit':
            # Deposit actions happen automatically when pushing into workshop
            # Just move the monster for now
            if direction:
                new_x, new_y = monster.x, monster.y
                if direction == "up":
                    new_y -= 1
                elif direction == "down":
                    new_y += 1
                elif direction == "left":
                    new_x -= 1
                elif direction == "right":
                    new_x += 1
                monster.x = new_x
                monster.y = new_y
            result_message += " (deposit action)"

        elif action_type == 'craft':
            # Crafting action - check if workshop has required tools
            workshop_id = action.get('workshop_id')
            if workshop_id:
                ws_result = await session.execute(
                    select(Entity).where(Entity.id == workshop_id, Entity.entity_type == "workshop")
                )
                workshop = ws_result.scalar_one_or_none()
                if workshop:
                    workshop_metadata = workshop.entity_metadata or {}
                    recipe_id = workshop_metadata.get('selected_recipe_id')

                    # Get recipe to check tool requirements
                    if recipe_id:
                        recipe_result = await session.execute(
                            select(GoodType).where(GoodType.id == recipe_id)
                        )
                        recipe = recipe_result.scalar_one_or_none()

                        if recipe and recipe.tools_required_tags:
                            # Check if workshop has all required tools
                            tool_items = workshop_metadata.get('tool_items', [])
                            available_tags = []
                            for tool in tool_items:
                                if tool.get('durability', 0) > 0:
                                    available_tags.extend(tool.get('tool_tags', []))

                            missing_tools = []
                            for required_tag in recipe.tools_required_tags:
                                if required_tag not in available_tags:
                                    missing_tools.append(required_tag)

                            if missing_tools:
                                # Stop autorepeat - tools depleted
                                autorepeat_stopped = True
                                stop_reason = f"Tool depleted: missing {', '.join(missing_tools)}. Autorepeat stopped."
                                current_task['is_playing'] = False
                                result_message += f" - FAILED: missing tools {missing_tools}"

            if not autorepeat_stopped:
                result_message += " (craft action)"

        # Increment index (unless we stopped)
        if not autorepeat_stopped:
            current_task['current_action_index'] = current_index + 1
        monster.current_task = current_task
        flag_modified(monster, 'current_task')
        await session.commit()

        response = {
            "message": result_message,
            "action": action,
            "current_index": current_index + 1,
            "total_actions": len(recorded_sequence),
            "monster_position": {"x": monster.x, "y": monster.y}
        }

        if autorepeat_stopped:
            response["stopped"] = True
            response["stop_reason"] = stop_reason

        return response


@app.get("/api/monsters/{monster_id}/autorepeat", response_model=AutorepeatState, tags=["Autorepeat"])
async def get_autorepeat_status(monster_id: str, token: str):
    """Get the current autorepeat status for a monster."""
    async with async_session() as session:
        player = await get_current_player(token, session)

        # Get the monster
        result = await session.execute(
            select(Monster).where(Monster.id == monster_id)
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
                detail="You can only view autorepeat status for your own monsters"
            )

        current_task = monster.current_task or {}
        recorded_sequence = current_task.get('recorded_sequence', [])

        return AutorepeatState(
            is_playing=current_task.get('is_playing', False),
            current_action_index=current_task.get('current_action_index', 0),
            total_actions=len(recorded_sequence),
            recorded_sequence=[RecordingAction(**a) for a in recorded_sequence]
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


class SetActivePushRequest(BaseModel):
    item_id: str
    monster_id: Optional[str] = None  # None means clear the flag


@app.post("/api/debug/item/set-active-push", tags=["Debug"])
async def set_active_push(request: SetActivePushRequest):
    """Set or clear the being_pushed_by flag on an item (for testing active-push protection)."""
    async with async_session() as session:
        result = await session.execute(
            select(Entity).where(Entity.id == request.item_id)
        )
        item = result.scalar_one_or_none()

        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        item_metadata = item.entity_metadata or {}

        if request.monster_id:
            # Set the flag
            item_metadata['being_pushed_by'] = request.monster_id
        else:
            # Clear the flag
            item_metadata.pop('being_pushed_by', None)

        item.entity_metadata = item_metadata
        flag_modified(item, 'entity_metadata')
        await session.commit()

        return {
            "message": "Active push flag updated",
            "item_id": item.id,
            "being_pushed_by": item_metadata.get('being_pushed_by')
        }


@app.get("/api/debug/item/{item_id}/push-status", tags=["Debug"])
async def get_item_push_status(item_id: str):
    """Check the being_pushed_by status of an item."""
    async with async_session() as session:
        result = await session.execute(
            select(Entity).where(Entity.id == item_id)
        )
        item = result.scalar_one_or_none()

        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        item_metadata = item.entity_metadata or {}

        return {
            "item_id": item.id,
            "item_name": item_metadata.get('name', 'Unknown'),
            "being_pushed_by": item_metadata.get('being_pushed_by'),
            "position": {"x": item.x, "y": item.y}
        }


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
                "width": e.width,
                "height": e.height,
                "metadata": e.entity_metadata
            }
            for e in entities
        ]


@app.get("/api/zones/{zone_id}/monsters", tags=["Zones"])
async def get_zone_monsters(zone_id: str):
    """Get all monsters in a zone (for multiplayer visibility)."""
    async with async_session() as session:
        result = await session.execute(
            select(Monster).where(Monster.current_zone_id == zone_id)
        )
        monsters = result.scalars().all()

        # Also get commune info for each monster to show owner
        monster_list = []
        for m in monsters:
            # Get commune for this monster
            result = await session.execute(
                select(Commune).where(Commune.id == m.commune_id)
            )
            commune = result.scalar_one_or_none()

            monster_list.append({
                "id": m.id,
                "name": m.name,
                "monster_type": m.monster_type,
                "x": m.x,
                "y": m.y,
                "commune_id": m.commune_id,
                "commune_name": commune.name if commune else "Unknown"
            })

        return monster_list


# =============================================================================
# Recipes Endpoints
# =============================================================================

@app.get("/api/recipes", tags=["Recipes"])
async def get_all_recipes():
    """Get all available recipes (good types that require a workshop)."""
    async with async_session() as session:
        result = await session.execute(
            select(GoodType).where(GoodType.requires_workshop.isnot(None))
        )
        recipes = result.scalars().all()

        return [
            {
                "id": r.id,
                "name": r.name,
                "requires_workshop": r.requires_workshop,
                "production_time": r.production_time,
                "difficulty_rating": r.difficulty_rating,
                "input_goods_tags": r.input_goods_tags_required,
                "tools_required": r.tools_required_tags
            }
            for r in recipes
        ]


@app.get("/api/recipes/workshop/{workshop_type}", tags=["Recipes"])
async def get_workshop_recipes(workshop_type: str):
    """Get recipes available at a specific workshop type."""
    async with async_session() as session:
        result = await session.execute(
            select(GoodType).where(GoodType.requires_workshop == workshop_type)
        )
        recipes = result.scalars().all()

        return [
            {
                "id": r.id,
                "name": r.name,
                "requires_workshop": r.requires_workshop,
                "production_time": r.production_time,
                "difficulty_rating": r.difficulty_rating,
                "input_goods_tags": r.input_goods_tags_required,
                "tools_required": r.tools_required_tags
            }
            for r in recipes
        ]


@app.post("/api/debug/recipes/seed", tags=["Debug"])
async def seed_recipes():
    """Seed sample recipes for testing."""
    async with async_session() as session:
        # Check if recipes already exist
        result = await session.execute(select(GoodType).limit(1))
        if result.scalar_one_or_none():
            return {"message": "Recipes already seeded"}

        # Sample smithing recipes
        sample_recipes = [
            GoodType(
                name="Iron Ingot",
                type_tags=["metal", "ingot"],
                requires_workshop="smithing",
                production_time=120,
                difficulty_rating=2,
                input_goods_tags_required=[["ore", "iron"]],
                tools_required_tags=["hammer"],
                relevant_ability_score="STR"
            ),
            GoodType(
                name="Steel Ingot",
                type_tags=["metal", "ingot", "refined"],
                requires_workshop="smithing",
                production_time=180,
                difficulty_rating=4,
                input_goods_tags_required=[["metal", "iron"], ["fuel", "coal"]],
                tools_required_tags=["hammer", "tongs"],
                relevant_ability_score="STR"
            ),
            GoodType(
                name="Iron Sword",
                type_tags=["weapon", "sword"],
                requires_workshop="smithing",
                production_time=300,
                difficulty_rating=5,
                input_goods_tags_required=[["metal", "iron"]],
                tools_required_tags=["hammer", "anvil"],
                relevant_ability_score="DEX"
            ),
            GoodType(
                name="Iron Nails",
                type_tags=["metal", "fastener"],
                requires_workshop="smithing",
                production_time=60,
                difficulty_rating=1,
                input_goods_tags_required=[["metal", "iron"]],
                tools_required_tags=["hammer"],
                relevant_ability_score="DEX"
            ),
            # Weaving recipes
            GoodType(
                name="Cloth",
                type_tags=["textile", "cloth"],
                requires_workshop="weaving",
                production_time=90,
                difficulty_rating=2,
                input_goods_tags_required=[["fiber", "thread"]],
                tools_required_tags=["loom"],
                relevant_ability_score="DEX"
            ),
            GoodType(
                name="Rope",
                type_tags=["textile", "rope"],
                requires_workshop="weaving",
                production_time=60,
                difficulty_rating=1,
                input_goods_tags_required=[["fiber"]],
                tools_required_tags=[],
                relevant_ability_score="STR"
            ),
        ]

        for recipe in sample_recipes:
            session.add(recipe)

        await session.commit()
        return {"message": f"Seeded {len(sample_recipes)} recipes"}


@app.patch("/api/debug/recipes/{recipe_id}", tags=["Debug"])
async def update_recipe(recipe_id: int, primary_applied_skill: str = None):
    """Update recipe fields (debug only)."""
    async with async_session() as session:
        result = await session.execute(
            select(GoodType).where(GoodType.id == recipe_id)
        )
        recipe = result.scalar_one_or_none()

        if not recipe:
            raise HTTPException(status_code=404, detail="Recipe not found")

        if primary_applied_skill:
            recipe.primary_applied_skill = primary_applied_skill

        await session.commit()
        return {"id": recipe.id, "name": recipe.name, "primary_applied_skill": recipe.primary_applied_skill}


@app.post("/api/debug/tech-tree/load", tags=["Debug"])
async def load_tech_tree():
    """Load tech tree from JSON file (data/tech_tree/good_types.json)."""
    import json
    import os

    # Get the path to the JSON file
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "data", "tech_tree", "good_types.json")

    if not os.path.exists(json_path):
        raise HTTPException(status_code=404, detail=f"Tech tree file not found at {json_path}")

    with open(json_path, 'r') as f:
        data = json.load(f)

    good_types_data = data.get('good_types', [])
    if not good_types_data:
        raise HTTPException(status_code=400, detail="No good_types found in JSON file")

    async with async_session() as session:
        # Clear existing good types
        await session.execute(delete(GoodType))

        # Insert new good types
        created_count = 0
        for gt_data in good_types_data:
            good_type = GoodType(
                name=gt_data.get('name'),
                type_tags=gt_data.get('type_tags', []),
                storage_volume=gt_data.get('storage_volume', 1),
                has_quality=gt_data.get('has_quality', 1),
                is_fixed_quantity=gt_data.get('is_fixed_quantity', 0),
                requires_workshop=gt_data.get('requires_workshop'),
                relevant_ability_score=gt_data.get('relevant_ability_score'),
                transferable_skills=gt_data.get('transferable_skills', []),
                primary_applied_skill=gt_data.get('primary_applied_skill'),
                secondary_applied_skills=gt_data.get('secondary_applied_skills', []),
                difficulty_rating=gt_data.get('difficulty_rating', 1),
                production_time=gt_data.get('production_time', 60),
                value_added_shares=gt_data.get('value_added_shares', 1),
                quantity=gt_data.get('quantity', 1),
                input_goods_tags_required=gt_data.get('input_goods_tags_required', []),
                tools_required_tags=gt_data.get('tools_required_tags', []),
                tools_weights=gt_data.get('tools_weights', {}),
                raw_material_base_value=gt_data.get('raw_material_base_value'),
                raw_material_rarity=gt_data.get('raw_material_rarity'),
                raw_material_density=gt_data.get('raw_material_density')
            )
            session.add(good_type)
            created_count += 1

        await session.commit()

    return {
        "message": f"Loaded {created_count} good types from tech tree",
        "count": created_count
    }


@app.get("/api/good-types", tags=["Recipes"])
async def get_all_good_types():
    """Get all good types in the tech tree."""
    async with async_session() as session:
        result = await session.execute(select(GoodType).order_by(GoodType.id))
        good_types = result.scalars().all()

        return [
            {
                "id": gt.id,
                "name": gt.name,
                "type_tags": gt.type_tags or [],
                "storage_volume": gt.storage_volume,
                "has_quality": gt.has_quality,
                "requires_workshop": gt.requires_workshop,
                "relevant_ability_score": gt.relevant_ability_score,
                "transferable_skills": gt.transferable_skills or [],
                "primary_applied_skill": gt.primary_applied_skill,
                "difficulty_rating": gt.difficulty_rating,
                "production_time": gt.production_time,
                "input_goods_tags_required": gt.input_goods_tags_required or [],
                "tools_required_tags": gt.tools_required_tags or []
            }
            for gt in good_types
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


class UpdateEntityRequest(BaseModel):
    metadata: dict


@app.patch("/api/debug/entities/{entity_id}", tags=["Debug"])
async def update_entity(entity_id: str, request: UpdateEntityRequest):
    """Update entity metadata (debug only)."""
    async with async_session() as session:
        result = await session.execute(
            select(Entity).where(Entity.id == entity_id)
        )
        entity = result.scalar_one_or_none()

        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")

        entity.entity_metadata = request.metadata
        flag_modified(entity, 'entity_metadata')
        await session.commit()

        return {
            "id": entity.id,
            "metadata": entity.entity_metadata
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


@app.get("/api/debug/communes/{commune_id}/cost-info", tags=["Debug"])
async def debug_get_commune_cost_info(commune_id: str):
    """Debug endpoint to view a commune's cost multiplier info."""
    async with async_session() as session:
        result = await session.execute(
            select(Commune).where(Commune.id == commune_id)
        )
        commune = result.scalar_one_or_none()

        if not commune:
            raise HTTPException(status_code=404, detail="Commune not found")

        total_spent = int(commune.total_renown_spent or "0")
        multiplier = calculate_cost_multiplier(total_spent)

        # Show adjusted costs for all monster types
        adjusted_costs = {
            name: get_adjusted_cost(data["cost"], commune)
            for name, data in MONSTER_TYPES.items()
        }

        return {
            "commune_id": commune.id,
            "commune_name": commune.name,
            "renown": int(commune.renown),
            "total_renown_spent": total_spent,
            "cost_multiplier": round(multiplier, 2),
            "adjusted_monster_costs": adjusted_costs
        }


@app.post("/api/debug/communes/{commune_id}/set-spending", tags=["Debug"])
async def debug_set_commune_spending(commune_id: str, total_spent: int):
    """Debug endpoint to set a commune's total spending (for testing cost multiplier)."""
    async with async_session() as session:
        result = await session.execute(
            select(Commune).where(Commune.id == commune_id)
        )
        commune = result.scalar_one_or_none()

        if not commune:
            raise HTTPException(status_code=404, detail="Commune not found")

        old_spent = int(commune.total_renown_spent or "0")
        commune.total_renown_spent = str(total_spent)
        await session.commit()

        new_multiplier = calculate_cost_multiplier(total_spent)

        return {
            "message": f"Updated total_renown_spent from {old_spent} to {total_spent}",
            "commune_id": commune.id,
            "new_cost_multiplier": round(new_multiplier, 2)
        }


@app.post("/api/debug/workshops/{workshop_id}/complete-crafting", tags=["Debug"])
async def debug_complete_crafting(workshop_id: str):
    """Debug endpoint to instantly complete crafting in a workshop."""
    async with async_session() as session:
        result = await session.execute(
            select(Entity).where(Entity.id == workshop_id)
        )
        workshop = result.scalar_one_or_none()

        if not workshop:
            raise HTTPException(status_code=404, detail="Workshop not found")

        if workshop.entity_type != "workshop":
            raise HTTPException(status_code=400, detail="Entity is not a workshop")

        workshop_metadata = workshop.entity_metadata or {}
        if not workshop_metadata.get('is_crafting'):
            return {"message": "Workshop is not currently crafting"}

        # Set started_at to far in the past to instantly complete
        from datetime import timedelta
        past_time = datetime.utcnow() - timedelta(hours=1)
        workshop_metadata['crafting_started_at'] = past_time.isoformat()
        workshop.entity_metadata = workshop_metadata
        flag_modified(workshop, 'entity_metadata')

        await session.commit()

        return {"message": "Crafting time accelerated. Poll status to complete."}


@app.post("/api/debug/monsters/{monster_id}/advance-skill-time", tags=["Debug"])
async def debug_advance_skill_time(monster_id: str, days: float = 1.0):
    """Debug endpoint to simulate skill time passage for testing decay.

    Moves the skill_last_used timestamps back by the specified number of game days.
    This simulates the passage of time without actually waiting.

    Args:
        monster_id: The ID of the monster
        days: Number of game days to simulate (default 1.0)
    """
    from datetime import timedelta

    async with async_session() as session:
        result = await session.execute(
            select(Monster).where(Monster.id == monster_id)
        )
        monster = result.scalar_one_or_none()

        if not monster:
            raise HTTPException(status_code=404, detail="Monster not found")

        skill_last_used = monster.skill_last_used or {}
        applied_skills = monster.applied_skills or {}

        # If no skill_last_used but has applied_skills, initialize timestamps to now
        if not skill_last_used and applied_skills:
            now = datetime.utcnow()
            skill_last_used = {skill: now.isoformat() for skill in applied_skills.keys()}
            monster.skill_last_used = skill_last_used
            flag_modified(monster, 'skill_last_used')
        elif not skill_last_used:
            return {"message": "Monster has no skills"}

        # Game time: 1 real second = 30 game seconds
        # So 1 game day = (24 * 60 * 60) / 30 real seconds = 2880 real seconds = 48 minutes
        real_seconds_per_game_day = (24 * 60 * 60) / GAME_TIME_MULTIPLIER
        real_seconds_to_subtract = real_seconds_per_game_day * days

        # Move all skill timestamps back in time
        updated_skills = {}
        for skill_name, timestamp_str in skill_last_used.items():
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
                new_timestamp = timestamp - timedelta(seconds=real_seconds_to_subtract)
                updated_skills[skill_name] = new_timestamp.isoformat()
            except (ValueError, TypeError):
                updated_skills[skill_name] = timestamp_str

        monster.skill_last_used = updated_skills
        flag_modified(monster, 'skill_last_used')

        # Calculate what the skills will be after decay
        original_skills = monster.applied_skills or {}
        decayed_skills = calculate_skill_decay(monster)

        await session.commit()

        return {
            "message": f"Advanced skill time by {days} game days",
            "original_skills": original_skills,
            "decayed_skills": decayed_skills,
            "wis": monster.wis,
            "decay_modifier": 1.0 - (monster.wis - 10) * 0.1
        }


@app.get("/api/debug/monsters/{monster_id}/upkeep-status", tags=["Debug"])
async def debug_upkeep_status(monster_id: str):
    """Debug endpoint to check upkeep status for a monster."""
    async with async_session() as session:
        result = await session.execute(
            select(Monster).where(Monster.id == monster_id)
        )
        monster = result.scalar_one_or_none()

        if not monster:
            raise HTTPException(status_code=404, detail="Monster not found")

        upkeep_info = await calculate_upkeep_due(monster, session)

        return {
            "monster_id": monster.id,
            "monster_name": monster.name,
            "monster_type": monster.monster_type,
            **upkeep_info
        }


@app.post("/api/debug/monsters/{monster_id}/advance-upkeep-time", tags=["Debug"])
async def debug_advance_upkeep_time(monster_id: str, days: float = 28.0):
    """Debug endpoint to simulate upkeep time passage for testing.

    Moves the last_upkeep_paid timestamp back by the specified number of game days.
    This simulates the passage of time without actually waiting.

    Args:
        monster_id: The ID of the monster
        days: Number of game days to simulate (default 28.0 - one full cycle)
    """
    from datetime import timedelta

    try:
        async with async_session() as session:
            result = await session.execute(
                select(Monster).where(Monster.id == monster_id)
            )
            monster = result.scalar_one_or_none()

            if not monster:
                raise HTTPException(status_code=404, detail="Monster not found")

            # Use created_at as the baseline
            current_time = monster.created_at

            # Game time: 1 real second = 30 game seconds
            # So 1 game day = (24 * 60 * 60) / 30 real seconds = 2880 real seconds = 48 minutes
            real_seconds_per_game_day = (24 * 60 * 60) / GAME_TIME_MULTIPLIER
            real_seconds_to_subtract = real_seconds_per_game_day * days

            # Move upkeep timestamp back in time
            new_time = current_time - timedelta(seconds=real_seconds_to_subtract)

            # Use raw SQL to update the column (since it's not in the model)
            await session.execute(
                text("UPDATE monsters SET last_upkeep_paid = :new_time WHERE id = :monster_id"),
                {"new_time": new_time.isoformat(), "monster_id": monster_id}
            )

            await session.commit()

            # Calculate upkeep status manually based on new_time
            now = datetime.utcnow()
            real_seconds_since_payment = (now - new_time).total_seconds()
            game_seconds_since_payment = real_seconds_since_payment * GAME_TIME_MULTIPLIER
            game_days_since_payment = game_seconds_since_payment / (24 * 60 * 60)
            UPKEEP_CYCLE_DAYS = 28
            days_until_due = UPKEEP_CYCLE_DAYS - game_days_since_payment
            upkeep_due = game_days_since_payment >= UPKEEP_CYCLE_DAYS
            monster_type_info = MONSTER_TYPES.get(monster.monster_type, {})
            upkeep_cost = monster_type_info.get("cost", 50)

            return {
                "message": f"Advanced upkeep time by {days} game days",
                "monster_id": monster.id,
                "monster_name": monster.name,
                "new_last_upkeep_paid": new_time.isoformat(),
                "upkeep_due": upkeep_due,
                "upkeep_cost": upkeep_cost,
                "days_since_payment": round(game_days_since_payment, 2),
                "days_until_due": round(days_until_due, 2)
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@app.post("/api/debug/run-migrations", tags=["Debug"])
async def debug_run_migrations():
    """Debug endpoint to run database migrations manually."""
    results = []
    async with async_session() as session:
        # Check if last_upkeep_paid column exists
        try:
            check_result = await session.execute(
                text("SELECT last_upkeep_paid FROM monsters LIMIT 1")
            )
            results.append("Column last_upkeep_paid exists")
        except Exception as e:
            results.append(f"Column check failed: {str(e)}")
            await session.rollback()
            # Try to add the column
            try:
                await session.execute(
                    text("ALTER TABLE monsters ADD COLUMN last_upkeep_paid TIMESTAMP")
                )
                await session.commit()
                results.append("Successfully added last_upkeep_paid column")
            except Exception as add_err:
                await session.rollback()
                results.append(f"Failed to add column: {str(add_err)}")

    return {"results": results}


@app.post("/api/debug/monsters/{monster_id}/advance-age", tags=["Debug"])
async def debug_advance_monster_age(monster_id: str, days: float = 30.0):
    """Debug endpoint to advance a monster's age for testing.

    Moves the created_at timestamp back by the specified number of game days.
    This simulates the monster aging without actually waiting.

    Args:
        monster_id: The ID of the monster
        days: Number of game days to age the monster (default 30.0)
    """
    from datetime import timedelta

    async with async_session() as session:
        result = await session.execute(
            select(Monster).where(Monster.id == monster_id)
        )
        monster = result.scalar_one_or_none()

        if not monster:
            raise HTTPException(status_code=404, detail="Monster not found")

        # Get current stats before aging
        stats_before = {
            "str": monster.str_,
            "dex": monster.dex,
            "con": monster.con,
            "int": monster.int_,
            "wis": monster.wis,
            "cha": monster.cha
        }
        age_before = monster.age_days
        age_bonus_before = monster.age_bonus

        # Game time: 1 real second = 30 game seconds
        # So 1 game day = (24 * 60 * 60) / 30 real seconds = 2880 real seconds = 48 minutes
        real_seconds_per_game_day = (24 * 60 * 60) / GAME_TIME_MULTIPLIER
        real_seconds_to_subtract = real_seconds_per_game_day * days

        # Move created_at back in time
        new_created_at = monster.created_at - timedelta(seconds=real_seconds_to_subtract)
        monster.created_at = new_created_at

        await session.commit()

        # Calculate new age and bonus
        age_after = monster.age_days
        age_bonus_after = monster.age_bonus

        # Get stats with age bonus applied
        stats_after = {
            "str": monster.str_ + age_bonus_after,
            "dex": monster.dex + age_bonus_after,
            "con": monster.con + age_bonus_after,
            "int": monster.int_ + age_bonus_after,
            "wis": monster.wis + age_bonus_after,
            "cha": monster.cha + age_bonus_after
        }

        return {
            "message": f"Advanced monster age by {days} game days",
            "monster_id": monster.id,
            "monster_name": monster.name,
            "age_before": age_before,
            "age_after": age_after,
            "age_bonus_before": age_bonus_before,
            "age_bonus_after": age_bonus_after,
            "base_stats": stats_before,
            "stats_with_bonus": stats_after
        }


@app.post("/api/debug/monsters/{monster_id}/collect-upkeep", tags=["Debug"])
async def debug_collect_upkeep(monster_id: str):
    """Debug endpoint to trigger upkeep collection for a monster.

    If upkeep is due, deducts the cost from the commune's renown.
    """
    async with async_session() as session:
        result = await session.execute(
            select(Monster).where(Monster.id == monster_id)
        )
        monster = result.scalar_one_or_none()

        if not monster:
            raise HTTPException(status_code=404, detail="Monster not found")

        # Get the commune
        result = await session.execute(
            select(Commune).where(Commune.id == monster.commune_id)
        )
        commune = result.scalar_one_or_none()

        if not commune:
            raise HTTPException(status_code=404, detail="Commune not found")

        # Get upkeep info before collection
        upkeep_before = await calculate_upkeep_due(monster, session)
        renown_before = int(commune.renown)

        # Process upkeep
        result = await process_monster_upkeep(monster, commune, session)

        await session.commit()

        return {
            "monster_id": monster.id,
            "monster_name": monster.name,
            "monster_type": monster.monster_type,
            "renown_before": renown_before,
            "upkeep_info_before": upkeep_before,
            "collection_result": result,
            "renown_after": int(commune.renown)
        }


@app.post("/api/debug/monsters/{monster_id}/teleport", tags=["Debug"])
async def debug_teleport_monster(monster_id: str, x: int, y: int):
    """Debug endpoint to teleport a monster to a specific position."""
    async with async_session() as session:
        result = await session.execute(
            select(Monster).where(Monster.id == monster_id)
        )
        monster = result.scalar_one_or_none()

        if not monster:
            raise HTTPException(status_code=404, detail="Monster not found")

        old_x, old_y = monster.x, monster.y
        monster.x = x
        monster.y = y
        await session.commit()

        return {
            "message": f"Teleported {monster.name} from ({old_x},{old_y}) to ({x},{y})",
            "monster_id": monster.id,
            "old_position": {"x": old_x, "y": old_y},
            "new_position": {"x": x, "y": y}
        }


@app.post("/api/debug/monsters/{monster_id}/move", tags=["Debug"])
async def debug_move_monster(monster_id: str, direction: str):
    """Debug endpoint to move a monster in a direction (bypasses authentication).

    This allows testing movement/collision without needing a valid session token.
    """
    async with async_session() as session:
        result = await session.execute(
            select(Monster).where(Monster.id == monster_id)
        )
        monster = result.scalar_one_or_none()

        if not monster:
            raise HTTPException(status_code=404, detail="Monster not found")

        # Calculate new position
        new_x, new_y = monster.x, monster.y
        if direction == "up":
            new_y -= 1
        elif direction == "down":
            new_y += 1
        elif direction == "left":
            new_x -= 1
        elif direction == "right":
            new_x += 1
        else:
            raise HTTPException(status_code=400, detail="Invalid direction")

        # Get zone for collision detection
        zone = None
        if monster.current_zone_id:
            result = await session.execute(
                select(Zone).where(Zone.id == monster.current_zone_id)
            )
            zone = result.scalar_one_or_none()

        zone_width = zone.width if zone else 100
        zone_height = zone.height if zone else 100

        # Check bounds
        if new_x < 0 or new_y < 0 or new_x >= zone_width or new_y >= zone_height:
            return {"blocked": True, "reason": "out_of_bounds", "monster_position": {"x": monster.x, "y": monster.y}}

        # Check terrain
        terrain_data = zone.terrain_data if zone else None
        if is_terrain_blocked(terrain_data, new_x, new_y):
            return {"blocked": True, "reason": "terrain", "monster_position": {"x": monster.x, "y": monster.y}}

        # Check for pushable items (including multi-cell entities)
        item_at_target = await get_entity_at_position(
            session, monster.current_zone_id, new_x, new_y, entity_type="item"
        )
        if not item_at_target:
            item_at_target = await get_entity_at_position(
                session, monster.current_zone_id, new_x, new_y, entity_type="wagon"
            )

        pushed_item = None
        if item_at_target:
            # Check if item is being actively pushed by another player
            item_metadata = item_at_target.entity_metadata or {}
            being_pushed_by = item_metadata.get('being_pushed_by')
            if being_pushed_by and being_pushed_by != str(monster.id):
                # Item is being pushed by another player - reject this push
                return {"blocked": True, "reason": "being_pushed_by_other", "monster_position": {"x": monster.x, "y": monster.y}}

            # Check if monster can push this item based on weight
            can_push, push_reason = can_monster_push_item(monster, item_at_target)
            if not can_push:
                return {"blocked": True, "reason": "item_too_heavy", "monster_position": {"x": monster.x, "y": monster.y},
                        "weight_info": {"item_weight": get_item_weight(item_at_target), "capacity": get_monster_transport_capacity(monster)}}

            # Mark item as being pushed (active-push protection)
            item_metadata['being_pushed_by'] = str(monster.id)
            item_at_target.entity_metadata = item_metadata
            flag_modified(item_at_target, 'entity_metadata')

            # Calculate push destination
            push_x, push_y = new_x, new_y
            if direction == "up":
                push_y -= 1
            elif direction == "down":
                push_y += 1
            elif direction == "left":
                push_x -= 1
            elif direction == "right":
                push_x += 1

            # Check if push destination is blocked
            if push_x < 0 or push_y < 0 or push_x >= zone_width or push_y >= zone_height:
                # Clear push protection on failure
                item_metadata.pop('being_pushed_by', None)
                item_at_target.entity_metadata = item_metadata
                flag_modified(item_at_target, 'entity_metadata')
                return {"blocked": True, "reason": "push_out_of_bounds", "monster_position": {"x": monster.x, "y": monster.y}}

            if is_terrain_blocked(terrain_data, push_x, push_y):
                # Clear push protection on failure
                item_metadata.pop('being_pushed_by', None)
                item_at_target.entity_metadata = item_metadata
                flag_modified(item_at_target, 'entity_metadata')
                return {"blocked": True, "reason": "push_terrain", "monster_position": {"x": monster.x, "y": monster.y}}

            # Check if push destination is blocked by another entity (multi-cell aware)
            is_blocked = await is_position_blocked_by_entity(
                session, monster.current_zone_id, push_x, push_y,
                entity_types=["item", "wagon"],
                exclude_entity_id=item_at_target.id
            )
            if is_blocked:
                # Clear push protection on failure
                item_metadata.pop('being_pushed_by', None)
                item_at_target.entity_metadata = item_metadata
                flag_modified(item_at_target, 'entity_metadata')
                return {"blocked": True, "reason": "push_blocked_by_entity", "monster_position": {"x": monster.x, "y": monster.y}}

            # Move the item and clear push protection
            item_at_target.x = push_x
            item_at_target.y = push_y
            item_metadata.pop('being_pushed_by', None)  # Clear active-push protection
            item_at_target.entity_metadata = item_metadata
            flag_modified(item_at_target, 'entity_metadata')
            pushed_item = {
                "id": item_at_target.id,
                "type": item_at_target.entity_type,
                "new_position": {"x": push_x, "y": push_y}
            }

        # Move the monster
        monster.x = new_x
        monster.y = new_y
        await session.commit()

        return {
            "blocked": False,
            "monster_position": {"x": new_x, "y": new_y},
            "pushed_item": pushed_item
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
