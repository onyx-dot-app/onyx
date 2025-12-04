# Compilation of SVGs into TypeScript React Components

## Overview

Integrating `@svgr/webpack` into the TypeScript compiler was not working via the recommended route (Next.js webpack configuration).
The automatic SVG-to-React component conversion was causing compilation issues and import resolution problems.
Therefore, we manually convert each SVG into a TSX file using SVGR CLI with a custom template.

## Files in This Directory

### `scripts/icon-template.js`

A custom SVGR template that generates icon components with the following features:
- Imports `IconProps` from `@/icons/index.ts` for consistent typing
- Supports the `size` prop for controlling icon dimensions
- Includes `width` and `height` attributes bound to the `size` prop
- Maintains all standard SVG props (className, color, title, etc.)

This ensures all generated icons have a consistent API and type definitions.

### `scripts/convert-svg.sh`

A convenience script that automates the SVG-to-TSX conversion process. It:
- Validates the input file
- Runs SVGR with the correct configuration and template
- Automatically deletes the source SVG file after successful conversion
- Provides error handling and user feedback

**Usage:**
```sh
./scripts/convert-svg.sh <filename.svg>
```

## Adding New SVGs

**Recommended Method:**

Use the conversion script for the easiest experience:

```sh
./scripts/convert-svg.sh my-icon.svg
```

**Manual Method:**

If you prefer to run the command directly:

```sh
bunx @svgr/cli ${SVG_FILE_NAME}.svg --typescript --svgo-config '{"plugins":[{"name":"removeAttrs","params":{"attrs":["stroke","stroke-opacity","width","height"]}}]}' --template scripts/icon-template.js > ${SVG_FILE_NAME}.tsx
```

This command:
- Converts SVG files to TypeScript React components (`--typescript`)
- Removes `stroke`, `strokeOpacity`, `width`, and `height` attributes from SVG elements (`--svgo-config` with `removeAttrs` plugin)
- Uses the custom template (`icon-template.js`) to generate components with `IconProps` and `size` prop support

After running the manual command, remember to delete the original SVG file.
