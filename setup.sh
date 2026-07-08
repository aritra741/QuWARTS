#!/bin/bash
# WDIRS Setup Script

set -e

echo "=================================="
echo "WDIRS Setup"
echo "=================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check Python version
echo -e "\n${YELLOW}[1/7] Checking Python version...${NC}"
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3, 9) else 1)'; then
    echo -e "${RED}Error: Python 3.9+ required${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python version OK${NC}"

# Check PostgreSQL
echo -e "\n${YELLOW}[2/7] Checking PostgreSQL...${NC}"
if command -v psql &> /dev/null; then
    psql_version=$(psql --version | awk '{print $3}')
    echo "PostgreSQL version: $psql_version"
    echo -e "${GREEN}✓ PostgreSQL found${NC}"
else
    echo -e "${RED}Warning: PostgreSQL not found${NC}"
    echo "Please install PostgreSQL 14+ before continuing"
    echo "  macOS: brew install postgresql@14"
    echo "  Ubuntu: sudo apt install postgresql postgresql-contrib"
fi

# Check Ollama
echo -e "\n${YELLOW}[3/7] Checking Ollama...${NC}"
if command -v ollama &> /dev/null; then
    echo "Ollama found"
    echo -e "${GREEN}✓ Ollama installed${NC}"
    
    # Check if model is available
    if ollama list | grep -q "qwen2.5:7b-instruct"; then
        echo -e "${GREEN}✓ qwen2.5:7b-instruct model found${NC}"
    else
        echo -e "${YELLOW}Pulling qwen2.5:7b-instruct model...${NC}"
        ollama pull qwen2.5:7b-instruct
        echo -e "${GREEN}✓ Model downloaded${NC}"
    fi
else
    echo -e "${RED}Warning: Ollama not found${NC}"
    echo "Please install Ollama from https://ollama.ai/"
    echo "Then run: ollama pull qwen2.5:7b-instruct"
fi

# Create virtual environment
echo -e "\n${YELLOW}[4/7] Creating virtual environment...${NC}"
if [ -d "venv" ]; then
    echo "Virtual environment already exists"
else
    python3 -m venv venv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi

# Activate virtual environment
echo -e "\n${YELLOW}[5/7] Activating virtual environment...${NC}"
source venv/bin/activate
echo -e "${GREEN}✓ Virtual environment activated${NC}"

# Install dependencies
echo -e "\n${YELLOW}[6/7] Installing Python dependencies...${NC}"
pip install --upgrade pip
pip install -r requirements.txt
echo -e "${GREEN}✓ Dependencies installed${NC}"

# Download spaCy model
echo -e "\n${YELLOW}[7/7] Downloading spaCy model...${NC}"
python -m spacy download en_core_web_sm
echo -e "${GREEN}✓ spaCy model downloaded${NC}"

# Create directories
echo -e "\n${YELLOW}Creating directories...${NC}"
mkdir -p .cache
mkdir -p .databases
mkdir -p .indexes
mkdir -p .sieves
echo -e "${GREEN}✓ Directories created${NC}"

# Setup complete
echo -e "\n${GREEN}=================================="
echo "Setup Complete!"
echo "==================================${NC}"

echo -e "\nNext steps:"
echo "1. Start PostgreSQL:"
echo "   macOS: brew services start postgresql@14"
echo "   Ubuntu: sudo systemctl start postgresql"
echo ""
echo "2. Create database:"
echo "   createdb wdirs"
echo ""
echo "3. Start Ollama server:"
echo "   ollama serve"
echo ""
echo "4. Activate virtual environment:"
echo "   source venv/bin/activate"
echo ""
echo "5. Run preprocessing:"
echo "   python wdirs_runner.py Med --preprocess --workload ../../Query/Med/"
echo ""
echo "6. Execute queries:"
echo "   python wdirs_runner.py Med --query \"SELECT * FROM disease WHERE status = 'Approved'\""
echo ""
echo -e "${GREEN}Happy extracting!${NC}"
