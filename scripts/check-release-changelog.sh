#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-$(tr -d '[:space:]' < "${ROOT_DIR}/VERSION")}"
CHANGELOG="${ROOT_DIR}/CHANGELOG.md"

if [[ -z "${VERSION}" ]]; then
  echo "[!] VERSION is empty."
  exit 1
fi

if [[ ! -f "${CHANGELOG}" ]]; then
  echo "[!] CHANGELOG.md does not exist."
  exit 1
fi

if ! grep -Eq "^## v${VERSION}([[:space:]]|-)" "${CHANGELOG}"; then
  echo "[!] Missing changelog section for v${VERSION}."
  echo "    Add a section like: ## v${VERSION} - YYYY-MM-DD"
  exit 1
fi

echo "[+] Changelog section exists for v${VERSION}."
