# Opal

A Typescript component library for Onyx.

## Usage

```tsx
import { Button } from '@onyx/opal';

function MyComponent() {
  return (
    <Button onClick={() => console.log('Clicked!')}>
      Click me
    </Button>
  );
}
```

## Build

Opal is built in such a way that it *reuses* the `/web/node_modules` directory.
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
│   ├── components/    # React components
│   └── index.ts       # Main export file
├── package.json
├── tsconfig.json
└── README.md
```
