#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${1:-docker.io/xiaoguiwucan/linux-wechat-agent}"
VERSION="${2:-$(tr -d '[:space:]' < "${ROOT_DIR}/VERSION")}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"

if [[ -z "${VERSION}" ]]; then
  echo "[!] VERSION is empty."
  exit 1
fi

echo "[+] Building and pushing ${IMAGE}:${VERSION} for ${PLATFORMS}"
docker buildx build \
  --platform "${PLATFORMS}" \
  -t "${IMAGE}:${VERSION}" \
  -t "${IMAGE}:latest" \
  --push \
  "${ROOT_DIR}"

echo "[+] Published:"
echo "    ${IMAGE}:${VERSION}"
echo "    ${IMAGE}:latest"
