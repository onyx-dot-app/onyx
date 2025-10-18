# Test Utilities Documentation

## Overview

The Onyx frontend testing framework provides reusable utilities that make integration tests cleaner, more readable, and easier to maintain.

## What Was Created

### 1. API Mocking Utilities (`tests/setup/api-mocks.ts`)

Simplifies mocking fetch responses with type-safe helpers:

- `mockApiSuccess()` - Mock successful responses
- `mockApiError()` - Mock error responses
- `mockUnauthorizedError()`, `mockNotFoundError()`, etc. - Convenience helpers for common HTTP errors
- `mockNetworkError()` - Mock network failures
- `mockSlowApiSuccess()` - Mock slow responses (for testing loading states)
- `mockSequentialResponses()` - Mock multiple responses in sequence
- `setupFetchSpy()` / `cleanupFetchSpy()` - Setup and teardown helpers
- `expectRequest()` - Validate request details
- `getRequestBody()`, `getRequestUrl()`, etc. - Extract request data

### 2. Test Helper Utilities (`tests/setup/test-helpers.ts`)

Provides helpers for common test operations:

**Form Interactions:**
- `fillForm()` - Fill multiple form fields at once
- `fillFormByPlaceholder()` - Fill form by placeholder text
- `clearAndType()` - Clear and type into input
- `submitForm()` - Submit a form

**User Actions:**
- `clickButton()` - Click button by accessible name
- `selectDropdownOption()` - Select from dropdown
- `uploadFile()` - Upload a file
- `pressKeyboardShortcut()` - Press keyboard shortcuts
- `tabThroughForm()` - Navigate form with Tab key

**Waiting & Assertions:**
- `waitForText()` - Wait for text to appear
- `waitForTextToDisappear()` - Wait for text to disappear
- `waitForSuccessMessage()` / `waitForErrorMessage()` - Wait for notifications
- `waitForLoadingToComplete()` - Wait for loading state
- `waitForModal()` - Wait for modal to appear
- `waitForButtonState()` - Wait for button to be enabled/disabled
- `expectFieldValue()` / `expectFieldEmpty()` - Assert form field values

**Utilities:**
- `elementExists()` - Check if element exists
- `findWithin()` - Find element within container
- `createTestFile()` - Create test file for uploads
- `debugScreen()` - Debug helper
- `getQueryParam()` - Extract query parameters from URL

### 3. Centralized Export (`tests/setup/test-utils.tsx`)

All utilities are re-exported from `test-utils.tsx` for convenience:

```typescript
import {
  // Testing Library
  render,
  screen,
  waitFor,
  userEvent,
  within,
  // Test Helpers
  fillForm,
  clickButton,
  waitForText,
  submitForm,
  // API Mocks
  mockApiSuccess,
  mockApiError,
  setupFetchSpy,
  cleanupFetchSpy,
  expectRequest,
} from "@tests/setup/test-utils";
```

## Benefits

### 1. Code Reduction

**Before:**
```typescript
it("allows user to login", async () => {
  const user = userEvent.setup();

  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ success: true }),
  } as Response);

  await user.type(screen.getByLabelText(/email/i), "test@example.com");
  await user.type(screen.getByLabelText(/password/i), "password123");

  const submitButton = screen.getByRole("button", { name: /log in/i });
  await user.click(submitButton);

  await waitFor(() => {
    expect(screen.getByText(/welcome/i)).toBeInTheDocument();
  });

  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          email: "test@example.com",
          password: "password123",
        }),
      })
    );
  });
});
```

**After:**
```typescript
it("allows user to login", async () => {
  const user = userEvent.setup();

  mockApiSuccess(fetchSpy, { success: true });

  await fillForm(user, {
    Email: "test@example.com",
    Password: "password123",
  });

  await submitForm(user, "Log In");

  await waitForText(/welcome/i);

  expectRequest(fetchSpy, {
    url: "/api/auth/login",
    method: "POST",
    body: {
      email: "test@example.com",
      password: "password123",
    },
  });
});
```

**Result: 33% fewer lines, much more readable!**

### 2. Consistency

- Standardized patterns across all tests
- Same approach for mocking, form filling, assertions
- Easier for new developers to understand

### 3. Maintainability

- Change implementation in one place
- All tests automatically updated
- Easier to add new features (e.g., new error types)

### 4. Readability

- Self-documenting function names
- Clear intent (`fillForm` vs. multiple `type` calls)
- Less noise, more signal

## Quick Start

### Basic Test Setup

```typescript
import {
  render,
  screen,
  userEvent,
  setupFetchSpy,
  cleanupFetchSpy,
  mockApiSuccess,
  fillForm,
  submitForm,
  waitForText,
} from "@tests/setup/test-utils";

describe("My Component", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = setupFetchSpy();
  });

  afterEach(() => {
    cleanupFetchSpy(fetchSpy);
  });

  it("does something", async () => {
    const user = userEvent.setup();

    mockApiSuccess(fetchSpy, { data: "value" });

    render(<MyComponent />);

    await fillForm(user, { Name: "John" });
    await submitForm(user);
    await waitForText("Success");
  });
});
```

## Common Patterns

### 1. Success Path Test

```typescript
it("submits form successfully", async () => {
  const user = userEvent.setup();

  mockApiSuccess(fetchSpy, { success: true });

  render(<Form />);

  await fillForm(user, { Email: "test@example.com" });
  await submitForm(user);

  await waitForSuccessMessage("Form submitted");

  expectRequest(fetchSpy, {
    url: "/api/submit",
    method: "POST",
    body: { email: "test@example.com" },
  });
});
```

### 2. Error Handling Test

```typescript
it("shows error message", async () => {
  const user = userEvent.setup();

  mockBadRequestError(fetchSpy, "Invalid email");

  render(<Form />);

  await fillForm(user, { Email: "invalid" });
  await submitForm(user);

  await waitForErrorMessage("Invalid email");
});
```

### 3. Loading State Test

```typescript
it("shows loading indicator", async () => {
  const user = userEvent.setup();

  mockSlowApiSuccess(fetchSpy, { data: "value" }, 1000);

  render(<Component />);

  await clickButton(user, "Fetch Data");

  expect(screen.getByText(/loading/i)).toBeInTheDocument();

  await waitForLoadingToComplete();

  expect(screen.getByText("value")).toBeInTheDocument();
});
```

### 4. CRUD Workflow Test

```typescript
it("completes CRUD workflow", async () => {
  const user = userEvent.setup();

  mockSequentialResponses(fetchSpy, [
    { success: true, data: [] }, // GET
    { success: true, data: { id: 1 }, status: 201 }, // POST
    { success: true, data: { id: 1, updated: true } }, // PATCH
    { success: true, data: {}, status: 204 }, // DELETE
  ]);

  render(<ItemManager />);

  // CREATE
  await clickButton(user, "Add");
  await fillForm(user, { Name: "Item" });
  await submitForm(user, "Create");
  await waitForSuccessMessage("Created");

  // UPDATE
  await clickButton(user, "Edit");
  await fillForm(user, { Name: "Updated" });
  await submitForm(user, "Save");
  await waitForSuccessMessage("Updated");

  // DELETE
  await clickButton(user, "Delete");
  await clickButton(user, "Confirm");
  await waitForSuccessMessage("Deleted");

  // Verify all API calls
  expect(fetchSpy).toHaveBeenCalledTimes(4);
});
```

## API Reference

### API Mocking

| Function | Description | Example |
|----------|-------------|---------|
| `mockApiSuccess(spy, data, status?)` | Mock successful response | `mockApiSuccess(fetchSpy, { id: 1 })` |
| `mockApiError(spy, status, detail)` | Mock error response | `mockApiError(fetchSpy, 400, "Bad Request")` |
| `mockBadRequestError(spy, detail)` | Mock 400 error | `mockBadRequestError(fetchSpy, "Invalid")` |
| `mockUnauthorizedError(spy, detail)` | Mock 401 error | `mockUnauthorizedError(fetchSpy, "Forbidden")` |
| `mockNotFoundError(spy, detail)` | Mock 404 error | `mockNotFoundError(fetchSpy, "Not found")` |
| `mockConflictError(spy, detail)` | Mock 409 error | `mockConflictError(fetchSpy, "Duplicate")` |
| `mockServerError(spy, detail)` | Mock 500 error | `mockServerError(fetchSpy, "Error")` |
| `mockNetworkError(spy, message?)` | Mock network failure | `mockNetworkError(fetchSpy)` |
| `mockSlowApiSuccess(spy, data, ms)` | Mock slow response | `mockSlowApiSuccess(fetchSpy, {}, 1000)` |
| `mockSequentialResponses(spy, responses)` | Mock multiple responses | See example above |
| `setupFetchSpy()` | Create fetch spy | `fetchSpy = setupFetchSpy()` |
| `cleanupFetchSpy(spy)` | Restore fetch spy | `cleanupFetchSpy(fetchSpy)` |
| `expectRequest(spy, expected)` | Validate request | `expectRequest(fetchSpy, { url, method, body })` |
| `getRequestBody(spy, index?)` | Extract request body | `const body = getRequestBody(fetchSpy)` |
| `getRequestUrl(spy, index?)` | Extract request URL | `const url = getRequestUrl(fetchSpy)` |
| `getRequestMethod(spy, index?)` | Extract request method | `const method = getRequestMethod(fetchSpy)` |

### Test Helpers

| Function | Description | Example |
|----------|-------------|---------|
| `fillForm(user, fields)` | Fill multiple form fields | `await fillForm(user, { Email: "test@example.com" })` |
| `fillFormByPlaceholder(user, fields)` | Fill by placeholder | `await fillFormByPlaceholder(user, { "Enter email": "test@example.com" })` |
| `clickButton(user, name)` | Click button | `await clickButton(user, "Submit")` |
| `submitForm(user, name?)` | Submit form | `await submitForm(user, "Create")` |
| `clearAndType(user, element, text)` | Clear and type | `await clearAndType(user, input, "new text")` |
| `waitForText(text, options?)` | Wait for text | `await waitForText(/success/i)` |
| `waitForTextToDisappear(text, options?)` | Wait for text to disappear | `await waitForTextToDisappear(/loading/i)` |
| `waitForSuccessMessage(message, options?)` | Wait for success | `await waitForSuccessMessage("Saved")` |
| `waitForErrorMessage(message, options?)` | Wait for error | `await waitForErrorMessage("Invalid")` |
| `waitForLoadingToComplete(text?, options?)` | Wait for loading | `await waitForLoadingToComplete()` |
| `waitForModal(title, options?)` | Wait for modal | `await waitForModal("Confirm")` |
| `waitForButtonState(name, state, options?)` | Wait for button state | `await waitForButtonState("Submit", "enabled")` |
| `elementExists(text, role?)` | Check existence | `expect(elementExists("Text")).toBe(true)` |
| `expectFieldValue(label, value)` | Assert field value | `expectFieldValue(/email/i, "test@example.com")` |
| `expectFieldEmpty(label)` | Assert field empty | `expectFieldEmpty(/password/i)` |

## Examples

See the following files for complete examples:

1. **`USING_TEST_UTILITIES.md`** - Comprehensive guide with before/after comparisons
2. **`EmailPasswordForm.test.tsx`** - Login workflow using utilities
3. **`InputPrompts.test.tsx`** - CRUD workflow using utilities
4. **`JEST_SPY_PATTERNS.md`** - Advanced spy patterns and techniques

## Best Practices

1. **Always import from test-utils**
   ```typescript
   import { render, mockApiSuccess } from "@tests/setup/test-utils";
   ```

2. **Use convenience helpers**
   ```typescript
   // ✅ Good
   mockUnauthorizedError(fetchSpy, "Invalid credentials");

   // ❌ Avoid
   mockApiError(fetchSpy, 401, "Invalid credentials");
   ```

3. **Chain helpers for workflows**
   ```typescript
   await fillForm(user, fields);
   await submitForm(user);
   await waitForSuccessMessage("Success");
   ```

4. **Validate requests with expectRequest**
   ```typescript
   expectRequest(fetchSpy, {
     url: "/api/endpoint",
     method: "POST",
     body: { data: "value" },
   });
   ```

## Adding Custom Helpers

You can extend the utilities by adding new functions to `api-mocks.ts` or `test-helpers.ts`:

```typescript
// In test-helpers.ts
export async function loginAsUser(
  user: ReturnType<typeof userEvent.setup>,
  email: string,
  password: string
): Promise<void> {
  await fillForm(user, { Email: email, Password: password });
  await submitForm(user, "Log In");
  await waitForText(/welcome/i);
}
```

Then use in tests:

```typescript
await loginAsUser(user, "test@example.com", "password123");
```

## Migration Guide

To migrate existing tests to use utilities:

1. **Update imports**
   ```typescript
   import {
     render,
     screen,
     userEvent,
     setupFetchSpy,
     mockApiSuccess,
     fillForm,
   } from "@tests/setup/test-utils";
   ```

2. **Replace fetch mocking**
   ```typescript
   // Before
   global.fetch = jest.fn();
   (global.fetch as jest.Mock).mockResolvedValueOnce({...});

   // After
   fetchSpy = setupFetchSpy();
   mockApiSuccess(fetchSpy, {...});
   ```

3. **Replace form interactions**
   ```typescript
   // Before
   await user.type(screen.getByLabelText(/email/i), "test@example.com");

   // After
   await fillForm(user, { Email: "test@example.com" });
   ```

4. **Replace assertions**
   ```typescript
   // Before
   await waitFor(() => {
     expect(screen.getByText(/success/i)).toBeInTheDocument();
   });

   // After
   await waitForSuccessMessage("Success");
   ```

## Summary

The test utilities provide a cleaner, more maintainable way to write integration tests. They:

- ✅ Reduce code by 33-50%
- ✅ Improve readability
- ✅ Standardize patterns
- ✅ Make tests easier to write and maintain
- ✅ Provide type-safe API mocking
- ✅ Include comprehensive helpers for common operations

Import everything from `@tests/setup/test-utils` and start writing cleaner tests today!
