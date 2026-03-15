#!/bin/bash
set -e

echo "======================================"
echo "  UpperCut — Full Setup & Deploy"
echo "======================================"

cd ~/Desktop/uppercut

# Step 1: Local setup
echo ""
echo "========== STEP 1: Local Mac Setup =========="
chmod +x local_setup.sh
./local_setup.sh

# Step 2: Test pipeline locally
echo ""
echo "========== STEP 2: Testing Pipeline =========="
chmod +x test_pipeline.sh
./test_pipeline.sh

# Step 3: Deploy to VPS
echo ""
echo "========== STEP 3: Deploying to VPS =========="
chmod +x deploy_to_vps.sh
./deploy_to_vps.sh

# Step 4: Start PM2 on VPS
echo ""
echo "========== STEP 4: Starting PM2 =========="
chmod +x start_pm2.sh
./start_pm2.sh

echo ""
echo "======================================"
echo "  Everything is live!"
echo ""
echo "  Dashboard: http://95.217.13.249:8080"
echo "  Pipeline:  Running 24/7 on VPS"
echo "  Alerts:    abasit.tlg@gmail.com"
echo "======================================"
