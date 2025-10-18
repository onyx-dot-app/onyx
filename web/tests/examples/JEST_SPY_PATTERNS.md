# Using jest.spyOn for API Request Validation

## Why Use jest.spyOn?

**Benefits over `global.fetch = jest.fn()`**:
1. ✅ More explicit and readable
2. ✅ Easier to restore original implementation
3. ✅ Better TypeScript support
4. ✅ Can spy on methods without replacing them entirely
5. ✅ Cleaner test cleanup with `mockRestore()`

## Basic Pattern

### Old Way (Direct Mock)
```typescript
beforeEach(() => {
  global.fetch = jest.fn();
});

// Mock response
(global.fetch as jest.Mock).mockResolvedValueOnce({
  ok: true,
  json: async () => ({ data: "value" }),
});
```

### New Way (Spy)
```typescript
let fetchSpy: jest.SpyInstance;

beforeEach(() => {
  fetchSpy = jest.spyOn(global, "fetch");
});

afterEach(() => {
  fetchSpy.mockRestore();
});

// Mock response
fetchSpy.mockResolvedValueOnce({
  ok: true,
  json: async () => ({ data: "value" }),
});
```

## Complete Example: Login Workflow

```typescript
describe("Email/Password Login with Spy", () => {
  let fetchSpy: jest.SpyInstance;
  const mockPush = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();

    // Create spy on global fetch
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    // Restore original implementation
    fetchSpy.mockRestore();
  });

  it("sends correct login request", async () => {
    const user = userEvent.setup();

    // Mock successful response
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ success: true }),
    } as Response);

    render(<EmailPasswordForm isSignup={false} />);

    // User fills form
    await user.type(screen.getByLabelText(/email/i), "test@example.com");
    await user.type(screen.getByLabelText(/password/i), "SecurePass123");

    // User submits
    await user.click(screen.getByRole("button", { name: /log in/i }));

    // Validate request was made correctly
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(1);
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/auth/login",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email: "test@example.com",
            password: "SecurePass123",
          }),
        })
      );
    });

    // Validate response was handled
    expect(mockPush).toHaveBeenCalledWith("/");
  });

  it("handles error responses correctly", async () => {
    const user = userEvent.setup();

    // Mock error response
    fetchSpy.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({
        detail: "Invalid email or password"
      }),
    } as Response);

    render(<EmailPasswordForm isSignup={false} />);

    await user.type(screen.getByLabelText(/email/i), "wrong@example.com");
    await user.type(screen.getByLabelText(/password/i), "wrongpass");
    await user.click(screen.getByRole("button", { name: /log in/i }));

    // Verify error message shown
    await waitFor(() => {
      expect(screen.getByText(/invalid email or password/i)).toBeInTheDocument();
    });

    // Verify no redirect happened
    expect(mockPush).not.toHaveBeenCalled();

    // Verify request details
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/auth/login",
      expect.objectContaining({
        method: "POST",
      })
    );
  });
});
```

## Advanced Patterns

### 1. Inspecting Request Body

```typescript
it("sends correctly formatted request body", async () => {
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ id: 123 }),
  } as Response);

  // ... user interactions ...

  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalled();
  });

  // Get the actual call arguments
  const [url, options] = fetchSpy.mock.calls[0];

  expect(url).toBe("/api/users");
  expect(options.method).toBe("POST");

  // Parse and validate body
  const requestBody = JSON.parse(options.body);
  expect(requestBody).toEqual({
    name: "John Doe",
    email: "john@example.com",
    role: "admin",
  });

  // Validate specific fields
  expect(requestBody.email).toMatch(/@example\.com$/);
});
```

### 2. Multiple Sequential Requests

```typescript
it("handles create, then fetch, then update workflow", async () => {
  const user = userEvent.setup();

  // Mock create response
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ id: 1, name: "Item 1" }),
  } as Response);

  // Mock fetch response
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => [{ id: 1, name: "Item 1" }],
  } as Response);

  // Mock update response
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ id: 1, name: "Updated Item" }),
  } as Response);

  render(<ItemManager />);

  // CREATE
  await user.click(screen.getByRole("button", { name: /add/i }));
  await user.type(screen.getByLabelText(/name/i), "Item 1");
  await user.click(screen.getByRole("button", { name: /create/i }));

  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  // Verify CREATE request
  expect(fetchSpy.mock.calls[0][0]).toBe("/api/items");
  expect(fetchSpy.mock.calls[0][1].method).toBe("POST");

  // UPDATE
  await user.click(screen.getByRole("button", { name: /edit/i }));
  await user.clear(screen.getByLabelText(/name/i));
  await user.type(screen.getByLabelText(/name/i), "Updated Item");
  await user.click(screen.getByRole("button", { name: /save/i }));

  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalledTimes(3); // Create + Fetch + Update
  });

  // Verify UPDATE request (3rd call)
  expect(fetchSpy.mock.calls[2][0]).toBe("/api/items/1");
  expect(fetchSpy.mock.calls[2][1].method).toBe("PATCH");

  const updateBody = JSON.parse(fetchSpy.mock.calls[2][1].body);
  expect(updateBody.name).toBe("Updated Item");
});
```

### 3. Validating Headers

```typescript
it("sends authentication headers", async () => {
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ data: "protected" }),
  } as Response);

  render(<ProtectedComponent />);

  await user.click(screen.getByRole("button", { name: /fetch data/i }));

  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalled();
  });

  const [_, options] = fetchSpy.mock.calls[0];

  // Validate headers
  expect(options.headers).toEqual(
    expect.objectContaining({
      "Content-Type": "application/json",
      Authorization: expect.stringMatching(/^Bearer /),
    })
  );

  // Or validate specific header
  expect(options.headers.Authorization).toBe("Bearer mock-token");
});
```

### 4. Validating Query Parameters

```typescript
it("sends correct query parameters", async () => {
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ results: [] }),
  } as Response);

  render(<SearchComponent />);

  await user.type(screen.getByLabelText(/search/i), "test query");
  await user.click(screen.getByRole("button", { name: /search/i }));

  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalled();
  });

  const [url] = fetchSpy.mock.calls[0];

  // Parse URL and check query params
  const urlObj = new URL(url, "http://localhost");
  expect(urlObj.pathname).toBe("/api/search");
  expect(urlObj.searchParams.get("q")).toBe("test query");
  expect(urlObj.searchParams.get("limit")).toBe("10");

  // Or use string matching
  expect(url).toContain("q=test+query");
  expect(url).toContain("limit=10");
});
```

### 5. Testing File Uploads

```typescript
it("uploads file with correct FormData", async () => {
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ url: "/uploads/file.pdf" }),
  } as Response);

  const file = new File(["content"], "document.pdf", { type: "application/pdf" });

  render(<FileUploader />);

  const input = screen.getByLabelText(/choose file/i);
  await user.upload(input, file);
  await user.click(screen.getByRole("button", { name: /upload/i }));

  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalled();
  });

  const [url, options] = fetchSpy.mock.calls[0];

  expect(url).toBe("/api/upload");
  expect(options.method).toBe("POST");

  // Verify FormData was sent
  expect(options.body).toBeInstanceOf(FormData);

  const formData = options.body as FormData;
  const uploadedFile = formData.get("file");
  expect(uploadedFile).toBeInstanceOf(File);
  expect((uploadedFile as File).name).toBe("document.pdf");
});
```

### 6. Testing Network Errors

```typescript
it("handles network errors gracefully", async () => {
  // Spy rejects to simulate network failure
  fetchSpy.mockRejectedValueOnce(new Error("Network request failed"));

  render(<DataFetcher />);

  await user.click(screen.getByRole("button", { name: /load data/i }));

  // Error message shown
  await waitFor(() => {
    expect(screen.getByText(/network error/i)).toBeInTheDocument();
  });

  // Verify fetch was attempted
  expect(fetchSpy).toHaveBeenCalledWith("/api/data");
});
```

### 7. Spying on Response Methods

```typescript
it("validates response is parsed correctly", async () => {
  const mockJson = jest.fn().mockResolvedValue({ id: 1, name: "Test" });

  fetchSpy.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: mockJson,
  } as unknown as Response);

  render(<Component />);

  await user.click(screen.getByRole("button", { name: /fetch/i }));

  await waitFor(() => {
    expect(fetchSpy).toHaveBeenCalled();
  });

  // Verify json() was called to parse response
  await waitFor(() => {
    expect(mockJson).toHaveBeenCalled();
  });

  // Verify data was used in UI
  expect(screen.getByText("Test")).toBeInTheDocument();
});
```

### 8. Testing Retry Logic

```typescript
it("retries failed request up to 3 times", async () => {
  // First 2 attempts fail, 3rd succeeds
  fetchSpy
    .mockRejectedValueOnce(new Error("Network error"))
    .mockRejectedValueOnce(new Error("Network error"))
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ data: "success" }),
    } as Response);

  render(<RetryComponent />);

  await user.click(screen.getByRole("button", { name: /fetch/i }));

  // Wait for all retries
  await waitFor(
    () => {
      expect(fetchSpy).toHaveBeenCalledTimes(3);
    },
    { timeout: 5000 }
  );

  // All calls to same endpoint
  expect(fetchSpy.mock.calls[0][0]).toBe("/api/data");
  expect(fetchSpy.mock.calls[1][0]).toBe("/api/data");
  expect(fetchSpy.mock.calls[2][0]).toBe("/api/data");

  // Success message shown after retry succeeds
  expect(screen.getByText(/success/i)).toBeInTheDocument();
});
```

## Complete Integration Test Example with Spy

```typescript
/**
 * @jest-environment jsdom
 */
import React from "react";
import { render, screen, userEvent, waitFor } from "@tests/setup/test-utils";
import InputPrompts from "./InputPrompts";

const mockPush = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

describe("Input Prompts CRUD with Spy", () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    fetchSpy = jest.spyOn(global, "fetch");
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it("creates new prompt with correct request", async () => {
    const user = userEvent.setup();

    // Mock initial fetch (get list)
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [],
    } as Response);

    render(<InputPrompts />);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(1);
      expect(fetchSpy).toHaveBeenCalledWith("/api/input_prompt");
    });

    // User clicks add button
    await user.click(screen.getByRole("button", { name: /add/i }));

    // User fills form
    await user.type(
      screen.getByPlaceholderText(/prompt shortcut/i),
      "Summarize"
    );
    await user.type(
      screen.getByPlaceholderText(/actual prompt/i),
      "Summarize this document"
    );

    // Mock create response
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: async () => ({
        id: 1,
        prompt: "Summarize",
        content: "Summarize this document",
        is_public: false,
        active: true,
      }),
    } as Response);

    // User submits
    await user.click(screen.getByRole("button", { name: /create/i }));

    // Validate CREATE request
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(2); // Initial fetch + create
    });

    const [url, options] = fetchSpy.mock.calls[1]; // Second call

    expect(url).toBe("/api/input_prompt");
    expect(options.method).toBe("POST");
    expect(options.headers).toEqual({ "Content-Type": "application/json" });

    const requestBody = JSON.parse(options.body);
    expect(requestBody).toEqual({
      prompt: "Summarize",
      content: "Summarize this document",
      is_public: false,
    });

    // Validate UI updated
    expect(screen.getByText("Summarize")).toBeInTheDocument();
    expect(screen.getByText(/summarize this document/i)).toBeInTheDocument();
  });

  it("updates prompt with correct PATCH request", async () => {
    const user = userEvent.setup();

    const existingPrompt = {
      id: 1,
      prompt: "Translate",
      content: "Translate to Spanish",
      is_public: false,
      active: true,
    };

    // Mock initial fetch
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [existingPrompt],
    } as Response);

    render(<InputPrompts />);

    await waitFor(() => {
      expect(screen.getByText("Translate")).toBeInTheDocument();
    });

    // User edits
    await user.click(screen.getByRole("button", { name: /edit/i }));

    const contentInput = screen.getByDisplayValue(/translate to spanish/i);
    await user.clear(contentInput);
    await user.type(contentInput, "Translate to French");

    // Mock update response
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => ({}),
    } as Response);

    await user.click(screen.getByRole("button", { name: /save/i }));

    // Validate UPDATE request
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(2);
    });

    const [url, options] = fetchSpy.mock.calls[1];

    expect(url).toBe("/api/input_prompt/1");
    expect(options.method).toBe("PATCH");

    const updateBody = JSON.parse(options.body);
    expect(updateBody).toEqual({
      prompt: "Translate",
      content: "Translate to French",
      active: true,
    });

    // Validate UI updated
    expect(screen.getByText(/translate to french/i)).toBeInTheDocument();
  });

  it("deletes prompt with correct DELETE request", async () => {
    const user = userEvent.setup();

    // Mock initial fetch
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 1,
          prompt: "Remove Me",
          content: "Content",
          is_public: false,
          active: true,
        },
      ],
    } as Response);

    render(<InputPrompts />);

    await waitFor(() => {
      expect(screen.getByText("Remove Me")).toBeInTheDocument();
    });

    // Mock delete response
    fetchSpy.mockResolvedValueOnce({
      ok: true,
      status: 204,
    } as Response);

    // User deletes
    await user.click(screen.getByRole("button", { name: /delete/i }));

    // Validate DELETE request
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(2);
    });

    const [url, options] = fetchSpy.mock.calls[1];

    expect(url).toBe("/api/input_prompt/1");
    expect(options.method).toBe("DELETE");

    // Validate item removed from UI
    expect(screen.queryByText("Remove Me")).not.toBeInTheDocument();
  });
});
```

## Comparison: Mock vs Spy

### Using Direct Mock
```typescript
// Setup
global.fetch = jest.fn();

// Usage
(global.fetch as jest.Mock).mockResolvedValueOnce({...});

// Assertion
expect(global.fetch).toHaveBeenCalledWith(...);

// Cleanup
// No automatic cleanup
```

### Using Spy
```typescript
// Setup
const fetchSpy = jest.spyOn(global, "fetch");

// Usage
fetchSpy.mockResolvedValueOnce({...});

// Assertion
expect(fetchSpy).toHaveBeenCalledWith(...);

// Cleanup
fetchSpy.mockRestore(); // Restores original
```

## Best Practices

1. **Always Restore**: Use `afterEach` to restore spies
   ```typescript
   afterEach(() => {
     fetchSpy.mockRestore();
   });
   ```

2. **Type Safety**: Cast responses as `Response` type
   ```typescript
   fetchSpy.mockResolvedValueOnce({
     ok: true,
     json: async () => ({ data: "value" }),
   } as Response);
   ```

3. **Validate Request Details**: Check URL, method, headers, body
   ```typescript
   const [url, options] = fetchSpy.mock.calls[0];
   expect(url).toBe("/api/endpoint");
   expect(options.method).toBe("POST");
   expect(JSON.parse(options.body)).toEqual({ key: "value" });
   ```

4. **Test Both Success and Failure**: Mock different status codes
   ```typescript
   // Success
   fetchSpy.mockResolvedValueOnce({ ok: true, status: 200 } as Response);

   // Client error
   fetchSpy.mockResolvedValueOnce({ ok: false, status: 400 } as Response);

   // Network error
   fetchSpy.mockRejectedValueOnce(new Error("Network error"));
   ```

5. **Use Descriptive Test Names**: Explain what request/response is being validated
   ```typescript
   it("sends POST request with user credentials to /api/auth/login", ...)
   it("handles 401 Unauthorized response by showing error message", ...)
   ```

## Summary

Using `jest.spyOn` provides:
- ✅ Better readability and explicit intent
- ✅ Automatic cleanup with `mockRestore()`
- ✅ Access to `mock.calls` for detailed inspection
- ✅ Better TypeScript support
- ✅ More flexible - can spy on any object method

This makes your integration tests more maintainable and easier to understand!
