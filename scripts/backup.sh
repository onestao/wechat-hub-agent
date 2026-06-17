#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${ROOT_DIR}/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${BACKUP_DIR}/wechat-agent-backup-${STAMP}.tar.gz"

mkdir -p "${BACKUP_DIR}"

items=()
[[ -f "${ROOT_DIR}/.env" ]] && items+=(".env")
[[ -d "${ROOT_DIR}/runtime" ]] && items+=("runtime")
[[ -d "${ROOT_DIR}/config" ]] && items+=("config")

if [[ "${#items[@]}" -eq 0 ]]; then
  echo "[!] Nothing to back up. Expected .env, runtime/, or config/."
  exit 1
fi

tar -C "${ROOT_DIR}" -czf "${OUT}" "${items[@]}"
echo "[+] Backup written: ${OUT}"
echo "[i] This archive contains private WeChat/runtime data. Do not upload it to GitHub."
