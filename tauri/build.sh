#!/bin/bash
# Build script for HIFI Detector desktop app
#
# Steps:
#   1. Build Python server with PyInstaller
#   2. Copy to Tauri resources
#   3. Build Tauri desktop app
#
# Usage:
#   ./build.sh          # Full production build
#   ./build.sh --dev    # Dev: just PyInstaller, then npx tauri dev

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
PYINSTALLER_SPEC="$SCRIPT_DIR/hifi-detect.spec"
PYINST_DIST="$SCRIPT_DIR/dist-python"
PYINST_BUILD="$SCRIPT_DIR/build-python"
TAURI_RESOURCES="$SCRIPT_DIR/src-tauri/python"

echo "=== HIFI Detector Desktop Build ==="
echo ""

# Step 1: PyInstaller
echo "[1/3] Building Python server (PyInstaller)..."
cd "$PROJECT_ROOT"
$VENV_PYTHON -m PyInstaller \
    --distpath "$PYINST_DIST" \
    --workpath "$PYINST_BUILD" \
    --noconfirm \
    "$PYINSTALLER_SPEC" 2>&1 | tail -5

BINARY="$PYINST_DIST/hifi-detect-server/hifi-detect-server"
if [ -f "$BINARY" ]; then
    echo "   OK: $(ls -lh "$BINARY" | awk '{print $5}')"
else
    echo "   ERROR: PyInstaller binary not found at $BINARY"
    exit 1
fi

# Step 2: Copy to Tauri resources
echo ""
echo "[2/3] Copying Python server to Tauri resources..."
mkdir -p "$TAURI_RESOURCES"
cp "$BINARY" "$TAURI_RESOURCES/hifi-detect-server"
cp -r "$PYINST_DIST/hifi-detect-server/_internal" "$TAURI_RESOURCES/_internal"
chmod +x "$TAURI_RESOURCES/hifi-detect-server"
echo "   OK: $(du -sh "$TAURI_RESOURCES" | awk '{print $1}')"

# Step 3: Tauri build
echo ""
echo "[3/3] Building Tauri desktop app..."
cd "$SCRIPT_DIR"
npx tauri build 2>&1 | tail -20

echo ""
echo "=== Build complete ==="
echo ""
echo "Output bundles:"
find "$SCRIPT_DIR/src-tauri/target/release/bundle" -name "*.app" -o -name "*.dmg" -o -name "*.msi" 2>/dev/null | while read f; do
    echo "  $(ls -lh "$f" | awk '{print $5, $NF}')"
done
