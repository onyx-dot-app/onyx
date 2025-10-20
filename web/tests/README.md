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
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import MyComponent from "./MyComponent";

test("user can submit the form", async () => {
  const user = setupUser();
  const fetchSpy = jest.spyOn(global, "fetch");

  fetchSpy.mockResolvedValueOnce({
    ok: true,
    json: async () => ({ success: true }),
  } as Response);

  render(<MyComponent />);

  await user.type(screen.getByPlaceholderText(/email/i), "user@example.com");
  await user.click(screen.getByRole("button", { name: /submit/i }));

  await waitFor(() => {
    expect(screen.getByText(/success/i)).toBeInTheDocument();
  });

  fetchSpy.mockRestore();
});
```

**Important**: Always use `setupUser()` instead of `userEvent.setup()` - it automatically wraps all interactions in `act()` to prevent React warnings.

### Handling Async State Updates

When components update state asynchronously, use the correct query methods:

**✅ Good - Use `findBy` for elements that appear after async updates:**
```typescript
await user.click(createButton);
expect(await screen.findByRole("textbox")).toBeInTheDocument();
```

**✅ Good - Use `waitFor` for complex assertions:**
```typescript
await waitFor(() => {
  expect(screen.getByText("Updated")).toBeInTheDocument();
  expect(screen.getByText("Count: 5")).toBeInTheDocument();
});
```

**❌ Bad - Don't use `getBy` immediately after state changes:**
```typescript
await user.click(button);
expect(screen.getByText("Updated")).toBeInTheDocument(); // May fail!
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
