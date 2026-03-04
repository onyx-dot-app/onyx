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
│   ├── convert-svg.sh                # Converts SVGs into React components
│   └── icon-template.js              # Shared SVGR template (used for both icons and illustrations)
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
| **Script flag** | (none) | `--illustration` |

## Files in This Directory

### `icon-template.js`

A custom SVGR template that generates components with the following features:
- Imports `IconProps` from `@opal/types` for consistent typing
- Supports the `size` prop for controlling icon dimensions
- Includes `width` and `height` attributes bound to the `size` prop
- Maintains all standard SVG props (className, color, title, etc.)

### `convert-svg.sh`

Converts an SVG into a React component. Behaviour depends on the mode:

**Icon mode** (default):
- Strips `stroke`, `stroke-opacity`, `width`, and `height` attributes
- Adds `width={size}`, `height={size}`, and `stroke="currentColor"`
- Result is colour-overridable via CSS `color` property

**Illustration mode** (`--illustration`):
- Strips only `width` and `height` attributes (all colours preserved)
- Adds `width={size}` and `height={size}`
- Does **not** add `stroke="currentColor"` — illustrations keep their original colours

Both modes automatically delete the source SVG file after successful conversion.

## Adding New SVGs

### Icons

```sh
# From web/lib/opal/
./scripts/convert-svg.sh src/icons/my-icon.svg
```

Then add the export to `src/icons/index.ts`:
```ts
export { default as SvgMyIcon } from "@opal/icons/my-icon";
```

### Illustrations

```sh
# From web/lib/opal/
./scripts/convert-svg.sh --illustration src/illustrations/my-illustration.svg
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
