#!/bin/bash
# UpperCut — VPS Setup Script for Ubuntu 24.04
# Usage: chmod +x setup.sh && sudo ./setup.sh

set -e

echo "========================================="
echo "  UpperCut — VPS Setup (Ubuntu 24.04)"
echo "========================================="

# System update
echo "[1/7] Updating system packages..."
apt update && apt upgrade -y

# Install Python 3.11 and ffmpeg
echo "[2/7] Installing Python 3.11, ffmpeg, and essentials..."
apt install -y python3.11 python3.11-venv python3-pip ffmpeg curl git

# Create project directory (if copying manually)
echo "[3/7] Setting up project directory..."
PROJ_DIR="/opt/uppercut"
if [ ! -d "$PROJ_DIR" ]; then
    mkdir -p "$PROJ_DIR"
    echo "Created $PROJ_DIR — copy your project files here."
fi

# Create virtual environment
echo "[4/7] Creating Python virtual environment..."
cd "$PROJ_DIR"
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Initialize database
echo "[5/7] Initializing database..."
python main.py --init-db

# Install PM2 for process management
echo "[6/7] Installing PM2..."
if ! command -v pm2 &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt install -y nodejs
    npm install -g pm2
fi

# Setup PM2 to run the pipeline + dashboard
echo "[7/7] Configuring PM2 processes..."
PYTHON="$PROJ_DIR/venv/bin/python3"

# Stop existing processes if any
pm2 delete uppercut 2>/dev/null || true
pm2 delete uppercut-dashboard 2>/dev/null || true

# Start pipeline (scheduler mode — runs every 6 hours)
pm2 start main.py --name uppercut --interpreter "$PYTHON"

# Start dashboard (web UI on port 8080)
pm2 start main.py --name uppercut-dashboard --interpreter "$PYTHON" -- --dashboard

# Auto-restart on reboot
pm2 startup
pm2 save

# Open firewall for dashboard
if command -v ufw &> /dev/null; then
    ufw allow 8080/tcp
    echo "Firewall: port 8080 opened for dashboard"
fi

echo ""
echo "========================================="
echo "  Setup complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "  1. Copy your .env and client_secrets.json to $PROJ_DIR"
echo "  2. Run: cd $PROJ_DIR && source venv/bin/activate"
echo "  3. Run: python main.py --test  (test single pipeline run)"
echo ""
echo "Running processes:"
echo "  Pipeline:  pm2 status uppercut"
echo "  Dashboard: http://$(curl -s ifconfig.me):8080"
echo "  Logs:      pm2 logs uppercut"
echo ""
