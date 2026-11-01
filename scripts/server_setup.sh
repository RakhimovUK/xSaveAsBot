#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 server (Oracle Cloud Always Free, ARM).
# Run as the default "ubuntu" user:  bash server_setup.sh
set -euo pipefail

REPO_URL="https://github.com/RakhimovUK/xSaveAsBot.git"
APP_DIR="$HOME/xSaveAsBot"

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get -y upgrade
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y git unattended-upgrades fail2ban

# Security updates install automatically
sudo dpkg-reconfigure -f noninteractive unattended-upgrades

# Docker Engine + compose plugin (official convenience script)
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"
sudo systemctl enable --now docker

# Small swap file as a safety net for image builds
if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

if [ ! -d "$APP_DIR" ]; then
    git clone "$REPO_URL" "$APP_DIR"
fi

echo
echo "Done. Next: copy .env to $APP_DIR/.env, then run scripts/deploy.sh"
echo "(log out and back in once so the docker group applies)"
