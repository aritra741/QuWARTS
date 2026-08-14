#!/bin/bash
# QuWARTS setup: virtualenv, Python dependencies, spaCy model, Ollama check.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=================================="
echo "QuWARTS Setup"
echo "=================================="

echo -e "\n${YELLOW}[1/5] Checking Python version...${NC}"
python3 --version
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo -e "${RED}Error: Python 3.9+ is required${NC}"
    exit 1
fi
echo -e "${GREEN}Python version OK${NC}"

echo -e "\n${YELLOW}[2/5] Checking Ollama...${NC}"
if command -v ollama >/dev/null 2>&1; then
    echo -e "${GREEN}Ollama is installed${NC}"
    if ollama list 2>/dev/null | grep -q "qwen2.5:7b-instruct"; then
        echo -e "${GREEN}qwen2.5:7b-instruct is available${NC}"
    else
        echo -e "${YELLOW}Pulling qwen2.5:7b-instruct...${NC}"
        ollama pull qwen2.5:7b-instruct
    fi
else
    echo -e "${YELLOW}Ollama not found. Install from https://ollama.ai/ then run:${NC}"
    echo "  ollama pull qwen2.5:7b-instruct"
fi

echo -e "\n${YELLOW}[3/5] Creating virtual environment...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
echo -e "${GREEN}Virtual environment ready${NC}"

echo -e "\n${YELLOW}[4/5] Installing QuWARTS...${NC}"
pip install --upgrade pip
pip install -e ".[dev]"
echo -e "${GREEN}Package installed${NC}"

echo -e "\n${YELLOW}[5/5] Downloading spaCy model...${NC}"
python -m spacy download en_core_web_sm
echo -e "${GREEN}spaCy model downloaded${NC}"

echo -e "\n${GREEN}=================================="
echo "Setup complete"
echo "==================================${NC}"
echo ""
echo "Next steps:"
echo "  1. source venv/bin/activate"
echo "  2. ollama serve"
echo "  3. python -m quwarts Player --preprocess --workload Query/Player/"
echo "  4. python -m quwarts Player --query \"SELECT name, team FROM player WHERE age > 30\""
echo ""
