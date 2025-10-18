# Integration Tests Only - Philosophy

## What We Test

This testing framework focuses **exclusively on integration tests** that validate complete user workflows.

### ✅ YES - Write Integration Tests For:

1. **Complete User Workflows**
   - Login → Redirect
   - Signup → Account created
   - Create → Edit → Delete (CRUD)
   - Search → Filter → Select
   - Upload → Process → Display

2. **Feature Workflows**
   - `EmailPasswordForm.test.tsx` - Login/Signup workflow
   - `InputPrompts.test.tsx` - CRUD workflow
   - `ConnectorSetup.test.tsx` - Multi-step form workflow (to be created)
   - `ChatInterface.test.tsx` - Chat conversation workflow (to be created)

### ❌ NO - Don't Write Tests For:

1. **Isolated Components**
   - ❌ `Button.test.tsx` - Just testing a button in isolation
   - ❌ `Input.test.tsx` - Just testing an input field
   - ❌ `Dropdown.test.tsx` - Just testing a dropdown
   - ❌ `Modal.test.tsx` - Just testing a modal

2. **Implementation Details**
   - ❌ CSS classes (`expect(button).toHaveClass("bg-red-800")`)
   - ❌ HTML attributes (`expect(button).toHaveAttribute("type", "submit")`)
   - ❌ Component props in isolation
   - ❌ Internal state

## Why Integration Tests Only?

### 1. Higher ROI
One integration test replaces dozens of unit tests:

```typescript
// ❌ Unit Test Approach (Low ROI)
// Would need 10+ separate files:
Button.test.tsx         // Tests button clicks
Input.test.tsx          // Tests typing
Form.test.tsx           // Tests form state
API.test.tsx            // Tests API calls
Validation.test.tsx     // Tests validation
ErrorMessage.test.tsx   // Tests error display
LoadingSpinner.test.tsx // Tests loading state
// ... etc

// ✅ Integration Test Approach (High ROI)
// One file tests entire workflow:
LoginForm.test.tsx      // Tests complete login workflow
```

### 2. Tests What Users Care About

Users don't care if a button has `type="submit"`. They care if the form submits correctly.

```typescript
// ❌ Unit Test (Low Value)
it("button has submit type", () => {
  render(<Button>Submit</Button>);
  expect(button).toHaveAttribute("type", "submit");
});

// ✅ Integration Test (High Value)
it("allows user to login successfully", async () => {
  render(<LoginForm />);
  await fillForm(user, { Email: "test@example.com", Password: "password" });
  await submitForm(user);
  expect(screen.getByText(/welcome/i)).toBeInTheDocument();
});
```

### 3. Catches Integration Bugs

Unit tests can't catch bugs where components don't work together:

```typescript
// ❌ Unit tests would pass:
Button.test.tsx ✅ // Button clicks work
Form.test.tsx ✅   // Form submission works
API.test.tsx ✅    // API calls work

// But integration would fail:
// Button doesn't actually trigger form submission due to event bubbling issue

// ✅ Integration test catches this:
LoginForm.test.tsx ❌ // Form doesn't submit when button is clicked
```

### 4. More Resilient to Refactoring

Integration tests don't break when you refactor components:

```typescript
// Scenario: You refactor Button to use a different CSS library

// ❌ Unit tests break:
expect(button).toHaveClass("btn-primary"); // ❌ Now it's "button--primary"

// ✅ Integration tests still pass:
await clickButton(user, "Submit");
expect(handleSubmit).toHaveBeenCalled(); // ✅ Still works
```

### 5. Less Maintenance

Fewer test files to maintain:

```
// ❌ Unit Test Approach
src/
  components/
    Button.test.tsx           ⬅️ Maintain
    Input.test.tsx            ⬅️ Maintain
    Form.test.tsx             ⬅️ Maintain
    Dropdown.test.tsx         ⬅️ Maintain
    Modal.test.tsx            ⬅️ Maintain
  // 50+ component test files to maintain

// ✅ Integration Test Approach
src/
  app/
    auth/
      login/
        EmailPasswordForm.test.tsx  ⬅️ Maintain
    chat/
      input-prompts/
        InputPrompts.test.tsx       ⬅️ Maintain
  // 5-10 integration test files to maintain
```

## Examples

### Integration Test Example 1: Login Workflow

```typescript
// ✅ web/src/app/auth/login/EmailPasswordForm.test.tsx

it("allows user to login with valid credentials", async () => {
  const user = userEvent.setup();

  mockApiSuccess(fetchSpy, { success: true });

  render(<EmailPasswordForm isSignup={false} />);

  // User fills form
  await fillForm(user, {
    Email: "test@example.com",
    Password: "password123",
  });

  // User submits
  await submitForm(user, "Log In");

  // API is called
  expectRequest(fetchSpy, {
    url: "/api/auth/login",
    method: "POST",
    body: { email: "test@example.com", password: "password123" },
  });

  // User is redirected
  expect(mockPush).toHaveBeenCalledWith("/");
});
```

**What this tests:**
- Form rendering ✅
- User typing into inputs ✅
- Form validation ✅
- Submit button click ✅
- API request ✅
- API response handling ✅
- Redirect on success ✅

**One test = 7 different pieces working together!**

### Integration Test Example 2: CRUD Workflow

```typescript
// ✅ web/src/app/chat/input-prompts/InputPrompts.test.tsx

it("user can create, edit, and delete prompts in sequence", async () => {
  const user = userEvent.setup();

  mockSequentialResponses(fetchSpy, [
    { success: true, data: [] },                          // GET
    { success: true, data: { id: 1, name: "New" } },      // POST
    { success: true, data: { id: 1, name: "Updated" } },  // PATCH
    { success: true, data: {}, status: 204 },             // DELETE
  ]);

  render(<InputPrompts />);

  // CREATE
  await clickButton(user, "Add");
  await fillForm(user, { Name: "New Prompt" });
  await submitForm(user, "Create");
  await waitForSuccessMessage("Created");

  // UPDATE
  await clickButton(user, "Edit");
  await fillForm(user, { Name: "Updated Prompt" });
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

**What this tests:**
- List rendering ✅
- Create form ✅
- Edit form ✅
- Delete confirmation ✅
- 4 API calls ✅
- UI updates after each operation ✅
- Success messages ✅

**One test = Complete CRUD workflow!**

## File Structure

```
web/
  src/
    app/
      auth/
        login/
          EmailPasswordForm.tsx
          EmailPasswordForm.test.tsx      ✅ Integration test
      chat/
        input-prompts/
          InputPrompts.tsx
          InputPrompts.test.tsx            ✅ Integration test
      admin/
        connectors/
          ConnectorSetup.tsx
          ConnectorSetup.test.tsx          ✅ Integration test (to create)
    components/
      Button.tsx                           ⛔ No Button.test.tsx
      Input.tsx                            ⛔ No Input.test.tsx
      Dropdown.tsx                         ⛔ No Dropdown.test.tsx
      ui/
        button.tsx                         ⛔ No button.test.tsx
        input.tsx                          ⛔ No input.test.tsx
```

## When to Write a Test

### ✅ Write a Test When:
- You have a complete user workflow to test
- The workflow involves multiple components working together
- The workflow makes API calls
- The workflow has multiple steps
- Users would actually do this in the app

### ❌ Don't Write a Test When:
- You just created a new UI component
- You want to test a component in isolation
- You want to test CSS or styling
- You want to test internal component state
- It's just a presentational component

## How to Test Components

### Component Testing Strategy

If you want confidence that a component works, test it **within an integration test**:

```typescript
// ❌ Don't do this:
// src/components/Button.test.tsx
it("button can be clicked", () => {
  const handleClick = jest.fn();
  render(<Button onClick={handleClick}>Click me</Button>);
  await user.click(button);
  expect(handleClick).toHaveBeenCalled();
});

// ✅ Do this instead:
// src/app/auth/login/EmailPasswordForm.test.tsx
it("allows user to login", async () => {
  render(<EmailPasswordForm />);
  await fillForm(user, { Email: "test@example.com", Password: "pass" });
  await submitForm(user, "Log In"); // <-- This tests Button works
  expect(mockPush).toHaveBeenCalledWith("/");
});
```

**The Button is tested, just not in isolation!**

### Visual Testing

For visual appearance (colors, spacing, responsive design), use visual regression testing:
- **Chromatic** (Storybook + visual diffs)
- **Percy**
- **Playwright screenshots**

Don't test visual appearance in Jest tests.

## Summary

### Integration Tests Only Approach

**What we do:**
- ✅ Test complete user workflows
- ✅ Test multiple components working together
- ✅ Test API interactions
- ✅ Test real user scenarios
- ✅ 2 integration tests per major feature

**What we don't do:**
- ❌ Test isolated components
- ❌ Test implementation details
- ❌ Test CSS classes
- ❌ Create 50+ component test files

**Result:**
- Higher confidence
- Less maintenance
- Fewer brittle tests
- Better coverage of real bugs
- Faster test execution (fewer tests)

**Motto:** Test what users do, not what components are.
