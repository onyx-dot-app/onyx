# Test Mocks Directory

This directory contains mock implementations used in Jest tests.

## Mocking Strategy

**Use `transformIgnorePatterns` for ES Module packages** instead of mocking them.

### Two Approaches:

| Approach                     | Use When                                                      | Examples                                                             |
| ---------------------------- | ------------------------------------------------------------- | -------------------------------------------------------------------- |
| **transformIgnorePatterns**  | All ESM packages                                              | `@radix-ui`, `@headlessui`, `react-markdown`, `remark-*`, `rehype-*` |
| **moduleNameMapper (mocks)** | Non-executable assets/files, or components with complex setup | CSS files, images, UserProvider                                      |

### Why Use transformIgnorePatterns:

Modern npm packages ship as ES Modules (ESM) by default. Jest runs in a Node environment that expects CommonJS. The `transformIgnorePatterns` configuration tells Jest which packages in `node_modules` to transform from ESM to CommonJS.

**Benefits:**

- Tests run against real package code, not mocks
- No need to maintain mock implementations
- Catches real bugs in how we use dependencies

**Trade-off:**

- Tests run slower (transformation takes time, especially for markdown packages)

## When to Add to transformIgnorePatterns

**Add packages to the `transformIgnorePatterns` array in `jest.config.js` when:**

### ✅ Add to transformIgnorePatterns:

1. **SyntaxError: Unexpected token 'export'**

   ```
   Error: SyntaxError: Unexpected token 'export'
   at node_modules/package-name/index.js:1
   ```

   → Package uses ES Modules and needs transformation

2. **Package ships as ESM**

   - Check `package.json`: `"type": "module"` or `"exports"` field
   - Files use `export`/`import` syntax
   - Common in modern packages (markdown, UI libraries)

3. **Works fine when transformed**
   - Package has no complex dependencies
   - No browser-specific APIs or native modules
   - Just needs ESM → CommonJS conversion

### How to Add:

1. Open `web/jest.config.js`
2. Find the `transformIgnorePatterns` array
3. Add package name to the appropriate category:

```javascript
transformIgnorePatterns: [
  "/node_modules/(?!(" +
    [
      // ... existing packages ...

      // Add your package here (grouped by category)
      "your-package-name",
      "another-package",

      // Use regex patterns for related packages
      "package-.*",  // All packages starting with "package-"
    ].join("|") +
    ")/)",
],
```

**Example:** Adding `remark-directive`:

```javascript
// Markdown & Syntax Highlighting
"react-markdown",
"remark-gfm",
"remark-math",
"remark-directive",  // ← Add here
"remark-parse",
```

## When to Add Mocks to This Directory

**Only mock things that CANNOT be executed in tests.**

### ✅ DO Mock:

1. **CSS/Style Files**

   - Already handled by `cssMock.js`
   - Cannot be executed in Node environment
   - Examples: `.css`, `.scss`, `.sass`, `.less`

2. **Static Assets**

   - Already handled by `fileMock.js`
   - Binary files that can't be imported
   - Examples: images, fonts, videos

3. **Components with Complex External Dependencies**
   - Components that require browser APIs not available in jsdom
   - Components with difficult-to-setup external dependencies
   - Example: `UserProvider.tsx` (already mocked)

### ❌ DON'T Mock:

1. **ES Module Packages**

   - ALWAYS use `transformIgnorePatterns` instead
   - Even complex packages like `react-markdown` with deep ESM dependency trees
   - Add the package (and any dependencies that fail) to `transformIgnorePatterns`

2. **Your Own Code**

   - Test real implementations
   - Mocking defeats the purpose of testing

3. **Packages That Work in Jest**
   - Most packages work fine in Jest
   - No need to add them anywhere

## Current Mocks

This directory contains **necessary mocks**:

```
mocks/
├── components/
│   └── UserProvider.tsx        # Component with complex dependencies
├── cssMock.js                  # All CSS/style files
└── README.md                   # This file
```

**Note:** `fileMock.js` is in `tests/setup/` (not in `mocks/`) for historical reasons.

## How to Add a New Mock

### Step 1: Determine if You Really Need a Mock

**Try `transformIgnorePatterns` first!** Only create a mock if:

- Asset/file cannot be executed (CSS, images)
- Component has complex external dependencies
- Package absolutely cannot work when transformed

### Step 2: Create the Mock File

**For Components:**

```typescript
// mocks/components/ComponentName.tsx
import React from 'react';

export default function ComponentName({ children }: { children?: React.ReactNode }) {
  return <div data-testid="mock-component-name">{children}</div>;
}
```

**For CSS/Assets:** (Already handled - no need to create)

### Step 3: Register in jest.config.js

Add to `moduleNameMapper`:

```javascript
moduleNameMapper: {
  // Before path aliases!
  "^@/components/ComponentName$":
    "<rootDir>/tests/setup/mocks/components/ComponentName.tsx",

  // Path aliases come last
  "^@/(.*)$": "<rootDir>/src/$1",
}
```

### Step 4: Verify Tests Pass

```bash
bun run test
```

## Decision Tree

```
Need to use a package in tests?
         ↓
Does it cause "SyntaxError: Unexpected token 'export'"?
         ↓
      YES → Try adding to transformIgnorePatterns first ✅
         ↓
      Does it still fail after transformation?
         ↓
      YES → Create mock (complex ESM structure) ⚠️
         |
      NO → Transformation worked! ✅
         |
Is it CSS/static asset?
         ↓
      YES → Already mocked (cssMock.js/fileMock.js) ✅
         |
      NO → Can the package be executed in Node/jsdom?
         ↓
      YES → Use it directly (no mock needed) ✅
         |
      NO → Is it a component with complex dependencies?
         ↓
      YES → Create mock in mocks/components/ ⚠️
         |
      NO → You probably don't need a mock! ✅
```

## Examples

### ✅ Example 1: ESM Package

**Problem:** `@tiptap/react` causes `SyntaxError: Unexpected token 'export'`

**Solution:** Add to `transformIgnorePatterns` in `jest.config.js`

```javascript
transformIgnorePatterns: [
  "/node_modules/(?!(" +
    [
      // ...
      "@tiptap/react",  // ← Add here
      "@tiptap/core",
      // ...
    ].join("|") +
    ")/)",
],
```

**If you get more errors:** Keep adding the failing packages until tests pass. The package may have ESM dependencies that also need transformation.

### ✅ Example 2: Complex ESM Package with Dependencies

**Problem:** `react-markdown` causes SyntaxError, then after fixing it, `devlop` fails, then `hast-util-to-jsx-runtime` fails...

**Solution:** Keep adding packages to transformIgnorePatterns:

```javascript
[
  "react-markdown",
  "remark-.*", // All remark packages
  "rehype-.*", // All rehype packages
  "hast-.*", // All hast packages
  "devlop",
  "hastscript",
  // ... and so on
];
```

**Pro tip:** Use wildcard patterns like `"remark-.*"` to match all packages with that prefix.

### ✅ Example 3: Static Asset (Already Handled)

**Problem:** Importing CSS causes error

**Solution:** Already handled! `cssMock.js` catches all CSS imports.

### ✅ Example 4: Component Mock (Rare Case)

**Problem:** `AuthProvider` requires complex auth setup

**Solution:**

```typescript
// mocks/components/AuthProvider.tsx
import React from 'react';

export default function AuthProvider({ children }: { children?: React.ReactNode }) {
  return <div data-testid="mock-auth-provider">{children}</div>;
}
```

```javascript
// jest.config.js
"^@/components/auth/AuthProvider$":
  "<rootDir>/tests/setup/mocks/components/AuthProvider.tsx",
```

## Troubleshooting

### "SyntaxError: Unexpected token 'export'"

**Fix:** Add the package to `transformIgnorePatterns` in `jest.config.js`

**If it happens again:** The package likely has ESM dependencies. Keep adding failing packages to the list until tests pass.

### "Cannot find module 'package-name'"

**Check:**

1. Is package installed? `bun pm ls package-name`
2. Is path in `jest.config.js` correct?
3. Did you add to `transformIgnorePatterns` if it's ESM?

### Tests slow after adding to transformIgnorePatterns

**This is expected.** Transformation takes time, especially for packages with deep dependency trees like `react-markdown`.

**Example:** The markdown tests take ~23 seconds vs ~1 second without markdown packages.

**Why this is worth it:**

- Tests run against real code, catching real bugs
- No mock maintenance burden
- More confidence in test results

**If tests are too slow:**

1. Use `jest --maxWorkers=50%` to parallelize (already configured)
2. Run specific test files during development: `bun run test -- --testPathPattern=MyComponent`
3. Let CI run the full suite

### Package still fails after adding to transformIgnorePatterns

**Rare, but possible issues:**

1. Package requires browser APIs → Mock it or use jsdom
2. Package has native dependencies → May need different approach
3. TypeScript type errors → Check tsconfig `allowJs: true` in jest.config.js transform options

## Testing Philosophy

**The Goal:** Write tests that are reliable and test YOUR code with REAL dependencies.

- ✅ **Transform ESM packages** - Always use `transformIgnorePatterns` for npm packages
- ✅ **Mock only non-executable things** - CSS, images, videos (things Node.js can't execute)
- ✅ **Test real code** - More confidence, catches real bugs, no mock maintenance
- ❌ **Don't mock packages** - Even if they have complex dependency trees
- ⚠️ **Accept slower tests** - Transformation takes time, but correctness > speed

## Additional Resources

- [Jest transformIgnorePatterns Documentation](https://jestjs.io/docs/configuration#transformignorepatterns-arraystring)
- [ES Modules in Jest](https://jestjs.io/docs/ecmascript-modules)
- [Testing Library Best Practices](https://testing-library.com/docs/guiding-principles/)
