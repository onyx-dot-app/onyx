# Opal Components

High-level UI components built on the [`@opal/core`](../core/) primitives. Every component in this directory delegates state styling (hover, active, disabled) to `Interactive.Stateless` or `Interactive.Stateful` via CSS data-attributes and the `--interactive-foreground` / `--interactive-foreground-icon` custom properties — no duplicated Tailwind class maps.

## Package export

Components are exposed via:

```ts
import { Button, SelectButton, OpenButton, Tag } from "@opal/components";
```

The barrel file at `index.ts` re-exports each component and its prop types. Each component imports its own `styles.css` internally.

## Components

| Component | Description | Docs |
|-----------|-------------|------|
| [Button](./buttons/button/) | Label and/or icon-only stateless button | [README](./buttons/button/README.md) |
| [SelectButton](./buttons/select-button/) | Stateful toggle button with optional foldable content | [README](./buttons/select-button/README.md) |
| [OpenButton](./buttons/open-button/) | Trigger button with rotating chevron for popovers | [README](./buttons/open-button/README.md) |
| [Tag](./tag/) | Small colored label for status/category metadata | [README](./tag/README.md) |

## Adding new components

1. Create a directory under `components/` in kebab-case (e.g. `components/inputs/text-input/`)
2. Add a `styles.css` for layout-only CSS (colors come from Interactive primitives)
3. Add a `components.tsx` with the component and its exported props type
4. Import `styles.css` at the top of your `components.tsx`
5. Add a `README.md` inside the component directory with architecture, props, and usage examples
6. In `components/index.ts`, re-export the component:
   ```ts
   export { TextInput, type TextInputProps } from "@opal/components/inputs/text-input/components";
   ```
