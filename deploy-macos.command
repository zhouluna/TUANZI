#!/bin/bash
# LUNA ZHOU, 2026-11-06: build/install a native app without preinstalled Python.
set -euo pipefail
ROOT="$(cd -- "$(dirname "$0")" && pwd)"
cd "$ROOT"
WORK=""
finish() {
    status=$?
    if [ -n "$WORK" ] && [ -d "$WORK" ]; then
        # Only the temporary wheel extraction created by mktemp below.
        case "$WORK" in "$CACHE"/bootstrap.*) rm -rf -- "$WORK" ;; esac
    fi
    if [ "$status" -ne 0 ]; then
        echo ""
        echo "Installation failed. Keep this window's error message and retry."
    fi
    if [ -t 0 ]; then read -r -p "Press Enter to close this window..." _ || true; fi
    exit "$status"
}
if [ "$(uname -s)" != "Darwin" ]; then echo "This installer runs on macOS only."; exit 1; fi
MAJOR="$(sw_vers -productVersion | cut -d. -f1)"
if [ "$MAJOR" -lt 14 ]; then echo "Tuanzi requires macOS 14 or newer (Qt 6.12)."; exit 1; fi
CACHE="$HOME/Library/Caches/TuanziPet"
mkdir -p "$CACHE/tools"
trap finish EXIT
if ! xcode-select -p >/dev/null 2>&1; then
    echo "First deployment needs Apple's Command Line Tools."
    echo "Please finish the official system installer; Tuanzi will continue automatically."
    xcode-select --install || true
    TOOL_DEADLINE=$((SECONDS + 1800))
    until xcode-select -p >/dev/null 2>&1; do
        if [ "$SECONDS" -ge "$TOOL_DEADLINE" ]; then
            echo "Apple tools are not installed yet. Finish installing, then run this script again."
            exit 1
        fi
        sleep 5
    done
fi
if ! xcrun --find lipo >/dev/null 2>&1 || ! xcrun --find install_name_tool >/dev/null 2>&1; then
    echo "Apple's developer tools are incomplete. Finish their system setup, then retry."
    exit 1
fi
# shellcheck source=packaging/uv-macos.env
source "$ROOT/packaging/uv-macos.env"
ARCH="$(uname -m)"
case "$ARCH" in
    arm64) URL="$UV_ARM64_URL"; SHA="$UV_ARM64_SHA256" ;;
    x86_64) URL="$UV_X64_URL"; SHA="$UV_X64_SHA256" ;;
    *) echo "Unsupported Mac architecture: $ARCH"; exit 1 ;;
esac
UV="$CACHE/tools/uv-$UV_VERSION-$ARCH"
if [ ! -x "$UV" ] || [ "$("$UV" --version 2>/dev/null | awk '{print $2}' || true)" != "$UV_VERSION" ]; then
    echo "[1/4] Downloading the verified runtime bootstrap..."
    WORK="$(mktemp -d "$CACHE/bootstrap.XXXXXX")"
    curl --fail --location --retry 3 --connect-timeout 30 "$URL" -o "$WORK/uv.whl"
    ACTUAL="$(shasum -a 256 "$WORK/uv.whl" | awk '{print $1}')"
    if [ "$ACTUAL" != "$SHA" ]; then echo "Bootstrap checksum mismatch; installation stopped."; exit 1; fi
    unzip -q "$WORK/uv.whl" -d "$WORK/extracted"
    cp "$WORK/extracted/$UV_BINARY_PATH" "$UV"
    chmod 755 "$UV"
    mkdir -p "$CACHE/tools/uv-$UV_VERSION-licenses"
    cp "$WORK/extracted/uv-$UV_VERSION.dist-info/licenses/"* "$CACHE/tools/uv-$UV_VERSION-licenses/"
fi
export UV_CACHE_DIR="$CACHE/uv-cache"
export UV_PYTHON_INSTALL_DIR="$CACHE/python"
BUILD_ENV="$CACHE/build-1.0.0-$ARCH"
echo "[2/4] Preparing Python and the build dependencies..."
if [ ! -x "$BUILD_ENV/bin/python" ]; then
    "$UV" --no-config venv --python 3.14 --managed-python "$BUILD_ENV"
fi
"$UV" --no-config pip install --python "$BUILD_ENV/bin/python" --index-url https://pypi.org/simple -r "$ROOT/packaging/requirements-build.txt"
echo "[3/4] Building and verifying Tuanzi.app..."
"$BUILD_ENV/bin/python" "$ROOT/scripts/build_release.py" --install --launch
echo "[4/4] Installed to $HOME/Applications/Tuanzi.app"
echo "You can open Tuanzi from Applications next time, without Python or this installer."
