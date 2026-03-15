#!/bin/bash
set -e

cd ~/Desktop/uppercut

# Load .env
export $(grep -v '^#' .env | grep -v '^$' | xargs)

VPS_IP="95.217.13.249"
VPS_USER="root"
VPS_PASS="$VPS_ROOT_PASSWORD"

echo "======================================"
echo "  Starting PM2 on VPS"
echo "======================================"

sshpass -p "$VPS_PASS" ssh -o StrictHostKeyChecking=no \
    $VPS_USER@$VPS_IP << 'ENDSSH'
set -e

cd /root/uppercut
source venv/bin/activate

# Create output log dir
mkdir -p output/logs

# Create PM2 ecosystem file
cat > ecosystem.config.js << 'EOF'
module.exports = {
  apps: [
    {
      name: "uppercut-pipeline",
      script: "main.py",
      interpreter: "/root/uppercut/venv/bin/python3",
      cwd: "/root/uppercut",
      watch: false,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      env: { PYTHONPATH: "/root/uppercut" },
      error_file: "/root/uppercut/output/logs/pipeline_error.log",
      out_file: "/root/uppercut/output/logs/pipeline_out.log"
    },
    {
      name: "uppercut-dashboard",
      script: "main.py",
      interpreter: "/root/uppercut/venv/bin/python3",
      args: "--dashboard",
      cwd: "/root/uppercut",
      watch: false,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      env: { PYTHONPATH: "/root/uppercut" },
      error_file: "/root/uppercut/output/logs/dashboard_error.log",
      out_file: "/root/uppercut/output/logs/dashboard_out.log"
    }
  ]
}
EOF

# Stop existing PM2 processes if any
pm2 delete all 2>/dev/null || true

# Start PM2
pm2 start ecosystem.config.js

# Save and setup startup
pm2 save
pm2 startup systemd -u root --hp /root 2>/dev/null || true

echo ""
echo "======================================"
echo "  PM2 started successfully!"
echo "======================================"

pm2 status
ENDSSH

echo ""
echo "======================================"
echo "  DEPLOYMENT COMPLETE!"
echo ""
echo "  Dashboard: http://95.217.13.249:8080"
echo "  Username:  admin"
echo "  Password:  (from .env DASHBOARD_PASSWORD)"
echo "======================================"
