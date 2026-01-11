#!/bin/bash
set -e

# Path setup
PROJECT_ROOT="$(pwd)"
GRID_BACKEND_PATH="$HOME/Documents/github/gridtickmultiplayer"

# Activate virtual environment
source ../venv/bin/activate

# Add paths to PYTHONPATH
export PYTHONPATH="$PROJECT_ROOT:$GRID_BACKEND_PATH:$PYTHONPATH"

# Load environment variables
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

echo "Starting Monster Workshop server..."
echo "API: http://$HOST:$PORT"
echo "WebSocket: ws://$HOST:$PORT/ws"
echo "Game Module: $GAME_MODULE"
echo "Database: $DATABASE_URL"

# Run the server using uvicorn from grid_backend
# We run grid_backend.main:app, but PYTHONPATH ensures it finds the module
exec uvicorn grid_backend.main:app --reload --host $HOST --port $PORT --reload-dir "$PROJECT_ROOT" --reload-dir "$GRID_BACKEND_PATH/grid_backend"
