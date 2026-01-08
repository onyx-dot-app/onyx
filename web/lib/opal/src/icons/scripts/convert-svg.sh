#!/bin/bash

# Convert an SVG file to a TypeScript React component
# Usage: ./convert-svg.sh <filename.svg>

if [ -z "$1" ]; then
  echo "Usage: ./convert-svg.sh <filename.svg>" >&2
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

# Run the conversion with relative path to template
bunx @svgr/cli "$SVG_FILE" --typescript --svgo-config '{"plugins":[{"name":"removeAttrs","params":{"attrs":["stroke","stroke-opacity","width","height"]}}]}' --template "scripts/icon-template.js" > "${BASE_NAME}.tsx"

if [ $? -eq 0 ]; then
  # Verify the output file was created and has content
  if [ ! -s "${BASE_NAME}.tsx" ]; then
    echo "Error: Output file was not created or is empty" >&2
    exit 1
  fi

  # Post-process the file to add width, height, and stroke attributes
  # Using perl for cross-platform compatibility (works on macOS, Linux, Windows with WSL)
  # Note: perl -i returns 0 even on some failures, so we validate the output

  perl -i -pe 's/<svg/<svg width={size} height={size}/g' "${BASE_NAME}.tsx"
  if [ $? -ne 0 ]; then
    echo "Error: Failed to add width/height attributes" >&2
    exit 1
  fi

  perl -i -pe 's/\{\.\.\.props\}/stroke="currentColor" {...props}/g' "${BASE_NAME}.tsx"
  if [ $? -ne 0 ]; then
    echo "Error: Failed to add stroke attribute" >&2
    exit 1
  fi

  # Verify the file still exists and has content after post-processing
  if [ ! -s "${BASE_NAME}.tsx" ]; then
    echo "Error: Output file corrupted during post-processing" >&2
    exit 1
  fi

  # Verify required attributes are present in the output
  if ! grep -q 'width={size}' "${BASE_NAME}.tsx" || ! grep -q 'stroke="currentColor"' "${BASE_NAME}.tsx"; then
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
