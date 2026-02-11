# Opal Components

High-level UI components built on the [`@opal/core`](../core/) primitives. Every component in this directory delegates state styling (hover, active, disabled, transient) to `Interactive.Base` via CSS data-attributes and the `--interactive-foreground` custom property — no duplicated Tailwind class maps.

## Package export

Components are exposed from the `@onyx/opal` package via:

```ts
import { Button } from "@opal/components";
```

The barrel file at `index.ts` re-exports each component and its prop types. Each component imports its own `styles.css` internally.

## Components

| Component | Description | Docs |
|-----------|-------------|------|
| [Button](./buttons/Button/) | Label and/or icon-only button | [README](./buttons/Button/README.md) |
| [OpenButton](./buttons/OpenButton/) | Trigger button with rotating chevron | [README](./buttons/OpenButton/README.md) |

## Adding new components

1. Create a directory under `components/` (e.g. `components/inputs/TextInput/`)
2. Add a `styles.css` for layout-only CSS (colors come from Interactive.Base or other core primitives)
3. Add a `components.tsx` with the component and its exported props type
4. Import `styles.css` at the top of your `components.tsx` (each component owns its own styles)
5. In `components/index.ts`, re-export the component:
   ```ts
   export { TextInput, type TextInputProps } from "@opal/components/inputs/TextInput/components";
   ```
6. Add a `README.md` inside the component directory with architecture, props, and usage examples
