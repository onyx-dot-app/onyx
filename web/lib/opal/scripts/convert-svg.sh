#!/bin/bash

# Convert an SVG file to a TypeScript React component.
#
# By default, converts to a colour-overridable icon (stroke colours stripped, replaced with currentColor).
# With --illustration, converts to a fixed-colour illustration (all original colours preserved).
#
# Usage (from the opal package root — web/lib/opal/):
#   ./scripts/convert-svg.sh src/icons/<filename.svg>
#   ./scripts/convert-svg.sh --illustration src/illustrations/<filename.svg>

ILLUSTRATION=false

# Parse flags
while [[ "$1" == --* ]]; do
  case "$1" in
    --illustration)
      ILLUSTRATION=true
      shift
      ;;
    *)
      echo "Unknown flag: $1" >&2
      echo "Usage: ./scripts/convert-svg.sh [--illustration] <filename.svg>" >&2
      exit 1
      ;;
  esac
done

if [ -z "$1" ]; then
  echo "Usage: ./scripts/convert-svg.sh [--illustration] <filename.svg>" >&2
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

# Build the SVGO config based on mode
if [ "$ILLUSTRATION" = true ]; then
  # Illustrations: only strip width and height (preserve all colours)
  SVGO_CONFIG='{"plugins":[{"name":"removeAttrs","params":{"attrs":["width","height"]}}]}'
else
  # Icons: strip stroke, stroke-opacity, width, and height
  SVGO_CONFIG='{"plugins":[{"name":"removeAttrs","params":{"attrs":["stroke","stroke-opacity","width","height"]}}]}'
fi

# Resolve the template path relative to this script (not the caller's CWD)
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"

# Run the conversion into a temp file so a failed run doesn't destroy an existing .tsx
TMPFILE="${BASE_NAME}.tsx.tmp"
bunx @svgr/cli "$SVG_FILE" --typescript --svgo-config "$SVGO_CONFIG" --template "${SCRIPT_DIR}/icon-template.js" > "$TMPFILE"

if [ $? -eq 0 ]; then
  mv "$TMPFILE" "${BASE_NAME}.tsx"
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

  # Icons additionally get stroke="currentColor"
  if [ "$ILLUSTRATION" = false ]; then
    perl -i -pe 's/\{\.\.\.props\}/stroke="currentColor" {...props}/g' "${BASE_NAME}.tsx"
    if [ $? -ne 0 ]; then
      echo "Error: Failed to add stroke attribute" >&2
      exit 1
    fi
  fi

  # Verify the file still exists and has content after post-processing
  if [ ! -s "${BASE_NAME}.tsx" ]; then
    echo "Error: Output file corrupted during post-processing" >&2
    exit 1
  fi

  # Verify required attributes are present in the output
  if ! grep -q 'width={size}' "${BASE_NAME}.tsx" || ! grep -q 'height={size}' "${BASE_NAME}.tsx"; then
    echo "Error: Post-processing did not add required attributes" >&2
    exit 1
  fi

  # For icons, also verify stroke="currentColor" was added
  if [ "$ILLUSTRATION" = false ]; then
    if ! grep -q 'stroke="currentColor"' "${BASE_NAME}.tsx"; then
      echo "Error: Post-processing did not add stroke=\"currentColor\"" >&2
      exit 1
    fi
  fi

  echo "Created ${BASE_NAME}.tsx"
  rm "$SVG_FILE"
  echo "Deleted $SVG_FILE"
else
  rm -f "$TMPFILE"
  echo "Error: Conversion failed" >&2
  exit 1
fi
