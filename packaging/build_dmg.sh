#!/usr/bin/env bash
# Buduje samodzielną aplikację macOS (.app) oraz obraz instalacyjny (.dmg) dla Photo Organizer AI.
# Użycie: ./packaging/build_dmg.sh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

APP_NAME="Photo Organizer AI"
DMG_NAME="Photo-Organizer-AI-macOS-$(uname -m).dmg"
DIST_DIR="$PROJECT_DIR/dist"
BUILD_DIR="$PROJECT_DIR/build"
STAGING_DIR="$BUILD_DIR/dmg_staging"
UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}"

echo "==> 1/4 Generuję ikonę aplikacji (.icns)..."
ICON_PNG="$BUILD_DIR/icon_1024.png"
ICONSET_DIR="$BUILD_DIR/AppIcon.iconset"
ICON_ICNS="$BUILD_DIR/AppIcon.icns"
mkdir -p "$BUILD_DIR" "$ICONSET_DIR"

"$UV_BIN" run python - <<'PY'
from pathlib import Path
from PIL import Image, ImageDraw

out = Path("build/icon_1024.png")
img = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
# Zaokrąglone tło w stylu macOS
draw.rounded_rectangle((64, 64, 960, 960), radius=210, fill=(23, 26, 35, 255), outline=(79, 140, 255, 255), width=20)
# Stylizowana ramka zdjęcia + akcent AI
draw.rounded_rectangle((190, 240, 834, 760), radius=64, fill=(31, 36, 49, 255), outline=(147, 197, 253, 255), width=16)
draw.ellipse((280, 320, 410, 450), fill=(79, 140, 255, 255))
draw.polygon([(240, 710), (470, 460), (630, 620), (720, 520), (800, 710)], fill=(34, 197, 94, 230))
img.save(out)
PY

for sz in 16 32 64 128 256 512; do
  sips -z "$sz" "$sz" "$ICON_PNG" --out "$ICONSET_DIR/icon_${sz}x${sz}.png" >/dev/null
  dbl=$((sz * 2))
  sips -z "$dbl" "$dbl" "$ICON_PNG" --out "$ICONSET_DIR/icon_${sz}x${sz}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET_DIR" -o "$ICON_ICNS"

echo "==> 2/4 Buduję paczkę $APP_NAME.app przez PyInstaller..."
rm -rf "$DIST_DIR" "$STAGING_DIR"

"$UV_BIN" run --with pyinstaller pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --onedir \
  --name "$APP_NAME" \
  --icon "$ICON_ICNS" \
  --osx-bundle-identifier "pl.photoorganizer.ai" \
  --add-data "$PROJECT_DIR/static:static" \
  --hidden-import "uvicorn.logging" \
  --hidden-import "uvicorn.loops" \
  --hidden-import "uvicorn.loops.auto" \
  --hidden-import "uvicorn.protocols" \
  --hidden-import "uvicorn.protocols.http" \
  --hidden-import "uvicorn.protocols.http.auto" \
  --hidden-import "uvicorn.protocols.websockets" \
  --hidden-import "uvicorn.protocols.websockets.auto" \
  --hidden-import "uvicorn.lifespan" \
  --hidden-import "uvicorn.lifespan.on" \
  --hidden-import "app" \
  --paths "$PROJECT_DIR" \
  "$PROJECT_DIR/packaging/launcher.py"

echo "==> 3/4 Podpisuję lokalnie (ad-hoc codesign)..."
codesign --force --deep --sign - "$DIST_DIR/$APP_NAME.app" || true

echo "==> 4/4 Tworzę instalator DMG: $DIST_DIR/$DMG_NAME..."
mkdir -p "$STAGING_DIR"
cp -R "$DIST_DIR/$APP_NAME.app" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"

hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DIST_DIR/$DMG_NAME"

echo ""
echo "GOTOWE! Instalator DMG zapisano tutaj:"
echo "  $DIST_DIR/$DMG_NAME"
