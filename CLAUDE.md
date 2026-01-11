# Monster Workshop - Development Notes

## Running the Application

### Prerequisites

- Python 3.10+
- The gridtickmultiplayer backend at `~/Documents/github/gridtickmultiplayer`
- The pyunicodegame library at `~/Documents/github/pyunicodegame`

### Backend Server

The backend uses the gridtickmultiplayer framework with our game module.

```bash
cd ~/Documents/github/gridtickmultiplayer
source venv/bin/activate
PYTHONPATH="/home/henry/Documents/sokobanmonstermakers/backend" \
GAME_MODULE="monster_workshop_game.main" \
DATABASE_URL="sqlite+aiosqlite:///./gridbackend.db" \
uvicorn grid_backend.main:app --port 8000
```

To start fresh (clear database):
```bash
rm ~/Documents/github/gridtickmultiplayer/gridbackend.db
```

### Frontend Client

```bash
cd ~/Documents/sokobanmonstermakers
source venv/bin/activate
python3 client/main.py
```

### Controls

- WASD or Arrow Keys: Move monster
- Walk into items to push them
- Q: Quit

## Project Structure

```
backend/
  monster_workshop_game/    # Game logic module
  data/                     # Game data (monsters, skills, recipes)
  tests/                    # Pytest test suite

client/
  main.py                   # Pygame/pyunicodegame client
  requirements.txt          # Client dependencies
```

## Running Tests

```bash
cd ~/Documents/sokobanmonstermakers
source venv/bin/activate
pytest backend/tests/ -v
```
