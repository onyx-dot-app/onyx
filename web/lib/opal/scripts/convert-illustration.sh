#!/bin/bash

# Convert an SVG file to a TypeScript React illustration component.
# Illustrations are NOT colour-overridable: all original stroke and fill colours are preserved.
# Only width and height attributes are stripped (replaced by the size prop).
#
# Usage (from the opal package root — web/lib/opal/):
#   ./scripts/convert-illustration.sh src/illustrations/<filename.svg>

if [ -z "$1" ]; then
  echo "Usage: ./scripts/convert-illustration.sh <filename.svg>" >&2
  exit 1
fi

SVG_FILE="$1"

# Check if file exists
if [ ! -f "$SVG_FILE" ]; then
  echo "Error: File '$SVG_FILE' not found" >&2
  exit 1
fi

# Check if it's an SVG file
if [[ ! "$SVG_FILE" == *.svg ]]; then
  echo "Error: File must have .svg extension" >&2
  exit 1
fi

# Get the base name without extension
BASE_NAME="${SVG_FILE%.svg}"

# Run the conversion — only strips width and height attributes (preserves all colours)
bunx @svgr/cli "$SVG_FILE" --typescript --svgo-config '{"plugins":[{"name":"removeAttrs","params":{"attrs":["width","height"]}}]}' --template "scripts/icon-template.js" > "${BASE_NAME}.tsx"

if [ $? -eq 0 ]; then
  # Verify the output file was created and has content
  if [ ! -s "${BASE_NAME}.tsx" ]; then
    echo "Error: Output file was not created or is empty" >&2
    exit 1
  fi

  # Post-process the file to add width and height attributes bound to the size prop
  # Using perl for cross-platform compatibility (works on macOS, Linux, Windows with WSL)
  # Note: perl -i returns 0 even on some failures, so we validate the output

  perl -i -pe 's/<svg/<svg width={size} height={size}/g' "${BASE_NAME}.tsx"
  if [ $? -ne 0 ]; then
    echo "Error: Failed to add width/height attributes" >&2
    exit 1
  fi

  # Verify the file still exists and has content after post-processing
  if [ ! -s "${BASE_NAME}.tsx" ]; then
    echo "Error: Output file corrupted during post-processing" >&2
    exit 1
  fi

  # Verify required attributes are present in the output
  if ! grep -q 'width={size}' "${BASE_NAME}.tsx"; then
    echo "Error: Post-processing did not add required attributes" >&2
    exit 1
  fi

  echo "Created ${BASE_NAME}.tsx"
  rm "$SVG_FILE"
  echo "Deleted $SVG_FILE"
else
  echo "Error: Conversion failed" >&2
  exit 1
fi
