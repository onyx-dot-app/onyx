# React Integration Testing

Integration tests for Onyx web application using Jest and React Testing Library.

## Running Tests

```bash
# Run all tests
npm test

# Run specific test file
npm test -- EmailPasswordForm.test

# Run without coverage
npm test -- --no-coverage
```

## Writing Tests

### Test Structure

Tests are co-located with source files:

```
src/app/auth/login/
├── EmailPasswordForm.tsx
└── EmailPasswordForm.test.tsx
```

### Basic Pattern

```typescript
import { render, screen, userEvent, waitFor } from "@tests/setup/test-utils";
import MyComponent from "./MyComponent";

test("user can submit the form", async () => {
  const user = userEvent.setup();

  // Mock API response
  const fetchSpy = jest.spyOn(global, "fetch");
  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ success: true }),
  } as Response);

  render(<MyComponent />);

  // Fill form
  await user.type(screen.getByPlaceholderText(/email/i), "user@example.com");

  // Submit
  await user.click(screen.getByRole("button", { name: /submit/i }));

  // Verify UI behavior after response
  await waitFor(() => {
    expect(screen.getByText(/success/i)).toBeInTheDocument();
  });

  fetchSpy.mockRestore();
});
```

## Testing Philosophy

**Test UI behavior, not implementation:**
- ✅ Verify success/error messages appear
- ✅ Check redirects happen (window.location.href)
- ✅ Validate form state changes
- ✅ Use accessible queries (getByRole, getByLabelText)

**Minimal mocking:**
- Only mock what's necessary (UserProvider, markdown packages)
- Use jest.spyOn(fetch) for API calls
- Avoid mocking application logic

## Examples

See existing tests:
- `src/app/auth/login/EmailPasswordForm.test.tsx` - Login/signup workflows
- `src/app/chat/input-prompts/InputPrompts.test.tsx` - CRUD operations
- `src/app/admin/configuration/llm/CustomLLMProviderUpdateForm.test.tsx` - Complex forms

## Mocks

Only essential mocks are configured in `tests/setup/__mocks__/`:
- `UserProvider` - Removes auth requirement for tests
- `react-markdown` / `remark-gfm` - ESM compatibility

See `tests/setup/__mocks__/README.md` for details.
