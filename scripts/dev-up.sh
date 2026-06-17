#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[+] Created .env from .env.example"
fi

docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build "$@"
