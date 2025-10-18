# React Testing Framework - Onyx Web

This document provides comprehensive guidance on writing tests for React components and hooks in the Onyx web application.

## Table of Contents

- [Overview](#overview)
- [Running Tests](#running-tests)
- [Writing Tests](#writing-tests)
- [Testing Patterns](#testing-patterns)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

## Overview

The Onyx web application uses a modern testing stack based on 2025 best practices:

- **Jest** - Test runner and framework
- **React Testing Library** - Component testing utilities
- **@testing-library/user-event** - User interaction simulation
- **SWR** - Data fetching (with fetch mocking for tests)
- **TypeScript** - Type-safe tests

### Testing Philosophy

> "The more your tests resemble the way your software is used, the more confidence they can give you."
> — Testing Library Guiding Principle

**Focus on:**
- ✅ User-facing behavior
- ✅ Accessibility (use `getByRole`, `getByLabelText`)
- ✅ What users see and do
- ✅ Integration testing over unit testing

**Avoid:**
- ❌ Testing implementation details
- ❌ Testing internal state
- ❌ Testing private functions
- ❌ Over-mocking

## Running Tests

```bash
# Run all tests
npm test

# Run tests in watch mode
npm run test:watch

# Run tests with coverage
npm run test:coverage

# Run tests verbose
npm run test:verbose

# Run specific test file
npm test -- Button.test.tsx

# Run tests matching pattern
npm test -- --testNamePattern="dropdown"
```

## Writing Tests

### File Structure

**Modern Approach (Recommended):** Co-locate tests with source files

```
src/components/
├── Button.tsx
└── Button.test.tsx

src/lib/
├── hooks.ts
└── hooks.test.tsx
```

**Why this structure?**
- ✅ Easier to find tests (right next to the code)
- ✅ No need for `__tests__` directories
- ✅ Simpler imports
- ✅ Follows modern Jest best practices
- ✅ Works great with VS Code and IDEs

### Basic Test Template

```typescript
/**
 * @jest-environment jsdom
 */
import { render, screen, userEvent } from "@tests/setup/test-utils";
import { MyComponent } from "../MyComponent";

describe("MyComponent", () => {
  it("allows users to interact with the component", async () => {
    const handleClick = jest.fn();
    const user = userEvent.setup();

    render(<MyComponent onClick={handleClick} />);

    // Best Practice: Use accessible queries
    const button = screen.getByRole("button", { name: /submit/i });
    await user.click(button);

    expect(handleClick).toHaveBeenCalled();
  });
});
```

## Testing Patterns

### 1. Testing Simple Components

**Example: Button Component**

```typescript
describe("Button Component", () => {
  it("allows users to click and triggers onClick handler", async () => {
    const handleClick = jest.fn();
    const user = userEvent.setup();

    render(<Button onClick={handleClick}>Submit Form</Button>);

    const button = screen.getByRole("button", { name: /submit form/i });
    await user.click(button);

    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("prevents interaction when disabled", async () => {
    const handleClick = jest.fn();
    const user = userEvent.setup();

    render(<Button onClick={handleClick} disabled>Disabled</Button>);

    const button = screen.getByRole("button", { name: /disabled/i });
    expect(button).toBeDisabled();

    await user.click(button);
    expect(handleClick).not.toHaveBeenCalled();
  });
});
```

### 2. Testing Interactive Components

**Example: Dropdown with Search**

```typescript
describe("Dropdown Component", () => {
  it("filters options based on search term", async () => {
    const handleSelect = jest.fn();
    const user = userEvent.setup();
    const options = [
      { name: "Apple", value: "apple" },
      { name: "Banana", value: "banana" },
    ];

    render(<Dropdown options={options} onSelect={handleSelect} />);

    const searchInput = screen.getByRole("textbox");
    await user.type(searchInput, "Apple");

    expect(screen.getByRole("menuitem", { name: /apple/i })).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /banana/i })).not.toBeInTheDocument();
  });
});
```

### 3. Testing Async Operations

**Example: Editable Value with async submit**

```typescript
describe("EditableValue Component", () => {
  it("calls onSubmit when user presses Enter", async () => {
    const handleSubmit = jest.fn().mockResolvedValue(true);
    const user = userEvent.setup();

    render(<EditableValue initialValue="Old" onSubmit={handleSubmit} />);

    await user.click(screen.getByText("Old"));
    const input = screen.getByRole("textbox");

    await user.clear(input);
    await user.type(input, "New{Enter}");

    // Wait for async operation
    await waitFor(() => {
      expect(handleSubmit).toHaveBeenCalledWith("New");
    });
  });
});
```

### 4. Testing SWR Hooks

**Example: Data fetching hook**

```typescript
describe("usePublicCredentials Hook", () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("fetches and returns credentials data", async () => {
    const mockData = [{ id: 1, name: "Test" }];

    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: true,
      json: async () => mockData,
    });

    const { result } = renderHook(() => usePublicCredentials());

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.data).toEqual(mockData);
  });
});
```

### 5. Testing Formik Forms

**Example: Form with validation**

```typescript
describe("Login Form", () => {
  it("shows validation error for invalid email", async () => {
    const handleSubmit = jest.fn();
    const user = userEvent.setup();

    render(<LoginForm onSubmit={handleSubmit} />);

    const emailInput = screen.getByLabelText(/email/i);
    await user.type(emailInput, "invalid-email");

    const submitButton = screen.getByRole("button", { name: /submit/i });
    await user.click(submitButton);

    // Best Practice: Use findBy for async validation
    expect(await screen.findByText(/invalid email/i)).toBeInTheDocument();
    expect(handleSubmit).not.toHaveBeenCalled();
  });
});
```

## Best Practices

### Query Priority

Use queries in this priority order:

1. **`getByRole`** - Best for accessibility
   ```typescript
   screen.getByRole("button", { name: /submit/i })
   screen.getByRole("textbox", { name: /email/i })
   ```

2. **`getByLabelText`** - For form fields
   ```typescript
   screen.getByLabelText(/password/i)
   ```

3. **`getByPlaceholderText`** - When label is not available
   ```typescript
   screen.getByPlaceholderText(/search/i)
   ```

4. **`getByText`** - For non-interactive elements
   ```typescript
   screen.getByText(/welcome back/i)
   ```

5. **`getByTestId`** - Last resort only
   ```typescript
   screen.getByTestId("custom-component")
   ```

### Async Testing

Always use `async/await` with user events:

```typescript
const user = userEvent.setup();

// ✅ Correct
await user.click(button);
await user.type(input, "text");

// ❌ Wrong
user.click(button); // Missing await
```

Use `waitFor` for async state changes:

```typescript
// ✅ Correct
await waitFor(() => {
  expect(screen.getByText(/loading/i)).not.toBeInTheDocument();
});

// ❌ Wrong
expect(screen.queryByText(/loading/i)).not.toBeInTheDocument(); // May be flaky
```

### Accessibility Testing

Test with screen reader-friendly queries:

```typescript
// ✅ Good - tests accessibility
const button = screen.getByRole("button", { name: /submit/i });

// ❌ Bad - doesn't test accessibility
const button = screen.getByTestId("submit-button");
```

### Mocking Data

Mock at the right level:

```typescript
// ✅ Good - Mock fetch for SWR hooks
global.fetch = jest.fn().mockResolvedValue({
  ok: true,
  json: async () => mockData,
});

// ❌ Bad - Don't mock SWR directly
jest.mock("swr");
```

## Troubleshooting

### Common Issues

**Issue: "Not wrapped in act(...)" warning**

```typescript
// Use userEvent instead of fireEvent
const user = userEvent.setup();
await user.click(button); // ✅ Correct

fireEvent.click(button); // ❌ May cause act warnings
```

**Issue: "Unable to find element"**

```typescript
// Use async queries for elements that appear later
const element = await screen.findByText(/loading/i); // ✅

const element = screen.getByText(/loading/i); // ❌ May fail if not immediate
```

**Issue: "Test timeout"**

```typescript
// Increase timeout for slow operations
await waitFor(() => {
  expect(result.current.data).toBeDefined();
}, { timeout: 5000 }); // 5 seconds instead of default 1 second
```

### Debugging Tests

```typescript
// Print the DOM
screen.debug();

// Print a specific element
screen.debug(screen.getByRole("button"));

// Log available roles
screen.logTestingPlaygroundURL();
```

## Resources

- [React Testing Library Docs](https://testing-library.com/docs/react-testing-library/intro/)
- [Jest Documentation](https://jestjs.io/docs/getting-started)
- [Common Testing Mistakes](https://kentcdodds.com/blog/common-mistakes-with-react-testing-library)
- [Testing Playground](https://testing-playground.com/) - Interactive query builder

## Examples

See the following test files for complete examples:

- `src/components/Button.test.tsx` - Simple component testing
- `src/components/Dropdown.test.tsx` - Interactive component with user input
- `src/components/EditableValue.test.tsx` - Async operations and state changes
- `src/lib/hooks.test.tsx` - SWR hook testing with fetch mocking

## Contributing

When adding new tests:

1. Follow the existing patterns in the codebase
2. Use accessible queries (`getByRole`, `getByLabelText`)
3. Test user behavior, not implementation
4. Write clear test descriptions
5. Keep tests focused and independent
