---
name: playwright-e2e-tests
description: Write and maintain Playwright end-to-end tests for the Onyx application. Use when creating new E2E tests, debugging test failures, adding test coverage, or when the user mentions Playwright, E2E tests, or browser testing.
---

# Playwright E2E Tests

## Project Layout

- **Tests**: `web/tests/e2e/` — organized by feature (`auth/`, `admin/`, `chat/`, `assistants/`, `connectors/`, `mcp/`)
- **Config**: `web/playwright.config.ts`
- **Utilities**: `web/tests/e2e/utils/`
- **Constants**: `web/tests/e2e/constants.js`
- **Global setup**: `web/tests/e2e/global-setup.ts`
- **Output**: `web/output/playwright/`

## Running Tests

```bash
# Run a specific test file
npx playwright test web/tests/e2e/chat/default_assistant.spec.ts

# Run a specific project
npx playwright test --project admin
npx playwright test --project exclusive
```

## Test Projects

| Project | Description | Parallelism |
|---------|-------------|-------------|
| `admin` | Standard tests (excludes `@exclusive`) | Parallel |
| `exclusive` | Serial, slower tests (tagged `@exclusive`) | 1 worker |

All tests use `admin_auth.json` storage state by default (pre-authenticated admin session).

## Authentication

Global setup (`global-setup.ts`) runs automatically before all tests and handles:

- Server readiness check (polls health endpoint, 60s timeout)
- Provisioning test users: admin, user, admin2 (idempotent)
- API login + saving storage states: `admin_auth.json`, `user_auth.json`, `admin2_auth.json`
- Promoting admin2 to admin role
- Ensuring a public LLM provider exists

Both test projects set `storageState: "admin_auth.json"`, so **every test starts pre-authenticated as admin with no login code needed**.

When a test needs a different user, use API-based login — never drive the login UI:

```typescript
import { loginAs } from "@tests/e2e/utils/auth";

await page.context().clearCookies();
await loginAs(page, "user");
await loginAs(page, "admin2");
```

## Test Structure

Tests start pre-authenticated as admin — navigate and test directly:

```typescript
import { test, expect } from "@playwright/test";

test.describe("Feature Name", () => {
  test("should describe expected behavior clearly", async ({ page }) => {
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
    // Already authenticated as admin — go straight to testing
  });
});
```

**User isolation** — tests that modify visible app state (creating assistants, sending chat messages, pinning items) should use `loginAsRandomUser` to get a fresh user per test. This prevents side effects from leaking into other parallel tests' screenshots and assertions:

```typescript
import { loginAsRandomUser } from "@tests/e2e/utils/auth";

test.beforeEach(async ({ page }) => {
  await page.context().clearCookies();
  await loginAsRandomUser(page);
});
```

Switch to admin only when privileged setup is needed (creating providers, configuring tools), then back to the isolated user for the actual test. See `chat/default_assistant.spec.ts` for a full example.

**API resource setup** — only when tests need to create backend resources (image gen configs, web search providers, MCP servers). Use `beforeAll`/`afterAll` with `OnyxApiClient` to create and clean up. See `chat/default_assistant.spec.ts` or `mcp/mcp_oauth_flow.spec.ts` for examples. This is uncommon (~4 of 37 test files).

## Key Utilities

### `OnyxApiClient` (`@tests/e2e/utils/onyxApiClient`)

Backend API client for test setup/teardown. Key methods:

- **Connectors**: `createFileConnector()`, `deleteCCPair()`, `pauseConnector()`
- **LLM Providers**: `ensurePublicProvider()`, `createRestrictedProvider()`, `setProviderAsDefault()`
- **Assistants**: `createAssistant()`, `deleteAssistant()`, `findAssistantByName()`
- **User Groups**: `createUserGroup()`, `deleteUserGroup()`, `setUserRole()`
- **Tools**: `createWebSearchProvider()`, `createImageGenerationConfig()`
- **Chat**: `createChatSession()`, `deleteChatSession()`

### `chatActions` (`@tests/e2e/utils/chatActions`)

- `sendMessage(page, message)` — sends a message and waits for AI response
- `startNewChat(page)` — clicks new-chat button and waits for intro
- `verifyDefaultAssistantIsChosen(page)` — checks Onyx logo is visible
- `verifyAssistantIsChosen(page, name)` — checks assistant name display
- `switchModel(page, modelName)` — switches LLM model via popover

### `visualRegression` (`@tests/e2e/utils/visualRegression`)

- `expectScreenshot(page, { name, mask?, hide?, fullPage? })`
- `expectElementScreenshot(locator, { name, mask?, hide? })`
- Controlled by `VISUAL_REGRESSION=true` env var

### `tools` (`@tests/e2e/utils/tools`)

- `TOOL_IDS` — centralized `data-testid` selectors for tool options
- `openActionManagement(page)` — opens the tool management popover

## Locator Strategy

Use locators in this priority order:

1. **`data-testid` / `aria-label`** — preferred for Onyx components
   ```typescript
   page.getByTestId("AppSidebar/new-session")
   page.getByLabel("admin-page-title")
   ```

2. **Role-based** — for standard HTML elements
   ```typescript
   page.getByRole("button", { name: "Create" })
   page.getByRole("dialog")
   ```

3. **Text/Label** — for visible text content
   ```typescript
   page.getByText("Custom Assistant")
   page.getByLabel("Email")
   ```

4. **CSS selectors** — last resort, only when above won't work
   ```typescript
   page.locator('input[name="name"]')
   page.locator("#onyx-chat-input-textarea")
   ```

**Never use** `page.locator` with complex CSS/XPath when a built-in locator works.

## Assertions

Use web-first assertions — they auto-retry until the condition is met:

```typescript
// Visibility
await expect(page.getByTestId("onyx-logo")).toBeVisible({ timeout: 5000 });

// Text content
await expect(page.getByTestId("assistant-name-display")).toHaveText("My Assistant");

// Count
await expect(page.locator('[data-testid="onyx-ai-message"]')).toHaveCount(2, { timeout: 30000 });

// URL
await expect(page).toHaveURL(/chatId=/);

// Element state
await expect(toggle).toBeChecked();
await expect(button).toBeEnabled();
```

**Never use** `assert` statements or hardcoded `page.waitForTimeout()`.

## Waiting Strategy

```typescript
// Wait for load state after navigation
await page.goto("/app");
await page.waitForLoadState("networkidle");

// Wait for specific element
await page.getByTestId("chat-intro").waitFor({ state: "visible", timeout: 10000 });

// Wait for URL change
await page.waitForFunction(() => window.location.href.includes("chatId="), null, { timeout: 10000 });

// Wait for network response
await page.waitForResponse(resp => resp.url().includes("/api/chat") && resp.status() === 200);
```

## Best Practices

1. **Descriptive test names** — clearly state expected behavior: `"should display greeting message when opening new chat"`
2. **API-first setup** — use `OnyxApiClient` for backend state; reserve UI interactions for the behavior under test
3. **User isolation** — tests that modify visible app state (sidebar, chat history) should use `loginAsRandomUser` for a fresh user per test, avoiding cross-test contamination. Always cleanup API-created resources in `afterAll`
4. **DRY helpers** — extract reusable logic into `utils/` with JSDoc comments
5. **No hardcoded waits** — use `waitFor`, `waitForLoadState`, or web-first assertions
6. **Parallel-safe** — no shared mutable state between tests; use unique names with timestamps (`\`test-${Date.now()}\``)
7. **Error context** — catch and re-throw with useful debug info (page text, URL, etc.)
8. **Tag slow tests** — mark serial/slow tests with `@exclusive` in the test title
9. **Visual regression** — use `expectScreenshot()` for UI consistency checks
10. **Minimal comments** — only comment to clarify non-obvious intent; never restate what the next line of code does
