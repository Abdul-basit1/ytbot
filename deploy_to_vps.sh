#!/bin/bash
set -e

cd ~/Desktop/uppercut

# Load .env
export $(grep -v '^#' .env | grep -v '^$' | xargs)

# Install sshpass if not installed
if ! command -v sshpass &> /dev/null; then
    echo "Installing sshpass..."
    brew install hudochenkov/sshpass/sshpass
fi

VPS_IP="95.217.13.249"
VPS_USER="root"
VPS_PASS="$VPS_ROOT_PASSWORD"

echo "======================================"
echo "  Deploying UpperCut to VPS"
echo "======================================"

# Upload project (exclude large/local-only dirs)
echo ""
echo "Uploading project to VPS..."
sshpass -p "$VPS_PASS" rsync -avz --progress \
    --exclude 'venv/' \
    --exclude 'output/videos/' \
    --exclude 'output/audio/' \
    --exclude 'output/footage/' \
    --exclude 'output/animation/' \
    --exclude 'output/thumbnails/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.git/' \
    --exclude 'database/master.db' \
    ./ \
    $VPS_USER@$VPS_IP:/root/uppercut/

echo "Files uploaded"

# Run VPS setup remotely
echo ""
echo "Setting up VPS environment..."
sshpass -p "$VPS_PASS" ssh -o StrictHostKeyChecking=no \
    $VPS_USER@$VPS_IP << 'ENDSSH'
set -e

echo "Updating system packages..."
apt update -qq && apt upgrade -y -qq

# Install Python 3.11
if ! command -v python3.11 &> /dev/null; then
    echo "Installing Python 3.11..."
    apt install -y software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa
    apt update -qq
    apt install -y python3.11 python3.11-venv python3.11-dev
else
    echo "Python 3.11 already installed"
fi

# Install ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    apt install -y ffmpeg
else
    echo "ffmpeg already installed"
fi

# Install Node.js + PM2
if ! command -v pm2 &> /dev/null; then
    echo "Installing Node.js + PM2..."
    if ! command -v node &> /dev/null; then
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
        apt install -y nodejs
    fi
    npm install -g pm2
else
    echo "PM2 already installed"
fi

# Set up project
cd /root/uppercut

# Create output directories
mkdir -p output/{videos,thumbnails,audio,footage,animation,logs}
mkdir -p assets/{fonts,music/kids,templates}
mkdir -p database

# Create venv
echo "Creating virtual environment..."
python3.11 -m venv venv
source venv/bin/activate

# Install packages
echo "Installing Python packages..."
python3 -m pip install --upgrade pip --quiet
python3 -m pip install -r requirements.txt --quiet

# Initialize database
echo "Initializing database..."
python3 main.py --init-db

# Configure firewall
echo "Configuring firewall..."
ufw allow 22/tcp
ufw allow 8080/tcp
ufw --force enable
echo "Firewall configured"

echo ""
echo "VPS setup complete!"
ENDSSH

echo ""
echo "======================================"
echo "  VPS deployment complete!"
echo "======================================"
