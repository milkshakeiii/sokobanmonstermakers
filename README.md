# Monster Workshop

A cooperative crafting game with a traditional roguelike/ASCII aesthetic using pyunicodegame for beautiful unicode graphics with particles, animations, and effects.

## Overview

Players control monsters in a persistent 2D grid world, optimizing production lines by physically pushing items around in a Sokoban-like manner. The game uses MonsterMakers economy mechanics (renown, skills, crafting) but embodies them in a physical world where crafting means pushing ingredients into workshops, and everything exists as tangible objects on the grid.

**"Sharing is good"** - the game encourages cooperation through shared workshops and items that benefit all contributors via the share distribution system.

## Features

- **Physical Crafting**: Push ingredients into workshops, no abstract menus
- **Recording System**: Record complex crafting sequences and auto-repeat them
- **Skill Progression**: Skills improve while working (INT bonus), decay when unused (WIS reduces)
- **Monster Types**: 5 unique monster types (Cyclops, Elf, Goblin, Orc, Troll) with different abilities
- **Share Economy**: All contributors to a product receive credit (producers, tool makers, transporters)
- **Multiplayer**: See other players, shared workshops, persistent world
- **Offline Progression**: Monsters continue auto-repeating while logged out

## Technology Stack

### Frontend
- **Framework**: Python + pyunicodegame
- **Rendering**: Unicode TUI-style graphics with sprites, animations, particles, bloom, lighting
- **Font**: Unifont (8x16 duospace, full Unicode coverage)

### Backend
- **Framework**: Python + gridtickmultiplayer architecture
- **Runtime**: Python 3.11+
- **Async**: asyncio
- **WebSockets**: FastAPI WebSocket support
- **Database**: SQLite (via aiosqlite)
- **ORM**: SQLAlchemy (async)

## Quick Start

### Prerequisites

- Python 3.11 or higher
- Virtual environment (venv or similar)

### Setup

```bash
# Run the setup script
./init.sh

# Or manually:
python3 -m venv venv
source venv/bin/activate
pip install fastapi uvicorn[standard] websockets sqlalchemy aiosqlite pydantic passlib[bcrypt] pygame
```

### Running the Application

```bash
# Activate virtual environment
source venv/bin/activate

# Start backend server
cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000

# In another terminal, start frontend client
source venv/bin/activate
cd frontend && python3 main.py
```

### Access Points

- **API Server**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **WebSocket**: ws://localhost:8000/ws

## Project Structure

```
monster-workshop/
├── init.sh              # Environment setup script
├── README.md            # This file
├── backend/             # Server-side code
│   ├── main.py          # FastAPI application
│   ├── models/          # SQLAlchemy models
│   ├── api/             # REST endpoints
│   ├── websocket/       # WebSocket handlers
│   ├── game/            # Game logic module
│   └── data/            # Tech tree, zone data
├── frontend/            # Client-side code
│   ├── main.py          # pyunicodegame application
│   ├── renderer/        # Rendering components
│   ├── ui/              # UI panels and overlays
│   └── assets/          # Sprites, fonts
├── data/                # Shared game data
│   ├── zones/           # Zone definitions
│   └── tech_tree/       # Good types, recipes
├── tests/               # Test suite
└── deps/                # External dependencies
    ├── pyunicodegame/
    └── gridtickmultiplayer/
```

## Game Concepts

### Grid System
- Cell size: 8x16 pixels (one narrow unicode character)
- Standard items: 2 cells wide (16x16 pixels, double-width unicode chars)
- Viewport: 60 cells wide x 20 cells tall

### Monster Types

| Type    | Cost   | Specialty                              |
|---------|--------|----------------------------------------|
| Cyclops | 100    | High STR (18), CON (16) - Heavy labor  |
| Elf     | 150    | High INT (18), DEX (16) - Skilled work |
| Goblin  | 50     | High DEX (18), CHA (16) - Fast + value |
| Orc     | 2000   | High STR (16), CON (18) - Premium      |
| Troll   | 1      | Massive equipment capacity             |

### Ability Scores (1-18 scale)

- **STR**: Bonus to quantity produced
- **DEX**: Reduces production task time
- **CON**: Reduces transport time
- **INT**: Bonus to learning skills
- **WIS**: Bonus to quality, reduces skill decay
- **CHA**: Bonus to good value

### Economy

- **Renown**: Earned by delivering scored goods
- **Shares**: All contributors get credit (producers, tool makers, transporters)
- **Upkeep**: 28-day cycle, monsters cost renown upkeep
- **Cost Multiplier**: Spending renown increases future costs

## API Endpoints

### REST Authentication
- `POST /api/auth/register` - Register new player
- `POST /api/auth/login` - Login and get session token
- `POST /api/auth/logout` - Invalidate session
- `GET /api/auth/me` - Get current player info

### REST Zones
- `GET /api/zones` - List all zones
- `GET /api/zones/{zone_id}` - Get zone details

### WebSocket
- `WS /ws` - Main game connection

### Debug (Development Only)
- `POST /api/debug/tick/pause` - Pause tick engine
- `POST /api/debug/tick/resume` - Resume tick engine
- `POST /api/debug/tick/step` - Advance single tick
- `GET /api/debug/zones/{zone_id}/state` - Inspect zone state
- `GET /api/debug/entities/{entity_id}` - Inspect entity
- `GET /api/debug/connections` - View connected players

## Architecture Principles

1. **Server Authoritative**: All game logic runs on server. Clients send intents, server validates.
2. **Data-Driven**: Towns, workshops, tech tree stored as pure data.
3. **Physical Embodiment**: Everything exists on the grid. No abstract menus.
4. **Sharing Is Good**: Anyone can use anyone's workshop/items. Using resources benefits owner via shares.
5. **Polish From Day One**: Heavy use of effects, animations, particles.

## Development

### Running Tests
```bash
pytest tests/
```

### Linting
```bash
pylint backend/ frontend/
```

## License

[License information to be added]

## Contributing

[Contribution guidelines to be added]
