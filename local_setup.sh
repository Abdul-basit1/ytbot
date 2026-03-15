#!/bin/bash
set -e

echo "======================================"
echo "  UpperCut — Local Mac Setup"
echo "======================================"

cd ~/Desktop/uppercut

# Install ffmpeg if missing
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    brew install ffmpeg
else
    echo "ffmpeg already installed: $(ffmpeg -version 2>&1 | head -1)"
fi

# Create venv if missing
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
else
    echo "Virtual environment already exists"
fi

# Activate venv
source venv/bin/activate

# Upgrade pip
python3 -m pip install --upgrade pip --quiet

# Install requirements
echo "Installing Python packages..."
python3 -m pip install -r requirements.txt --quiet

# Create output directories
mkdir -p output/{videos,thumbnails,audio,footage,animation,logs}
mkdir -p assets/{fonts,music/kids,templates}
mkdir -p database

# Initialize database
echo "Initializing database..."
python3 main.py --init-db

echo "======================================"
echo "  Local setup complete!"
echo "======================================"
