#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "[!] Missing .env. Run: cp .env.example .env"
  exit 1
fi

account_name="$(grep -E '^WECHAT_ACCOUNT_DIR_NAME=' "${ENV_FILE}" | tail -n1 | cut -d= -f2- || true)"
if [[ -z "${account_name}" || "${account_name}" == "PLEASE_SET_WECHAT_ACCOUNT_DIR" ]]; then
  echo "[!] WECHAT_ACCOUNT_DIR_NAME is not set."
  echo "    Run: ./scripts/detect-wechat-account.sh"
  exit 1
fi

mkdir -p "${ROOT_DIR}/runtime/wechat-decrypt/keys" "${ROOT_DIR}/runtime/wechat-decrypt/decrypted"
cat > "${ROOT_DIR}/runtime/wechat-decrypt/config.json" <<JSON
{
  "db_dir": "/config/xwechat_files/${account_name}/db_storage",
  "keys_file": "/runtime/wechat-decrypt/keys/all_keys.json",
  "decrypted_dir": "/runtime/wechat-decrypt/decrypted",
  "decoded_image_dir": "/runtime/wechat-decrypt/decoded_images"
}
JSON

echo "[+] Wrote runtime/wechat-decrypt/config.json for ${account_name}"
echo "[+] Scanning WeChat process memory inside wechat-selkies..."

docker compose exec -T -u root wechat-selkies sh -lc '
  set -e
  cd /opt/wechat-decrypt
  export WECHAT_DECRYPT_APP_DIR=/runtime/wechat-decrypt
  export WECHAT_DECRYPT_NONINTERACTIVE=1
  python3 find_all_keys_linux.py
'

if [[ -s "${ROOT_DIR}/runtime/wechat-decrypt/keys/all_keys.json" ]]; then
  echo "[+] Keys saved to runtime/wechat-decrypt/keys/all_keys.json"
else
  echo "[!] Key extraction did not produce all_keys.json."
  echo "    Keep WeChat open on port 3000, open a few recent chats, then retry."
  exit 1
fi
