#!/bin/bash
# Build script for HIFI Detector desktop app
#
# Steps:
#   1. Build Svelte frontend
#   2. Build Python server with PyInstaller
#   3. Copy to Tauri resources
#   4. Build Tauri desktop app
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

# Step 1: Frontend (Svelte) -> hifi_detector/web/static
echo "[1/4] Building Svelte frontend..."
cd "$PROJECT_ROOT/web"
npm ci
npm run build
echo "   OK: frontend built to hifi_detector/web/static"

# Step 2: PyInstaller
echo ""
echo "[2/4] Building Python server (PyInstaller)..."
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

# Step 3: Copy to Tauri resources
echo ""
echo "[3/4] Copying Python server to Tauri resources..."
rm -rf "$TAURI_RESOURCES"
mkdir -p "$TAURI_RESOURCES"
cp "$BINARY" "$TAURI_RESOURCES/hifi-detect-server"
cp -r "$PYINST_DIST/hifi-detect-server/_internal" "$TAURI_RESOURCES/_internal"
chmod +x "$TAURI_RESOURCES/hifi-detect-server"
echo "   OK: $(du -sh "$TAURI_RESOURCES" | awk '{print $1}')"

# Step 4: Tauri build
echo ""
echo "[4/4] Building Tauri desktop app..."
cd "$SCRIPT_DIR"
npx tauri build 2>&1 | tail -20

echo ""
echo "=== Build complete ==="
echo ""
echo "Output bundles:"
find "$SCRIPT_DIR/src-tauri/target/release/bundle" -name "*.app" -o -name "*.dmg" -o -name "*.msi" 2>/dev/null | while read f; do
    echo "  $(ls -lh "$f" | awk '{print $5, $NF}')"
done
