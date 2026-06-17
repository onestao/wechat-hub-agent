#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${1:-docker.io/xiaoguiwucan/linux-wechat-agent}"
VERSION="${2:-$(tr -d '[:space:]' < "${ROOT_DIR}/VERSION")}"

if [[ -z "${VERSION}" ]]; then
  echo "[!] VERSION is empty."
  exit 1
fi

echo "[+] Building ${IMAGE}:${VERSION}"
docker build -t "${IMAGE}:${VERSION}" -t "${IMAGE}:latest" "${ROOT_DIR}"

echo "[+] Pushing ${IMAGE}:${VERSION}"
docker push "${IMAGE}:${VERSION}"

echo "[+] Pushing ${IMAGE}:latest"
docker push "${IMAGE}:latest"

echo "[+] Published:"
echo "    ${IMAGE}:${VERSION}"
echo "    ${IMAGE}:latest"
