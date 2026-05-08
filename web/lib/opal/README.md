# Opal

Onyx's TypeScript component library and design system.

## Install

```sh
npm install @onyx-ai/opal
```

Peer dependencies (install whichever the lib actually exercises in your usage):

```sh
npm install react react-dom next \
  @radix-ui/react-popover @radix-ui/react-separator \
  @radix-ui/react-slot @radix-ui/react-tooltip \
  @dnd-kit/core @dnd-kit/sortable @dnd-kit/modifiers @dnd-kit/utilities \
  @tanstack/react-table formik \
  react-markdown remark-gfm rehype-sanitize
```

## Setup

### 1. Import the design tokens once

In your app's root entry (e.g. Next.js `app/layout.tsx`):

```tsx
import "@onyx-ai/opal/styles.css";
```

The CSS file defines the custom properties (`--text-01`, `--background-neutral-00`, etc.) that
the Tailwind preset references.

### 2. Wire up the Tailwind preset

In your `tailwind.config.js`:

```js
module.exports = {
  presets: [require("@onyx-ai/opal/tailwind-preset")],
  content: [
    "./src/**/*.{ts,tsx}",
    "./node_modules/@onyx-ai/opal/dist/**/*.{js,mjs}",
  ],
};
```

The `content` glob ensures Tailwind picks up the classes used inside Opal components.

You also need to define the underlying CSS variables (`--text-01`, etc.) in your own
`colors.css` or import a copy from Onyx. The preset references them but does not define them —
they live with the consumer so the consumer controls the palette.

## Usage

```tsx
import { Button, Text } from "@onyx-ai/opal/components";
import { Content } from "@onyx-ai/opal/layouts";
import SvgPlus from "@onyx-ai/opal/icons/plus";

function MyComponent() {
  return (
    <Content
      icon={SvgPlus}
      title="Hello"
      description="World"
      sizePreset="main-ui"
      variant="section"
    />
  );
}
```

## Subpath imports

| Subpath                         | Contents                                             |
| ------------------------------- | ---------------------------------------------------- |
| `@onyx-ai/opal/components`      | Buttons, Text, Tag, Tooltip, Popover, Table, etc.    |
| `@onyx-ai/opal/layouts`         | Content, ContentAction, IllustrationContent, Section |
| `@onyx-ai/opal/core`            | Interactive primitives, Hoverable, Disabled          |
| `@onyx-ai/opal/icons`           | SVG icon components                                  |
| `@onyx-ai/opal/illustrations`   | Larger SVG illustrations                             |
| `@onyx-ai/opal/types`           | Shared types (`RichStr`, `IconProps`, etc.)          |
| `@onyx-ai/opal/utils`           | `cn`, `markdown` helpers                             |
| `@onyx-ai/opal/styles.css`      | Bundled component CSS                                |
| `@onyx-ai/opal/tailwind-preset` | Tailwind preset with tokens                          |

## Local development (inside the Onyx repo)

The package is consumed by `web/` as a workspace via `web/package.json`'s `"@onyx-ai/opal":
"./lib/opal"`. During Onyx development, `web/` resolves Opal source through the `@opal/*`
TypeScript path alias (defined in `web/tsconfig.json`), so changes are picked up live without
running `npm run build`.

To produce the published artifact:

```sh
cd web/lib/opal
npm run build       # tsup -> dist/, then bundle-css.mjs -> dist/styles.css
```

Adding a runtime dependency: declare it under `peerDependencies` (so consumers control the
version) and ensure the matching version is also declared in the root `web/package.json`
`dependencies` block so Onyx's web app keeps building.

## Conventions

- Component dirs: `web/lib/opal/src/components/<kebab-name>/` containing `components.tsx`,
  `README.md`, `styles.css` (when needed), and `<PascalName>.stories.tsx` (when applicable).
- Imports inside the lib use the `@opal/` path alias; never `@/`.
- Types/interfaces declared at the top of `components.tsx` without `export`; everything is
  re-exported from a single `export { Foo, type FooProps };` block at the bottom.
- See `web/AGENTS.md` for broader frontend standards.
