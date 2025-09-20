# Compilation of SVGs into TypeScript React Components

## Manual Conversion Process

Integrating `@svgr/webpack` into the TypeScript compiler was not working via the recommended route (Next.js webpack configuration). The automatic SVG-to-React component conversion was causing compilation issues and import resolution problems.

Therefore, we need to manually convert each SVG into a TSX file using the following command:

```sh
bunx @svgr/cli ${SVG_FILE} --typescript --no-dimensions --svgo-config '{"plugins":[{"name":"removeAttrs","params":{"attrs":"stroke"}}]}' > ${SVG_FILE_NAME}.tsx
```

This command:
- Converts SVG files to TypeScript React components (`--typescript`)
- Removes width and height from the root SVG tag (`--no-dimensions`)
- Removes all `stroke` attributes from SVG elements (`--svgo-config` with `removeAttrs` plugin)

## Adding New SVGs

When adding a new SVG icon:

1. Place the SVG file in this directory (`web/src/icons/`)
2. Run the conversion command:
   ```sh
   bunx @svgr/cli ${SVG_FILE} --typescript --no-dimensions --svgo-config '{"plugins":[{"name":"removeAttrs","params":{"attrs":"stroke"}}]}' > ${SVG_FILE_NAME}.tsx
   ```
3. Delete the original SVG file (keep only the generated `.tsx` file)
