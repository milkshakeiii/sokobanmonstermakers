#!/bin/bash

# Monster Workshop - Development Environment Setup Script
# This script sets up and runs the development environment for Monster Workshop

set -e

echo "================================================"
echo "  Monster Workshop - Development Environment"
echo "================================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Check Python version
echo -e "\n${BLUE}Checking Python version...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python 3 is not installed. Please install Python 3.11+${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
REQUIRED_VERSION="3.10"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo -e "${RED}Python 3.10 or higher is required. Found: $PYTHON_VERSION${NC}"
    exit 1
fi
echo -e "${GREEN}Python $PYTHON_VERSION detected${NC}"

# Create virtual environment if it doesn't exist
VENV_DIR="$PROJECT_ROOT/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo -e "\n${BLUE}Creating virtual environment...${NC}"
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}Virtual environment created${NC}"
fi

# Activate virtual environment
echo -e "\n${BLUE}Activating virtual environment...${NC}"
source "$VENV_DIR/bin/activate"

# Install/upgrade pip
echo -e "\n${BLUE}Upgrading pip...${NC}"
pip install --upgrade pip

# Install backend dependencies
echo -e "\n${BLUE}Installing backend dependencies...${NC}"
pip install fastapi uvicorn[standard] websockets sqlalchemy aiosqlite pydantic passlib[bcrypt]

# Install frontend dependencies (pyunicodegame requires pygame)
echo -e "\n${BLUE}Installing frontend dependencies...${NC}"
pip install pygame

# Check for pyunicodegame (custom library - may need manual installation)
if ! python3 -c "import pyunicodegame" &> /dev/null 2>&1; then
    echo -e "${YELLOW}pyunicodegame not found. Attempting to install from source...${NC}"
    if [ -d "$PROJECT_ROOT/deps/pyunicodegame" ]; then
        pip install -e "$PROJECT_ROOT/deps/pyunicodegame"
    else
        echo -e "${YELLOW}pyunicodegame will need to be installed manually from github.com/pyunicodegame${NC}"
    fi
fi

# Check for gridtickmultiplayer
if ! python3 -c "import gridtickmultiplayer" &> /dev/null 2>&1; then
    echo -e "${YELLOW}gridtickmultiplayer not found. Attempting to install from source...${NC}"
    if [ -d "$PROJECT_ROOT/deps/gridtickmultiplayer" ]; then
        pip install -e "$PROJECT_ROOT/deps/gridtickmultiplayer"
    else
        echo -e "${YELLOW}gridtickmultiplayer will need to be installed manually from github.com/gridtickmultiplayer${NC}"
    fi
fi

# Create necessary directories
echo -e "\n${BLUE}Creating project directories...${NC}"
mkdir -p "$PROJECT_ROOT/backend"
mkdir -p "$PROJECT_ROOT/frontend"
mkdir -p "$PROJECT_ROOT/data"
mkdir -p "$PROJECT_ROOT/data/zones"
mkdir -p "$PROJECT_ROOT/data/tech_tree"
mkdir -p "$PROJECT_ROOT/deps"
mkdir -p "$PROJECT_ROOT/tests"

# Initialize database if it doesn't exist
echo -e "\n${BLUE}Setting up database...${NC}"
if [ ! -f "$PROJECT_ROOT/data/monster_workshop.db" ]; then
    echo -e "${GREEN}Database will be created on first run${NC}"
else
    echo -e "${GREEN}Database already exists${NC}"
fi

# Print status
echo ""
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  Environment Setup Complete!${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${BLUE}To start the development servers:${NC}"
echo ""
echo "  Backend (FastAPI + WebSocket):"
echo "    cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 8000"
echo ""
echo "  Frontend (pyunicodegame client):"
echo "    cd frontend && python3 main.py"
echo ""
echo -e "${BLUE}Access points:${NC}"
echo "  - API Server: http://localhost:8000"
echo "  - API Docs:   http://localhost:8000/docs"
echo "  - WebSocket:  ws://localhost:8000/ws"
echo ""
echo -e "${BLUE}Development commands:${NC}"
echo "  - Run tests:  pytest tests/"
echo "  - Lint code:  pylint backend/ frontend/"
echo ""
echo -e "${YELLOW}Note: Make sure to activate the virtual environment:${NC}"
echo "  source venv/bin/activate"
echo ""

# Optional: Start servers if requested
if [ "$1" == "--start" ]; then
    echo -e "${BLUE}Starting backend server...${NC}"
    cd "$PROJECT_ROOT/backend"
    uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
    BACKEND_PID=$!
    echo "Backend started with PID: $BACKEND_PID"

    echo -e "\n${GREEN}Server is running. Press Ctrl+C to stop.${NC}"
    wait $BACKEND_PID
fi
