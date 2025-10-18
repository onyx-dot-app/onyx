# Test Mocks

This directory contains Jest mocks for dependencies that are difficult to test with in their original form.

## Why These Mocks Exist

### `@/components/user/UserProvider.tsx`

**Problem:** The real `UserProvider` requires complex setup with props like:
- `authTypeMetadata` (auth configuration)
- `settings` (CombinedSettings object)
- `user` (User object)

**Solution:** This mock provides a simple `useUser()` hook that returns safe default values, allowing components that depend on user context to render in tests without extensive setup.

**Usage:** Automatically applied via `jest.config.js` moduleNameMapper. Components using `useUser()` will get the mock instead of the real provider.

**Mock values:**
```typescript
{
  user: null,
  isAdmin: false,
  isCurator: false,
  isCloudSuperuser: false,
  refreshUser: async () => {},
  updateUserAutoScroll: async () => {},
  updateUserShortcuts: async () => {},
  toggleAssistantPinnedStatus: async () => true,
  updateUserTemperatureOverrideEnabled: async () => {},
  updateUserPersonalization: async () => {},
}
```

### `react-markdown.tsx`

**Problem:** The `react-markdown` library uses ESM (ECMAScript Modules) which Jest cannot parse by default without extensive configuration. Many components (like `Field.tsx`) import this library.

**Solution:** This mock provides a simple component that renders markdown content as plain text, avoiding ESM parsing issues.

**Usage:** Automatically applied via `jest.config.js` moduleNameMapper.

**Limitation:** Markdown is not actually rendered/parsed in tests - content is displayed as-is. If you need to test markdown rendering, you'll need to configure Jest to handle ESM properly.

### `remark-gfm.ts`

**Problem:** The `remark-gfm` library (GitHub Flavored Markdown plugin for react-markdown) also uses ESM.

**Solution:** This mock provides a no-op plugin function that does nothing but allows components to import it without errors.

**Usage:** Automatically applied via `jest.config.js` moduleNameMapper.

## When to Add New Mocks

Add mocks to this directory when:

1. **ESM compatibility issues** - Library uses `export/import` syntax that Jest can't parse
2. **Complex setup requirements** - Component/provider requires extensive configuration that's not relevant to your test
3. **External dependencies** - Library makes network calls, accesses browser APIs not available in tests, etc.

## When NOT to Mock

Avoid mocking when:

1. **Testing the actual behavior** - If you're testing how markdown renders, don't mock react-markdown
2. **Simple to configure** - If it's easy to provide real props, use the real component
3. **Core business logic** - Don't mock your own application logic

## Configuration

These mocks are configured in `jest.config.js`:

```javascript
moduleNameMapper: {
  // Mock react-markdown and related packages
  "^react-markdown$": "<rootDir>/tests/setup/__mocks__/react-markdown.tsx",
  "^remark-gfm$": "<rootDir>/tests/setup/__mocks__/remark-gfm.ts",
  // Mock UserProvider
  "^@/components/user/UserProvider$": "<rootDir>/tests/setup/__mocks__/@/components/user/UserProvider.tsx",
  // ... other mappings
}
```

**Important:** Specific mocks must come BEFORE the generic `@/` path alias, otherwise the path alias will match first and the mock won't be applied.

## Debugging Mock Issues

If a component isn't getting the mock:

1. Check that the import path exactly matches the moduleNameMapper pattern
2. Clear Jest cache: `npx jest --clearCache`
3. Check that the mock file path is correct relative to `<rootDir>`
4. Verify the mock comes BEFORE generic path aliases in moduleNameMapper
