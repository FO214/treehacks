#!/bin/bash
# Set visionOS app icon from a source image (resizes to 1024x1024 if needed).
# Usage: ./set-app-icon.sh /path/to/icon.png

set -e
ICON_SRC="${1:?Usage: $0 /path/to/icon.png}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ASSETS="$SCRIPT_DIR/treehacks26/Assets.xcassets/AppIcon.solidimagestack"

if [[ ! -f "$ICON_SRC" ]]; then
  echo "Error: File not found: $ICON_SRC"
  exit 1
fi

# Resize to 1024x1024 (sips is built-in on macOS)
ICON_1024=$(mktemp -t appicon).png
sips -z 1024 1024 "$ICON_SRC" --out "$ICON_1024"

# Copy to all three layers
for layer in Front Middle Back; do
  LAYER_DIR="$ASSETS/${layer}.solidimagestacklayer/Content.imageset"
  cp "$ICON_1024" "$LAYER_DIR/icon.png"
  # Update Contents.json to reference icon.png
  cat > "$LAYER_DIR/Contents.json" << 'EOF'
{"images":[{"idiom":"vision","scale":"2x","filename":"icon.png"}],"info":{"author":"xcode","version":1}}
EOF
done

rm -f "$ICON_1024"
echo "App icon set. Clean build (Shift+Cmd+K) and rebuild."
