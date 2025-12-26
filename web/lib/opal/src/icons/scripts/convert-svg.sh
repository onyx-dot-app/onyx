#!/bin/bash

# Convert an SVG file to a TypeScript React component
# Usage: ./convert-svg.sh <filename.svg>

if [ -z "$1" ]; then
  echo "Usage: ./convert-svg.sh <filename.svg>"
  exit 1
fi

SVG_FILE="$1"

# Check if file exists
if [ ! -f "$SVG_FILE" ]; then
  echo "Error: File '$SVG_FILE' not found"
  exit 1
fi

# Check if it's an SVG file
if [[ ! "$SVG_FILE" == *.svg ]]; then
  echo "Error: File must have .svg extension"
  exit 1
fi

# Get the base name without extension
BASE_NAME="${SVG_FILE%.svg}"

# Run the conversion with relative path to template
bunx @svgr/cli "$SVG_FILE" --typescript --svgo-config '{"plugins":[{"name":"removeAttrs","params":{"attrs":["stroke","stroke-opacity","width","height"]}}]}' --template "scripts/icon-template.js" > "${BASE_NAME}.tsx"

if [ $? -eq 0 ]; then
  # Add width and height attributes bound to size prop
  sed -i '' 's/<svg/<svg width={size} height={size}/g' "${BASE_NAME}.tsx"
  # Add stroke="currentColor" before {...props} for proper override behavior
  sed -i '' 's/{\.\.\.props}/stroke="currentColor" {...props}/g' "${BASE_NAME}.tsx"

  echo "Created ${BASE_NAME}.tsx"
  rm "$SVG_FILE"
  echo "Deleted $SVG_FILE"
else
  echo "Error: Conversion failed"
  exit 1
fi
