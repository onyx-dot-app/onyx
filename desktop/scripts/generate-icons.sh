#!/bin/bash
# Icon generation script for Onyx Desktop
# Requires: ImageMagick (brew install imagemagick)

set -e

ICON_DIR="src-tauri/icons"
SOURCE_SVG="$ICON_DIR/icon.svg"

# Check if ImageMagick is installed
if ! command -v magick &> /dev/null; then
    echo "ImageMagick not found. Install with: brew install imagemagick"
    exit 1
fi

echo "Generating icons from $SOURCE_SVG..."

# Generate PNG icons
magick -background none "$SOURCE_SVG" -resize 32x32 "$ICON_DIR/32x32.png"
magick -background none "$SOURCE_SVG" -resize 128x128 "$ICON_DIR/128x128.png"
magick -background none "$SOURCE_SVG" -resize 256x256 "$ICON_DIR/128x128@2x.png"

# Generate macOS .icns
# Create iconset directory
ICONSET="$ICON_DIR/icon.iconset"
mkdir -p "$ICONSET"

magick -background none "$SOURCE_SVG" -resize 16x16 "$ICONSET/icon_16x16.png"
magick -background none "$SOURCE_SVG" -resize 32x32 "$ICONSET/icon_16x16@2x.png"
magick -background none "$SOURCE_SVG" -resize 32x32 "$ICONSET/icon_32x32.png"
magick -background none "$SOURCE_SVG" -resize 64x64 "$ICONSET/icon_32x32@2x.png"
magick -background none "$SOURCE_SVG" -resize 128x128 "$ICONSET/icon_128x128.png"
magick -background none "$SOURCE_SVG" -resize 256x256 "$ICONSET/icon_128x128@2x.png"
magick -background none "$SOURCE_SVG" -resize 256x256 "$ICONSET/icon_256x256.png"
magick -background none "$SOURCE_SVG" -resize 512x512 "$ICONSET/icon_256x256@2x.png"
magick -background none "$SOURCE_SVG" -resize 512x512 "$ICONSET/icon_512x512.png"
magick -background none "$SOURCE_SVG" -resize 1024x1024 "$ICONSET/icon_512x512@2x.png"

# Convert to icns (macOS only)
if command -v iconutil &> /dev/null; then
    iconutil -c icns "$ICONSET" -o "$ICON_DIR/icon.icns"
    rm -rf "$ICONSET"
    echo "Generated icon.icns"
else
    echo "iconutil not found (not on macOS?), skipping .icns generation"
fi

# Generate Windows .ico
magick "$ICON_DIR/32x32.png" "$ICON_DIR/128x128.png" "$ICON_DIR/icon.ico"

echo "Done! Icons generated in $ICON_DIR/"
ls -la "$ICON_DIR/"
