# SVG-to-TSX Conversion Scripts

## Overview

Integrating `@svgr/webpack` into the TypeScript compiler was not working via the recommended route (Next.js webpack configuration).
The automatic SVG-to-React component conversion was causing compilation issues and import resolution problems.
Therefore, we manually convert each SVG into a TSX file using SVGR CLI with a custom template.

All scripts in this directory should be run from the **opal package root** (`web/lib/opal/`).

## Directory Layout

```
web/lib/opal/
├── scripts/                          # SVG conversion tooling (this directory)
│   ├── convert-icon.sh               # Converts SVGs into colour-overridable icon components
│   ├── convert-illustration.sh       # Converts SVGs into fixed-colour illustration components
│   └── icon-template.js              # Shared SVGR template used by both scripts
├── src/
│   ├── icons/                        # Small, single-colour icons (stroke = currentColor)
│   └── illustrations/                # Larger, multi-colour illustrations (colours preserved)
└── package.json
```

## Icons vs Illustrations

| | Icons | Illustrations |
|---|---|---|
| **Import path** | `@opal/icons` | `@opal/illustrations` |
| **Location** | `src/icons/` | `src/illustrations/` |
| **Colour** | Overridable via `currentColor` | Fixed — original SVG colours preserved |
| **Script** | `convert-icon.sh` | `convert-illustration.sh` |

## Files in This Directory

### `icon-template.js`

A custom SVGR template that generates components with the following features:
- Imports `IconProps` from `@opal/types` for consistent typing
- Supports the `size` prop for controlling icon dimensions
- Includes `width` and `height` attributes bound to the `size` prop
- Maintains all standard SVG props (className, color, title, etc.)

This template is shared by both conversion scripts.

### `convert-icon.sh`

Converts an SVG into a **colour-overridable** icon component. It:
- Validates the input file
- Runs SVGR with SVGO configured to strip `stroke`, `stroke-opacity`, `width`, and `height` attributes
- Post-processes the output to add `width={size}`, `height={size}`, and `stroke="currentColor"`
- Automatically deletes the source SVG file after successful conversion
- Provides error handling and user feedback

**Usage:**
```sh
# From web/lib/opal/
./scripts/convert-icon.sh src/icons/my-icon.svg
```

### `convert-illustration.sh`

Converts an SVG into a **fixed-colour** illustration component. It:
- Validates the input file
- Runs SVGR with SVGO configured to strip only `width` and `height` attributes (all colours are preserved)
- Post-processes the output to add `width={size}` and `height={size}`
- Does **not** add `stroke="currentColor"` — illustrations keep their original stroke and fill colours
- Automatically deletes the source SVG file after successful conversion
- Provides error handling and user feedback

**Usage:**
```sh
# From web/lib/opal/
./scripts/convert-illustration.sh src/illustrations/my-illustration.svg
```

## Adding New SVGs

### Icons

```sh
# From web/lib/opal/
./scripts/convert-icon.sh src/icons/my-icon.svg
```

Then add the export to `src/icons/index.ts`:
```ts
export { default as SvgMyIcon } from "@opal/icons/my-icon";
```

### Illustrations

```sh
# From web/lib/opal/
./scripts/convert-illustration.sh src/illustrations/my-illustration.svg
```

Then add the export to `src/illustrations/index.ts`:
```ts
export { default as SvgMyIllustration } from "@opal/illustrations/my-illustration";
```

## Manual Conversion

If you prefer to run the SVGR command directly:

**For icons** (strips colours):
```sh
bunx @svgr/cli <file>.svg --typescript --svgo-config '{"plugins":[{"name":"removeAttrs","params":{"attrs":["stroke","stroke-opacity","width","height"]}}]}' --template scripts/icon-template.js > <file>.tsx
```

**For illustrations** (preserves colours):
```sh
bunx @svgr/cli <file>.svg --typescript --svgo-config '{"plugins":[{"name":"removeAttrs","params":{"attrs":["width","height"]}}]}' --template scripts/icon-template.js > <file>.tsx
```

After running either manual command, remember to delete the original SVG file.
