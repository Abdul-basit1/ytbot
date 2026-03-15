#!/usr/bin/env python3
"""
UpperCut — VPS Deployment Script (paramiko)
Uploads project, installs dependencies, inits DB, configures firewall, starts PM2.
"""

import os
import sys
import stat
import time
from pathlib import Path

import paramiko
from dotenv import dotenv_values

# ── Config ─────────────────────────────────────────────────────────────────

PROJECT_DIR = Path(__file__).resolve().parent
env = dotenv_values(PROJECT_DIR / ".env")

VPS_HOST = env.get("VPS_IP", "95.217.13.249")
VPS_USER = "root"
VPS_PASS = env["VPS_ROOT_PASSWORD"]
REMOTE_DIR = "/root/uppercut"

# Files/dirs to skip when uploading
EXCLUDE = {
    "venv", "__pycache__", ".git", "output", "database",
    ".env.example", "deploy.py",
}
EXCLUDE_EXT = {".pyc", ".pyo", ".db"}


# ── Helpers ────────────────────────────────────────────────────────────────

def ssh_connect():
    """Create and return a connected SSH client."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)
    return client


def run_remote(client, cmd, label=None, ignore_errors=False):
    """Run a command on VPS. Raises on non-zero exit unless ignore_errors."""
    if label:
        print(f"\n--- {label} ---")
    stdin, stdout, stderr = client.exec_command(
        f"export DEBIAN_FRONTEND=noninteractive; {cmd}",
        timeout=600,
    )
    out = stdout.read().decode()
    err = stderr.read().decode()
    exit_code = stdout.channel.recv_exit_status()
    if out.strip():
        for line in out.strip().split("\n")[-10:]:  # last 10 lines
            print(f"  {line}")
    if exit_code != 0 and not ignore_errors:
        if err.strip():
            print(f"  STDERR: {err.strip()[:500]}")
        raise RuntimeError(f"Command failed (exit {exit_code}): {cmd[:80]}...")
    return out


def upload_project(client):
    """Upload project files to VPS by creating a tar, piping over SSH."""
    import subprocess
    import tempfile

    # Build exclude args for tar
    tar_excludes = ["--exclude", "._*"]  # macOS resource forks
    for exc in EXCLUDE:
        tar_excludes.extend(["--exclude", f"./{exc}"])
    for ext in EXCLUDE_EXT:
        tar_excludes.extend(["--exclude", f"*{ext}"])

    print("  Creating tarball...")
    tar_path = Path(tempfile.gettempdir()) / "uppercut_deploy.tar.gz"
    tar_env = {**os.environ, "COPYFILE_DISABLE": "1"}  # suppress macOS ._* files
    subprocess.run(
        ["tar", "czf", str(tar_path)] + tar_excludes + ["-C", str(PROJECT_DIR), "."],
        check=True,
        env=tar_env,
    )
    tar_size = tar_path.stat().st_size
    print(f"  Tarball: {tar_size / 1024:.0f} KB")

    # Upload tar via SSH stdin pipe
    print("  Uploading via SSH pipe...")
    run_remote(client, f"mkdir -p {REMOTE_DIR}")

    transport = client.get_transport()
    chan = transport.open_session()
    chan.exec_command(f"cat > /tmp/uppercut_deploy.tar.gz")
    with open(tar_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            chan.sendall(chunk)
    chan.shutdown_write()
    chan.recv_exit_status()
    chan.close()

    # Extract on VPS
    run_remote(client,
        f"cd {REMOTE_DIR} && tar xzf /tmp/uppercut_deploy.tar.gz && "
        "rm /tmp/uppercut_deploy.tar.gz && "
        "echo 'Files extracted'",
    )

    tar_path.unlink(missing_ok=True)
    print("  Upload complete!")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 50)
    print("  UpperCut — VPS Deployment")
    print("=" * 50)

    # Step 1: Connect
    print(f"\nConnecting to {VPS_HOST}...")
    client = ssh_connect()
    print("Connected!")

    # Step 2: Upload files
    print("\nUploading project files...")
    upload_project(client)

    # Step 3: Create directories
    run_remote(client,
        f"mkdir -p {REMOTE_DIR}/output/{{videos,thumbnails,audio,footage,animation,logs}} "
        f"{REMOTE_DIR}/assets/{{fonts,music/kids,templates}} "
        f"{REMOTE_DIR}/database",
        "Creating directories"
    )

    # Step 4: Install system packages
    run_remote(client,
        "apt update -qq 2>/dev/null; "
        "apt install -y -qq python3-venv python3-dev ffmpeg 2>/dev/null; "
        "echo 'System packages installed'",
        "Installing system packages (python3-venv, ffmpeg)",
        ignore_errors=True,
    )

    # Step 5: Install Node.js + PM2
    run_remote(client,
        "if ! command -v pm2 > /dev/null 2>&1; then "
        "  if ! command -v node > /dev/null 2>&1; then "
        "    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - > /dev/null 2>&1; "
        "    apt install -y -qq nodejs > /dev/null 2>&1; "
        "  fi; "
        "  npm install -g pm2 > /dev/null 2>&1; echo 'PM2 installed'; "
        "else echo 'PM2 already installed'; fi",
        "Installing Node.js + PM2"
    )

    # Step 6: Create venv + install Python packages
    run_remote(client,
        f"cd {REMOTE_DIR} && "
        "python3 -m venv venv && "
        "source venv/bin/activate && "
        "python3 -m pip install --upgrade pip --quiet && "
        "python3 -m pip install -r requirements.txt --quiet && "
        "echo 'Python packages installed'",
        "Setting up Python environment"
    )

    # Step 7: Init database
    run_remote(client,
        f"cd {REMOTE_DIR} && source venv/bin/activate && python3 main.py --init-db",
        "Initializing database"
    )

    # Step 8: Firewall
    run_remote(client,
        "ufw allow 22/tcp > /dev/null 2>&1; "
        "ufw allow 8080/tcp > /dev/null 2>&1; "
        "ufw --force enable > /dev/null 2>&1; "
        "echo 'Firewall configured (SSH + 8080)'",
        "Configuring firewall",
        ignore_errors=True,
    )

    # Step 9: Create PM2 ecosystem and start
    ecosystem_js = """
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
""".strip()

    # Write ecosystem file
    run_remote(client,
        f"cat > {REMOTE_DIR}/ecosystem.config.js << 'ECOSYSTEMEOF'\n{ecosystem_js}\nECOSYSTEMEOF",
        "Writing PM2 ecosystem config"
    )

    # Stop existing, start fresh
    run_remote(client,
        f"cd {REMOTE_DIR} && "
        "pm2 delete all 2>/dev/null; "
        "pm2 start ecosystem.config.js && "
        "pm2 save && "
        "pm2 startup systemd -u root --hp /root 2>/dev/null; "
        "echo 'PM2 started'",
        "Starting PM2 processes",
        ignore_errors=True,
    )

    # Step 10: Verify
    print("\n--- Verification ---")
    run_remote(client, "pm2 status")

    # Wait a moment for dashboard to boot
    time.sleep(3)

    run_remote(client,
        f"curl -s -o /dev/null -w '%{{http_code}}' -u admin:{env.get('DASHBOARD_PASSWORD', 'changeme')} http://127.0.0.1:8080/ "
        "|| echo 'Dashboard not responding yet (may need a few seconds)'",
        "Testing dashboard"
    )

    client.close()

    print("\n" + "=" * 50)
    print("  DEPLOYMENT COMPLETE!")
    print()
    print(f"  Dashboard: http://{VPS_HOST}:8080")
    print(f"  Username:  admin")
    print(f"  Password:  (from .env DASHBOARD_PASSWORD)")
    print("=" * 50)


if __name__ == "__main__":
    main()
