#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
XWECHAT_DIR="${ROOT_DIR}/config/xwechat_files"

if [[ ! -f "${ENV_FILE}" ]]; then
  cp "${ROOT_DIR}/.env.example" "${ENV_FILE}"
  echo "[+] Created .env from .env.example"
fi

if [[ ! -d "${XWECHAT_DIR}" ]]; then
  echo "[!] ${XWECHAT_DIR} does not exist."
  echo "    Start wechat-selkies first, open port 3000, and scan-login to WeChat."
  exit 1
fi

candidate_file="$(mktemp)"
trap 'rm -f "${candidate_file}"' EXIT

while IFS= read -r db_dir; do
  mtime="$(stat -f "%m" "${db_dir}" 2>/dev/null || stat -c "%Y" "${db_dir}" 2>/dev/null || echo 0)"
  printf "%s\t%s\n" "${mtime}" "${db_dir}" >> "${candidate_file}"
done < <(find "${XWECHAT_DIR}" -mindepth 2 -maxdepth 2 -type d -name db_storage -print)

if [[ ! -s "${candidate_file}" ]]; then
  echo "[!] No db_storage directory found under ${XWECHAT_DIR}."
  echo "    Make sure WeChat is logged in and has loaded recent chats."
  exit 1
fi

chosen="$(sort -rn "${candidate_file}" | head -n 1 | cut -f2-)"
account_name="$(basename "$(dirname "${chosen}")")"

tmp_file="$(mktemp)"
if grep -q '^WECHAT_ACCOUNT_DIR_NAME=' "${ENV_FILE}"; then
  sed "s|^WECHAT_ACCOUNT_DIR_NAME=.*|WECHAT_ACCOUNT_DIR_NAME=${account_name}|" "${ENV_FILE}" > "${tmp_file}"
else
  cat "${ENV_FILE}" > "${tmp_file}"
  printf '\nWECHAT_ACCOUNT_DIR_NAME=%s\n' "${account_name}" >> "${tmp_file}"
fi
mv "${tmp_file}" "${ENV_FILE}"

echo "[+] Selected WeChat account directory: ${account_name}"
echo "[+] Updated ${ENV_FILE}"
other_count="$(sort -rn "${candidate_file}" | tail -n +2 | wc -l | tr -d ' ')"
if [[ "${other_count}" != "0" ]]; then
  echo "[i] Other candidates:"
  sort -rn "${candidate_file}" | tail -n +2 | cut -f2- | sed 's/^/    /'
fi
