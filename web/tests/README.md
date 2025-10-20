# React Integration Testing Guide

Comprehensive guide for writing integration tests in the Onyx web application using Jest and React Testing Library.

## Table of Contents

- [Running Tests](#running-tests)
- [Core Concepts](#core-concepts)
- [Writing Tests](#writing-tests)
- [Query Selectors](#query-selectors)
- [User Interactions](#user-interactions)
- [Async Operations](#async-operations)
- [Mocking](#mocking)
- [Common Patterns](#common-patterns)
- [Testing Philosophy](#testing-philosophy)
- [Troubleshooting](#troubleshooting)

## Running Tests

```bash
# Run all tests
npm test

# Run specific test file
npm test -- EmailPasswordForm.test

# Run tests matching pattern
npm test -- --testPathPattern="auth"

# Run without coverage
npm test -- --no-coverage

# Run in watch mode
npm test -- --watch

# Run with verbose output
npm test -- --verbose
```

## Core Concepts

### Test Structure

Tests are **co-located** with source files for easy discovery and maintenance:

```
src/app/auth/login/
├── EmailPasswordForm.tsx
└── EmailPasswordForm.test.tsx
```

### Test Anatomy

Every test follows this structure:

```typescript
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import MyComponent from "./MyComponent";

test("descriptive test name explaining user behavior", async () => {
  // 1. Setup - Create user, mock APIs
  const user = setupUser();
  const fetchSpy = jest.spyOn(global, "fetch");

  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ data: "value" }),
  } as Response);

  // 2. Render - Display the component
  render(<MyComponent />);

  // 3. Act - Simulate user interactions
  await user.type(screen.getByRole("textbox"), "test input");
  await user.click(screen.getByRole("button", { name: /submit/i }));

  // 4. Assert - Verify expected outcomes
  await waitFor(() => {
    expect(screen.getByText(/success/i)).toBeInTheDocument();
  });

  // 5. Cleanup - Restore mocks
  fetchSpy.mockRestore();
});
```

### setupUser() - Automatic act() Wrapping

**ALWAYS use `setupUser()` instead of `userEvent.setup()`**

```typescript
// ✅ Correct - Automatic act() wrapping
const user = setupUser();
await user.click(button);
await user.type(input, "text");

// ❌ Wrong - Manual act() required, verbose
const user = userEvent.setup();
await act(async () => {
  await user.click(button);
});
```

The `setupUser()` helper automatically wraps all user interactions in React's `act()` to prevent warnings and ensure proper state updates.

## Writing Tests

### Query Selectors

Use queries in this priority order (most accessible first):

#### 1. Role Queries (Preferred)

```typescript
// Buttons
screen.getByRole("button", { name: /submit/i })
screen.getByRole("button", { name: /cancel/i })

// Text inputs
screen.getByRole("textbox", { name: /email/i })

// Checkboxes
screen.getByRole("checkbox", { name: /remember me/i })

// Links
screen.getByRole("link", { name: /learn more/i })

// Headings
screen.getByRole("heading", { name: /welcome/i })
```

#### 2. Label Queries

```typescript
// For form inputs with labels
screen.getByLabelText(/password/i)
screen.getByLabelText(/email address/i)
```

#### 3. Placeholder Queries

```typescript
// When no label exists
screen.getByPlaceholderText(/enter email/i)
```

#### 4. Text Queries

```typescript
// For non-interactive text
screen.getByText(/welcome back/i)
screen.getByText(/error occurred/i)
```

#### Query Variants

```typescript
// getBy - Throws error if not found (immediate)
screen.getByRole("button")

// queryBy - Returns null if not found (checking absence)
expect(screen.queryByText(/error/i)).not.toBeInTheDocument()

// findBy - Returns promise, waits for element (async)
expect(await screen.findByText(/success/i)).toBeInTheDocument()

// getAllBy - Returns array of all matches
const inputs = screen.getAllByRole("textbox")
```

### Query Selectors: The Wrong Way

**❌ Avoid these anti-patterns:**

```typescript
// DON'T query by test IDs
screen.getByTestId("submit-button")

// DON'T query by class names
container.querySelector(".submit-btn")

// DON'T query by element types
container.querySelector("button")
```

## User Interactions

### Basic Interactions

```typescript
const user = setupUser();

// Click
await user.click(screen.getByRole("button", { name: /submit/i }));

// Type text
await user.type(screen.getByRole("textbox"), "test input");

// Clear and type
await user.clear(input);
await user.type(input, "new value");

// Check/uncheck checkbox
await user.click(screen.getByRole("checkbox"));

// Select from dropdown
await user.selectOptions(
  screen.getByRole("combobox"),
  "option-value"
);

// Upload file
const file = new File(["content"], "test.txt", { type: "text/plain" });
const input = screen.getByLabelText(/upload/i);
await user.upload(input, file);
```

### Form Interactions

```typescript
test("user can fill and submit form", async () => {
  const user = setupUser();

  render(<ContactForm />);

  await user.type(screen.getByLabelText(/name/i), "John Doe");
  await user.type(screen.getByLabelText(/email/i), "john@example.com");
  await user.type(screen.getByLabelText(/message/i), "Hello!");
  await user.click(screen.getByRole("button", { name: /send/i }));

  await waitFor(() => {
    expect(screen.getByText(/message sent/i)).toBeInTheDocument();
  });
});
```

## Async Operations

### Handling Async State Updates

**Rule**: After triggering state changes, always wait for UI updates before asserting.

#### Pattern 1: findBy Queries (Simplest)

```typescript
// Element appears after async operation
await user.click(createButton);
expect(await screen.findByRole("textbox")).toBeInTheDocument();
```

#### Pattern 2: waitFor (Complex Assertions)

```typescript
await user.click(submitButton);

await waitFor(() => {
  expect(screen.getByText("Success")).toBeInTheDocument();
  expect(screen.getByText("Count: 5")).toBeInTheDocument();
});
```

#### Pattern 3: waitForElementToBeRemoved

```typescript
await user.click(deleteButton);

await waitForElementToBeRemoved(() => screen.queryByText(/item name/i));
```

### Common Async Mistakes

```typescript
// ❌ Wrong - getBy immediately after state change
await user.click(button);
expect(screen.getByText("Updated")).toBeInTheDocument(); // May fail!

// ✅ Correct - Wait for state update
await user.click(button);
expect(await screen.findByText("Updated")).toBeInTheDocument();

// ❌ Wrong - Multiple getBy calls without waiting
await user.click(button);
expect(screen.getByText("Success")).toBeInTheDocument();
expect(screen.getByText("Data loaded")).toBeInTheDocument();

// ✅ Correct - Single waitFor with multiple assertions
await user.click(button);
await waitFor(() => {
  expect(screen.getByText("Success")).toBeInTheDocument();
  expect(screen.getByText("Data loaded")).toBeInTheDocument();
});
```

## Mocking

### Mocking fetch API

**IMPORTANT**: Always document which endpoint each mock corresponds to using comments.

```typescript
let fetchSpy: jest.SpyInstance;

beforeEach(() => {
  fetchSpy = jest.spyOn(global, "fetch");
});

afterEach(() => {
  fetchSpy.mockRestore();
});

test("fetches data successfully", async () => {
  // Mock GET /api/data
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ data: [1, 2, 3] }),
  } as Response);

  render(<MyComponent />);

  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalledWith("/api/data");
  });
});
```

**Why comment the endpoint?** Sequential mocks can be confusing. Comments make it clear which API call each mock corresponds to, making tests easier to understand and maintain.

### Multiple API Calls

**Pattern**: Document each endpoint with a comment, then verify it was called correctly.

```typescript
test("handles multiple API calls", async () => {
  const user = setupUser();

  // Mock GET /api/items
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ items: [] }),
  } as Response);

  // Mock POST /api/items
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ id: 1, name: "New Item" }),
  } as Response);

  render(<MyComponent />);

  // Verify GET was called
  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalledWith("/api/items");
  });

  await user.click(screen.getByRole("button", { name: /create/i }));

  // Verify POST was called
  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/items",
      expect.objectContaining({ method: "POST" })
    );
  });
});
```

**Three API calls example:**

```typescript
test("test, create, and set as default", async () => {
  const user = setupUser();

  // Mock POST /api/llm/test
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({}),
  } as Response);

  // Mock PUT /api/llm/provider?is_creation=true
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ id: 5, name: "New Provider" }),
  } as Response);

  // Mock POST /api/llm/provider/5/default
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({}),
  } as Response);

  render(<MyForm />);

  await user.type(screen.getByLabelText(/name/i), "New Provider");
  await user.click(screen.getByRole("button", { name: /create/i }));

  // Verify all three endpoints were called
  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/llm/test",
      expect.objectContaining({ method: "POST" })
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/llm/provider",
      expect.objectContaining({ method: "PUT" })
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/llm/provider/5/default",
      expect.objectContaining({ method: "POST" })
    );
  });
});
```

### Verifying Request Body

```typescript
test("sends correct data", async () => {
  const user = setupUser();

  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({}),
  } as Response);

  render(<MyForm />);

  await user.type(screen.getByLabelText(/name/i), "Test");
  await user.click(screen.getByRole("button", { name: /submit/i }));

  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalled();
  });

  const callArgs = fetchSpy.mock.calls[0];
  const requestBody = JSON.parse(callArgs[1].body);

  expect(requestBody).toEqual({
    name: "Test",
    active: true,
  });
});
```

### Mocking Errors

```typescript
test("displays error message on failure", async () => {
  // Mock GET /api/data (network error)
  fetchSpy.mockRejectedValueOnce(new Error("Network error"));

  render(<MyComponent />);

  await waitFor(() => {
    expect(screen.getByText(/failed to load/i)).toBeInTheDocument();
  });
});

test("handles API error response", async () => {
  // Mock POST /api/items (server error)
  fetchSpy.mockResolvedValueOnce({
    ok: false,
    status: 500,
  } as Response);

  render(<MyComponent />);

  await waitFor(() => {
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument();
  });
});
```

### Mocking Next.js Router

```typescript
// At top of test file
jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: jest.fn(),
    back: jest.fn(),
    refresh: jest.fn(),
  }),
  usePathname: () => "/current-path",
}));
```

## Common Patterns

### Testing CRUD Operations

```typescript
describe("User Management", () => {
  test("creates new user", async () => {
    const user = setupUser();

    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ id: 1, name: "New User" }),
    } as Response);

    render(<UserForm />);

    await user.type(screen.getByLabelText(/name/i), "New User");
    await user.click(screen.getByRole("button", { name: /create/i }));

    await waitFor(() => {
      expect(screen.getByText(/user created/i)).toBeInTheDocument();
    });
  });

  test("edits existing user", async () => {
    const user = setupUser();

    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ id: 1, name: "Updated User" }),
    } as Response);

    render(<UserForm initialData={{ id: 1, name: "Old Name" }} />);

    await user.clear(screen.getByLabelText(/name/i));
    await user.type(screen.getByLabelText(/name/i), "Updated User");
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => {
      expect(screen.getByText(/user updated/i)).toBeInTheDocument();
    });
  });

  test("deletes user", async () => {
    const user = setupUser();

    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    render(<UserList />);

    await waitFor(() => {
      expect(screen.getByText("John Doe")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /delete/i }));

    await waitFor(() => {
      expect(screen.queryByText("John Doe")).not.toBeInTheDocument();
    });
  });
});
```

### Testing Conditional Rendering

```typescript
test("shows edit form when edit button clicked", async () => {
  const user = setupUser();

  render(<MyComponent />);

  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /edit/i }));

  expect(await screen.findByRole("textbox")).toBeInTheDocument();
});

test("toggles between states", async () => {
  const user = setupUser();

  render(<Toggle />);

  const button = screen.getByRole("button", { name: /show details/i });

  await user.click(button);
  expect(await screen.findByText(/details content/i)).toBeInTheDocument();

  await user.click(button);
  expect(screen.queryByText(/details content/i)).not.toBeInTheDocument();
});
```

### Testing Lists and Tables

```typescript
test("displays list of items", async () => {
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({
      items: [
        { id: 1, name: "Item 1" },
        { id: 2, name: "Item 2" },
        { id: 3, name: "Item 3" },
      ],
    }),
  } as Response);

  render(<ItemList />);

  await waitFor(() => {
    expect(screen.getByText("Item 1")).toBeInTheDocument();
    expect(screen.getByText("Item 2")).toBeInTheDocument();
    expect(screen.getByText("Item 3")).toBeInTheDocument();
  });
});

test("filters items", async () => {
  const user = setupUser();

  render(<FilterableList items={mockItems} />);

  await user.type(screen.getByRole("searchbox"), "specific");

  await waitFor(() => {
    expect(screen.getByText("Specific Item")).toBeInTheDocument();
    expect(screen.queryByText("Other Item")).not.toBeInTheDocument();
  });
});
```

### Testing Validation

```typescript
test("shows validation errors", async () => {
  const user = setupUser();

  render(<LoginForm />);

  await user.click(screen.getByRole("button", { name: /submit/i }));

  await waitFor(() => {
    expect(screen.getByText(/email is required/i)).toBeInTheDocument();
    expect(screen.getByText(/password is required/i)).toBeInTheDocument();
  });
});

test("clears validation on valid input", async () => {
  const user = setupUser();

  render(<LoginForm />);

  await user.click(screen.getByRole("button", { name: /submit/i }));

  await waitFor(() => {
    expect(screen.getByText(/email is required/i)).toBeInTheDocument();
  });

  await user.type(screen.getByLabelText(/email/i), "valid@email.com");

  await waitFor(() => {
    expect(screen.queryByText(/email is required/i)).not.toBeInTheDocument();
  });
});
```

## Testing Philosophy

### What to Test

**✅ Test user-visible behavior:**
- Forms can be filled and submitted
- Buttons trigger expected actions
- Success/error messages appear
- Navigation works correctly
- Data is displayed after loading
- Validation errors show and clear appropriately

**✅ Test integration points:**
- API calls are made with correct parameters
- Responses are handled properly
- Error states are handled
- Loading states appear

**❌ Don't test implementation details:**
- Internal state values
- Component lifecycle methods
- CSS class names
- Specific React hooks being used

### Test Naming

Write test names that describe user behavior:

```typescript
// ✅ Good - Describes what user can do
test("user can create new prompt", async () => {})
test("shows error when API call fails", async () => {})
test("filters items by search term", async () => {})

// ❌ Bad - Implementation-focused
test("handleSubmit is called", async () => {})
test("state updates correctly", async () => {})
test("renders without crashing", async () => {})
```

### Minimal Mocking

Only mock external dependencies:

```typescript
// ✅ Mock external APIs
jest.spyOn(global, "fetch")

// ✅ Mock Next.js router
jest.mock("next/navigation")

// ✅ Mock problematic packages
// (configured in tests/setup/__mocks__)

// ❌ Don't mock application code
// ❌ Don't mock component internals
// ❌ Don't mock utility functions
```

## Troubleshooting

### "Not wrapped in act()" Warning

**Solution**: Always use `setupUser()` instead of `userEvent.setup()`

```typescript
// ✅ Correct
const user = setupUser();

// ❌ Wrong
const user = userEvent.setup();
```

### "Unable to find element" Error

**Solution**: Element hasn't appeared yet, use `findBy` or `waitFor`

```typescript
// ❌ Wrong - getBy doesn't wait
await user.click(button);
expect(screen.getByText("Success")).toBeInTheDocument();

// ✅ Correct - findBy waits
await user.click(button);
expect(await screen.findByText("Success")).toBeInTheDocument();
```

### "Multiple elements found" Error

**Solution**: Be more specific with your query

```typescript
// ❌ Too broad
screen.getByRole("button")

// ✅ Specific
screen.getByRole("button", { name: /submit/i })
```

### Test Times Out

**Causes**:
1. Async operation never completes
2. Waiting for element that never appears
3. Missing mock for API call

**Solutions**:
```typescript
// Check fetch is mocked
expect(fetchSpy).toHaveBeenCalled()

// Use queryBy to check if element exists
expect(screen.queryByText("Text")).toBeInTheDocument()

// Verify mock is set up before render
fetchSpy.mockResolvedValueOnce(...)
render(<Component />)
```

## Examples

See comprehensive test examples:
- `src/app/auth/login/EmailPasswordForm.test.tsx` - Login/signup workflows, validation
- `src/app/chat/input-prompts/InputPrompts.test.tsx` - CRUD operations, conditional rendering
- `src/app/admin/configuration/llm/CustomLLMProviderUpdateForm.test.tsx` - Complex forms, multi-step workflows

## Built-in Mocks

Only essential mocks in `tests/setup/__mocks__/`:
- `UserProvider` - Removes auth requirement for tests
- `react-markdown` / `remark-gfm` - ESM compatibility

See `tests/setup/__mocks__/README.md` for details.
