# Using Test Utilities

This guide demonstrates how to use the reusable test utilities provided in the testing framework.

## Import Everything from One Place

```typescript
import {
  render,
  screen,
  userEvent,
  waitFor,
  // Test helpers
  fillForm,
  clickButton,
  waitForText,
  submitForm,
  // API mocks
  mockApiSuccess,
  mockApiError,
  mockNetworkError,
  setupFetchSpy,
  cleanupFetchSpy,
  expectRequest,
} from "@tests/setup/test-utils";
```

## API Mocking Utilities

### Basic Setup

```typescript
describe("My Component", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = setupFetchSpy(); // Helper function
  });

  afterEach(() => {
    cleanupFetchSpy(fetchSpy); // Helper function
  });
});
```

### Mock Successful Responses

```typescript
// Old way
fetchSpy.mockResolvedValueOnce({
  ok: true,
  status: 200,
  json: async () => ({ id: 1, name: "Test" }),
} as Response);

// New way with helper
mockApiSuccess(fetchSpy, { id: 1, name: "Test" });

// With custom status
mockApiSuccess(fetchSpy, { created: true }, 201);
```

### Mock Error Responses

```typescript
// Generic error
mockApiError(fetchSpy, 400, "Invalid input");

// Convenience helpers for common errors
mockBadRequestError(fetchSpy, "Invalid email format");
mockUnauthorizedError(fetchSpy, "Invalid credentials");
mockForbiddenError(fetchSpy, "Access denied");
mockNotFoundError(fetchSpy, "User not found");
mockConflictError(fetchSpy, "Email already exists");
mockServerError(fetchSpy, "Database error");

// Network error
mockNetworkError(fetchSpy, "Network request failed");
```

### Mock Slow Responses (Testing Loading States)

```typescript
it("shows loading spinner during request", async () => {
  const user = userEvent.setup();

  // Mock slow response (1000ms delay)
  mockSlowApiSuccess(fetchSpy, { data: "value" }, 1000);

  render(<Component />);
  await clickButton(user, "Fetch Data");

  // Loading spinner should be visible
  expect(screen.getByText(/loading/i)).toBeInTheDocument();

  // Wait for data to load
  await waitForText("value");

  // Loading spinner should be gone
  expect(screen.queryByText(/loading/i)).not.toBeInTheDocument();
});
```

### Mock Sequential Responses

```typescript
// Old way
fetchSpy
  .mockResolvedValueOnce({ ok: true, json: async () => item1 } as Response)
  .mockResolvedValueOnce({ ok: true, json: async () => item2 } as Response)
  .mockResolvedValueOnce({ ok: false, status: 400 } as Response);

// New way with helper
mockSequentialResponses(fetchSpy, [
  { success: true, data: item1 },
  { success: true, data: item2 },
  { success: false, status: 400, detail: "Validation error" },
]);
```

### Validate Requests

```typescript
// Old way
await waitFor(() => {
  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/users",
    expect.objectContaining({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "John", email: "john@example.com" }),
    })
  );
});

// New way with helper
await waitFor(() => {
  expectRequest(fetchSpy, {
    url: "/api/users",
    method: "POST",
    body: { name: "John", email: "john@example.com" },
    headers: { "Content-Type": "application/json" },
  });
});
```

### Extract Request Data

```typescript
// Get request URL
const url = getRequestUrl(fetchSpy, 0); // First call
expect(url).toBe("/api/users");

// Get request method
const method = getRequestMethod(fetchSpy, 0);
expect(method).toBe("POST");

// Get request body
const body = getRequestBody(fetchSpy, 0);
expect(body.email).toBe("test@example.com");

// Get request headers
const headers = getRequestHeaders(fetchSpy, 0);
expect(headers["Content-Type"]).toBe("application/json");
```

## Test Helper Utilities

### Fill Forms

```typescript
// Old way
await user.type(screen.getByLabelText(/email/i), "test@example.com");
await user.type(screen.getByLabelText(/password/i), "password123");
await user.type(screen.getByLabelText(/name/i), "John Doe");

// New way with helper
await fillForm(user, {
  Email: "test@example.com",
  Password: "password123",
  Name: "John Doe",
});

// Or by placeholder
await fillFormByPlaceholder(user, {
  "Enter email": "test@example.com",
  "Enter password": "password123",
});
```

### Click Buttons

```typescript
// Old way
const button = screen.getByRole("button", { name: /submit/i });
await user.click(button);

// New way with helper
await clickButton(user, "Submit");
await clickButton(user, /log in/i);
```

### Submit Forms

```typescript
// Simple submission
await submitForm(user); // Finds button with "submit" text

// Custom button text
await submitForm(user, "Create Account");
await submitForm(user, /log in/i);
```

### Wait for Text

```typescript
// Old way
await waitFor(() => {
  expect(screen.getByText(/success/i)).toBeInTheDocument();
});

// New way with helper
await waitForText(/success/i);
await waitForText("Account created successfully");

// Wait for error messages
await waitForErrorMessage("Invalid credentials");

// Wait for success messages
await waitForSuccessMessage("Changes saved");
```

### Wait for Loading

```typescript
// Wait for loading to disappear
await waitForLoadingToComplete();

// Custom loading text
await waitForLoadingToComplete(/fetching data/i);
```

### Clear and Type

```typescript
// Old way
const input = screen.getByLabelText(/email/i);
await user.clear(input);
await user.type(input, "new@example.com");

// New way with helper
const input = screen.getByLabelText(/email/i);
await clearAndType(user, input, "new@example.com");
```

### Check Element Existence

```typescript
// Old way
expect(screen.queryByText("Welcome")).not.toBeInTheDocument();

// New way with helper
expect(elementExists("Welcome")).toBe(false);
expect(elementExists("Submit", "button")).toBe(true);
```

### Work with Modals

```typescript
// Wait for modal to appear
await waitForModal("Confirm Delete");

// Close modal
await closeModal(user); // Press Escape
await closeModal(user, "button"); // Click close button
```

### Keyboard Navigation

```typescript
// Tab through form fields
await tabThroughForm(user, [
  { label: /email/i, value: "test@example.com" },
  { label: /password/i, value: "password123" },
  { label: /name/i, value: "John Doe" },
]);

// Press keyboard shortcuts
await pressKeyboardShortcut(user, "{Control>}s{/Control}"); // Ctrl+S
await pressKeyboardShortcut(user, "{Escape}");
```

### File Uploads

```typescript
// Create test file
const file = createTestFile("document.pdf", "application/pdf", "PDF content");

// Upload file
await uploadFile(user, "Upload document", file);
```

### Work with Dropdowns

```typescript
await selectDropdownOption(user, "Country", "United States");
await selectDropdownOption(user, /language/i, /english/i);
```

### Assertions

```typescript
// Check field values
expectFieldValue(/email/i, "test@example.com");
expectFieldEmpty(/password/i);

// Wait for button state
await waitForButtonState("Submit", "enabled");
await waitForButtonState("Submit", "disabled");

// Check error messages
expect(hasErrorMessage("Invalid email")).toBe(true);
```

## Complete Example: Login Test with Utilities

### Before (Without Utilities)

```typescript
describe("Login Form", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it("allows user to login", async () => {
    const user = userEvent.setup();

    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ success: true }),
    } as Response);

    render(<LoginForm />);

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

  it("shows error on invalid credentials", async () => {
    const user = userEvent.setup();

    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: "Invalid credentials" }),
    } as Response);

    render(<LoginForm />);

    await user.type(screen.getByLabelText(/email/i), "wrong@example.com");
    await user.type(screen.getByLabelText(/password/i), "wrongpass");

    const submitButton = screen.getByRole("button", { name: /log in/i });
    await user.click(submitButton);

    await waitFor(() => {
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument();
    });
  });
});
```

### After (With Utilities)

```typescript
import {
  render,
  screen,
  userEvent,
  setupFetchSpy,
  cleanupFetchSpy,
  mockApiSuccess,
  mockUnauthorizedError,
  fillForm,
  submitForm,
  waitForText,
  waitForErrorMessage,
  expectRequest,
} from "@tests/setup/test-utils";

describe("Login Form", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = setupFetchSpy();
  });

  afterEach(() => {
    cleanupFetchSpy(fetchSpy);
  });

  it("allows user to login", async () => {
    const user = userEvent.setup();

    mockApiSuccess(fetchSpy, { success: true });

    render(<LoginForm />);

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

  it("shows error on invalid credentials", async () => {
    const user = userEvent.setup();

    mockUnauthorizedError(fetchSpy, "Invalid credentials");

    render(<LoginForm />);

    await fillForm(user, {
      Email: "wrong@example.com",
      Password: "wrongpass",
    });

    await submitForm(user, "Log In");

    await waitForErrorMessage(/invalid credentials/i);
  });
});
```

**Lines of code:**
- Before: ~60 lines
- After: ~40 lines
- **33% reduction** with better readability!

## Complete Example: CRUD Workflow with Utilities

```typescript
import {
  render,
  screen,
  userEvent,
  setupFetchSpy,
  cleanupFetchSpy,
  mockApiSuccess,
  mockServerError,
  mockSequentialResponses,
  fillFormByPlaceholder,
  clickButton,
  waitForText,
  waitForTextToDisappear,
  expectRequest,
  clearAndType,
} from "@tests/setup/test-utils";

describe("Item Manager CRUD", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = setupFetchSpy();
  });

  afterEach(() => {
    cleanupFetchSpy(fetchSpy);
  });

  it("completes full CRUD workflow", async () => {
    const user = userEvent.setup();

    // Setup sequential API responses
    mockSequentialResponses(fetchSpy, [
      { success: true, data: [] }, // Initial fetch
      { success: true, data: { id: 1, name: "Item 1" }, status: 201 }, // Create
      { success: true, data: { id: 1, name: "Updated Item" } }, // Update
      { success: true, data: {}, status: 204 }, // Delete
    ]);

    render(<ItemManager />);

    // Wait for initial load
    await waitForTextToDisappear(/loading/i);

    // CREATE
    await clickButton(user, "Add Item");
    await fillFormByPlaceholder(user, {
      "Item name": "Item 1",
    });
    await clickButton(user, "Create");

    await waitForText("Item created successfully");
    await waitForText("Item 1");

    // UPDATE
    await clickButton(user, "Edit");
    const nameInput = screen.getByDisplayValue("Item 1");
    await clearAndType(user, nameInput, "Updated Item");
    await clickButton(user, "Save");

    await waitForText("Item updated successfully");
    await waitForText("Updated Item");

    // DELETE
    await clickButton(user, "Delete");
    await clickButton(user, "Confirm");

    await waitForText("Item deleted successfully");
    await waitForTextToDisappear("Updated Item");

    // Verify all API calls
    expectRequest(fetchSpy, { url: "/api/items", method: "GET", callIndex: 0 });
    expectRequest(fetchSpy, { url: "/api/items", method: "POST", callIndex: 1 });
    expectRequest(fetchSpy, { url: "/api/items/1", method: "PATCH", callIndex: 2 });
    expectRequest(fetchSpy, { url: "/api/items/1", method: "DELETE", callIndex: 3 });
  });

  it("handles errors gracefully", async () => {
    const user = userEvent.setup();

    mockApiSuccess(fetchSpy, [{ id: 1, name: "Item 1" }]);

    render(<ItemManager />);

    await waitForText("Item 1");

    // Mock server error for update
    mockServerError(fetchSpy, "Database connection failed");

    await clickButton(user, "Edit");
    const nameInput = screen.getByDisplayValue("Item 1");
    await clearAndType(user, nameInput, "Updated");
    await clickButton(user, "Save");

    // Error message shown, original value retained
    await waitForErrorMessage("Database connection failed");
    expect(screen.getByText("Item 1")).toBeInTheDocument();
  });
});
```

## Benefits Summary

### Code Reduction
- **33-50% fewer lines** in typical tests
- Less boilerplate, more readable tests
- Focus on test logic, not setup

### Consistency
- Standardized patterns across all tests
- Easier onboarding for new developers
- Consistent error handling

### Maintainability
- Change implementation in one place
- Update all tests automatically
- Easier refactoring

### Readability
- Self-documenting function names
- Clear intent (`fillForm` vs. multiple `type` calls)
- Better test structure

## Best Practices

1. **Always use helpers when available**
   ```typescript
   // ✅ Good
   await fillForm(user, { Email: "test@example.com" });

   // ❌ Avoid
   await user.type(screen.getByLabelText(/email/i), "test@example.com");
   ```

2. **Import from test-utils**
   ```typescript
   // ✅ Good
   import { render, mockApiSuccess, fillForm } from "@tests/setup/test-utils";

   // ❌ Avoid
   import { render } from "@testing-library/react";
   import { mockApiSuccess } from "../setup/api-mocks";
   ```

3. **Use convenience helpers for common errors**
   ```typescript
   // ✅ Good
   mockUnauthorizedError(fetchSpy, "Invalid credentials");

   // ❌ Avoid
   mockApiError(fetchSpy, 401, "Invalid credentials");
   ```

4. **Chain helpers for complex workflows**
   ```typescript
   await fillForm(user, fields);
   await submitForm(user);
   await waitForSuccessMessage("Account created");
   ```

## Custom Helpers

Feel free to add your own helpers to `test-helpers.ts` or `api-mocks.ts`:

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

// In api-mocks.ts
export function mockAuthenticatedUser(fetchSpy: jest.SpyInstance, userData: any): void {
  mockApiSuccess(fetchSpy, userData);
}
```

Then use in tests:

```typescript
await loginAsUser(user, "test@example.com", "password123");
mockAuthenticatedUser(fetchSpy, { id: 1, name: "John Doe" });
```
