#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "${SCRIPT_DIR}")"
RUNTIME_DIR="${SCRIPT_DIR}/wine-runtime"

if [ -f "${RUNTIME_DIR}/.patched" ]; then
    echo "[build_runtime] runtime/wine-runtime is already set up and patched."
    exit 0
fi

PACKAGE_NAME="wine-11.20-1-x86_64.pkg.tar.zst"
PACKAGE_URL="https://archive.archlinux.org/packages/w/wine/${PACKAGE_NAME}"
EXPECTED_SHA256="6dfd8bcc9b370de2942732a36d730e1b18a141218975315da816c8326c237644"

mkdir -p "${SCRIPT_DIR}"
ARCHIVE="${SCRIPT_DIR}/${PACKAGE_NAME}"

if [ ! -f "${ARCHIVE}" ] || ! echo "${EXPECTED_SHA256}  ${ARCHIVE}" | sha256sum -c --quiet 2>/dev/null; then
    echo "[build_runtime] Downloading isolated Wine 11.20 runtime..."
    curl -fL --retry 5 -o "${ARCHIVE}.tmp" "${PACKAGE_URL}"
    echo "${EXPECTED_SHA256}  ${ARCHIVE}.tmp" | sha256sum -c --quiet || { rm -f "${ARCHIVE}.tmp"; echo "Checksum failed!" >&2; exit 1; }
    mv "${ARCHIVE}.tmp" "${ARCHIVE}"
fi

echo "[build_runtime] Extracting Wine runtime..."
rm -rf "${RUNTIME_DIR}" "${SCRIPT_DIR}/extract_tmp"
mkdir -p "${SCRIPT_DIR}/extract_tmp"
tar --zstd -xf "${ARCHIVE}" -C "${SCRIPT_DIR}/extract_tmp" usr
mv "${SCRIPT_DIR}/extract_tmp/usr" "${RUNTIME_DIR}"
rm -rf "${SCRIPT_DIR}/extract_tmp"

echo "[build_runtime] Applying binary patches (transparency, memory, drag)..."
python3 -I "${ROOT_DIR}/patches/patch_runtime.py" "${RUNTIME_DIR}"
ln -sfn wineserver "${RUNTIME_DIR}/bin/tappo-wineserver"
touch "${RUNTIME_DIR}/.patched"
echo "[build_runtime] Wine runtime successfully built and patched!"
