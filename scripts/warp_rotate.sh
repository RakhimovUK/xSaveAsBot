#!/usr/bin/env bash
# Get a fresh free WARP identity (new IP) when YouTube starts answering "confirm you're not a bot".
set -euo pipefail
cd ~/warp
mkdir -p old && mv -f wgcf-account.toml wgcf-profile.conf old/ 2>/dev/null || true
./wgcf register --accept-tos
./wgcf generate
chmod 600 wgcf-account.toml wgcf-profile.conf
sudo systemctl restart wireproxy
sleep 4
curl -s -m 15 --socks5-hostname 172.18.0.1:1080 https://www.cloudflare.com/cdn-cgi/trace | grep -E '^ip=|warp'
