#!/bin/bash

# Script to add size prop support to all icon files in the current directory

for file in *.tsx; do
  # Skip index.tsx and the template file
  if [[ "$file" == "index.tsx" ]]; then
    continue
  fi

  # Check if file contains the old pattern
  if grep -q "const Svg.*= (props: SVGProps<SVGSVGElement>) => (" "$file"; then
    echo "Updating $file..."

    # Replace the component signature to accept size prop
    sed -i '' 's/const \(Svg[^=]*\) = (props: SVGProps<SVGSVGElement>) => (/const \1 = ({ size, ...props }: SVGProps<SVGSVGElement> \& { size?: number }) => (/g' "$file"

    # Add width and height attributes to the svg tag
    sed -i '' 's/<svg$/<svg width={size} height={size}/g' "$file"
    sed -i '' 's/<svg /<svg width={size} height={size} /g' "$file"
  fi
done

echo "Done!"
