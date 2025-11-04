# Opal

A TSX component library for the Onyx project.

## Overview

Opal is an internal library that provides reusable React/TSX components for the Onyx web application. It's designed to maintain consistency and promote code reuse across the project.

## Structure

```
libs/opal/
├── src/
│   ├── components/    # React components
│   └── index.ts       # Main export file
├── dist/              # Compiled output (generated)
├── package.json
├── tsconfig.json
└── README.md
```

## Development

### Building the library

```bash
cd libs/opal
npm run build
```

### Watch mode for development

```bash
cd libs/opal
npm run dev
```

### Clean build artifacts

```bash
cd libs/opal
npm run clean
```

## Usage in web application

The library is linked as a local dependency in the `web` application:

```tsx
import { Button } from '@onyx/opal';

function MyComponent() {
  return (
    <Button variant="primary" onClick={() => console.log('Clicked!')}>
      Click me
    </Button>
  );
}
```

## Adding new components

1. Create your component in `src/components/YourComponent.tsx`
2. Export it from `src/index.ts`
3. Rebuild the library with `npm run build`
4. The component will be available in the web app

## TypeScript

The library is fully typed with TypeScript. Type definitions are automatically generated during the build process.
