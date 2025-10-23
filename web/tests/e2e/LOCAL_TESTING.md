# Local Testing Guide

## Skipping Authentication for Local Tests

When testing Playwright tests locally, you can skip the authentication step if you're already logged in to the application in your browser.

### Quick Start

Set the `SKIP_AUTH` environment variable to `true` when running your tests:

```bash
SKIP_AUTH=true npx playwright test web/tests/e2e/assistants/create_and_edit_assistant.spec.ts --headed
```

### How It Works

The `SKIP_AUTH` flag modifies the behavior of authentication functions in `web/tests/e2e/utils/auth.ts`:

- **`loginAsRandomUser(page)`**: Skips the signup flow entirely
- **`loginAs(page, userType)`**: Skips the login flow for admin/user accounts

### Prerequisites

Before running tests with `SKIP_AUTH=true`, ensure:

1. Your local Onyx instance is running at `http://localhost:3000`
2. You're already logged in to the application (the session cookies exist)
3. Your browser cookies are persisted in Playwright's context

### Important Notes

- **Session Persistence**: Playwright tests run in isolated browser contexts. By default, they won't share cookies with your regular browser session.
- **Use Cases**: 
  - ✅ Fast iteration when developing/debugging specific test scenarios
  - ✅ Testing UI interactions without waiting for auth flows
  - ❌ NOT recommended for CI/CD pipelines
  - ❌ NOT recommended for comprehensive test runs

### Alternative: Persistent Context (Advanced)

For a more robust solution that shares your actual browser session, you can use Playwright's persistent context:

```typescript
import { chromium } from '@playwright/test';

const userDataDir = '/path/to/your/chrome/profile';
const context = await chromium.launchPersistentContext(userDataDir);
const page = await context.newPage();
```

### Debugging

If you're having issues with authentication:

1. Check that your session is active: Visit `http://localhost:3000` in your browser
2. Verify Onyx services are running: Check `backend/log/` for service logs
3. Look at Playwright's console output for auth-related messages

### Running Tests Without SKIP_AUTH

For normal test execution (with authentication):

```bash
npx playwright test web/tests/e2e/assistants/create_and_edit_assistant.spec.ts
```

This will create a new random user account and test the full authentication flow.

