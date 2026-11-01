#!/usr/bin/env bash
# Pull the latest code and (re)start all services. Run on the server from the repo root.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo ".env is missing; copy it from your laptop first" >&2
    exit 1
fi
chmod 600 .env

git pull --ff-only
docker compose up -d --build
docker image prune -f >/dev/null
docker compose ps
