# Opal

A Typescript component library for Onyx.

## Usage

```tsx
import { Button } from "@opal/components";

function MyComponent() {
  return <Button onClick={() => console.log("Clicked!")}>Click me</Button>;
}
```

## Build

Opal is built in such a way that it _reuses_ the `/web/node_modules` directory.
Therefore, builds don't incur duplicate space-costs (i.e., what would have happened if Opal had its own `node_modules`).
If you want to add dependencies to Opal, define that dependency inside of `/web/lib/opal/package.json` under `peerDependencies`.
Then, go to `/web` and run the install:

```sh
npm i

# Or, if you prefer `bun`
bun i
```

Those dependencies will then install inside of `/web/node_modules` and be available to Opal.

## Structure

```
/web/lib/opal/
├── src/
│   ├── core/           # Low-level primitives (Interactive, Hoverable)
│   ├── components/     # High-level React components (Button, SelectButton, OpenButton, Tag)
│   ├── layouts/        # Layout primitives (Content, ContentAction, IllustrationContent)
│   └── index.ts        # Main export file
├── package.json
├── tsconfig.json
└── README.md
```

## Conventions

- **Directory names** are kebab-case (e.g. `select-button/`, `open-button/`, `content-action/`)
- **Each component directory** contains `components.tsx`, `styles.css` (if needed), and `README.md`
- **Imports** use `@opal/` path aliases (e.g. `@opal/components`, `@opal/core`)
