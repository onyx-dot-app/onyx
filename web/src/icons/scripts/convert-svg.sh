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

# Run the conversion (template file must be in the same directory as this script)
cd "$(dirname "${BASH_SOURCE[0]}")"
bunx @svgr/cli "$OLDPWD/$SVG_FILE" --typescript --svgo-config '{"plugins":[{"name":"removeAttrs","params":{"attrs":["stroke","stroke-opacity","width","height"]}}]}' --template="./icon-template.js" > "$OLDPWD/${BASE_NAME}.tsx"
cd "$OLDPWD"

if [ $? -eq 0 ]; then
  # Ensure stroke="currentColor" is before {...props} for proper override behavior
  sed -i '' 's/{\.\.\.props}/stroke="currentColor" {...props}/g' "${BASE_NAME}.tsx"
  # Remove duplicate if template already added it
  sed -i '' 's/stroke="currentColor" stroke="currentColor"/stroke="currentColor"/g' "${BASE_NAME}.tsx"

  echo "Created ${BASE_NAME}.tsx"
  rm "$SVG_FILE"
  echo "Deleted $SVG_FILE"
else
  echo "Error: Conversion failed"
  exit 1
fi
