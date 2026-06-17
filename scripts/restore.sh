#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIVE="${1:-}"

if [[ -z "${ARCHIVE}" || ! -f "${ARCHIVE}" ]]; then
  echo "Usage: ./scripts/restore.sh /path/to/wechat-agent-backup.tar.gz"
  exit 1
fi

SAFETY_DIR="${ROOT_DIR}/backups/pre-restore-$(date +%Y%m%d-%H%M%S)"
mkdir -p "${SAFETY_DIR}"

for item in .env runtime config; do
  if [[ -e "${ROOT_DIR}/${item}" ]]; then
    mv "${ROOT_DIR}/${item}" "${SAFETY_DIR}/${item}"
  fi
done

tar -C "${ROOT_DIR}" -xzf "${ARCHIVE}"

echo "[+] Restored ${ARCHIVE}"
echo "[i] Previous local data, if any, was moved to ${SAFETY_DIR}"
