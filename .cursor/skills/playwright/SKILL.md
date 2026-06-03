---
name: playwright-e2e-tests
description: Write and maintain Playwright end-to-end tests for the Onyx application. Use when creating new E2E tests, debugging test failures, adding test coverage, or when the user mentions Playwright, E2E tests, or browser testing.
---

# Playwright E2E Tests

## Project Layout

- **Tests**: `web/tests/e2e/` — organized by feature (`auth/`, `admin/`, `chat/`, `assistants/`, `connectors/`, `mcp/`)
- **Config**: `web/playwright.config.ts`
- **Utilities**: `web/tests/e2e/utils/`
- **Constants**: `web/tests/e2e/constants.ts`
- **Global setup**: `web/tests/e2e/global-setup.ts`
- **Output**: `web/output/playwright/`

## Imports

Always use absolute imports with the `@tests/e2e/` prefix — never relative paths (`../`, `../../`). The alias is defined in `web/tsconfig.json` and resolves to `web/tests/`.

```typescript
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { TEST_ADMIN_CREDENTIALS } from "@tests/e2e/constants";
```

All new files should be `.ts`, not `.js`.

## Environment

`playwright.config.ts` honors a `BASE_URL` override (default `http://localhost:3000`). Global setup
registers/logs in users over `/api/auth/*`, so `BASE_URL` must point at a server that proxies `/api`
to the backend. Pick it based on how the app is running:

- **Dev servers (`ods web dev` + `ods backend api`):** use the default `http://localhost:3000` — no
  override needed. In dev, `next dev` proxies `/api/*` to the backend itself (the dev-only route
  handler `web/src/app/api/[...path]/route.ts`), so both the UI and `/api` live on `:3000`.
- **Prebuilt / production compose stack:** production builds disable that in-app `/api` proxy, so
  `/api` is fronted by the `nginx` sibling container — run with `BASE_URL=http://nginx`.

Readiness check: `curl -s -o /dev/null -w '%{http_code}' http://localhost:3000/api/auth/type` → `200` (swap in `http://nginx` when targeting the compose stack).

Other bootstrap notes:
- The devcontainer image bakes in Playwright's OS deps + Node, but **not** the Chromium browser binary. If a run fails with a missing-browser error, install it once: `bunx playwright install chromium`.
- Run commands from the `web/` directory; `global-setup.ts` writes auth-state files (`admin_auth.json`, …) to the cwd. It's idempotent, so setup is fast.
- `web/.vscode/.env` may be **absent** — `dotenv` skips it silently (fine for most tests). One exception: `tests/e2e/mcp/mcp_oauth_flow.spec.ts` **throws at import** without `MCP_OAUTH_*` vars, which also breaks a whole-suite `--list`. Scope runs to specific files/dirs to avoid it.

## Running Tests

```bash
cd web   # from the repo root

# Run a specific test file
# (default BASE_URL=http://localhost:3000 works with the dev servers)
bunx playwright test tests/e2e/chat/default_assistant.spec.ts

# Narrow to a single test by title (fast smoke check)
bunx playwright test tests/e2e/chat/welcome_page.spec.ts \
  -g "chat input is visible and focusable" --project admin

# Run a specific project
bunx playwright test --project admin
bunx playwright test --project exclusive

# Against the prebuilt compose stack (prod build) instead of the dev servers,
# front /api via nginx:
BASE_URL=http://nginx bunx playwright test --project admin
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
- Provisioning test users: admin, admin2, and a **pool of worker users** (`worker0@example.com` through `worker7@example.com`) (idempotent)
- API login + saving storage states: `admin_auth.json`, `admin2_auth.json`, and `worker{N}_auth.json` for each worker user
- Setting display name to `"worker"` for each worker user
- Promoting admin2 to admin role
- Ensuring a public LLM provider exists

Both test projects set `storageState: "admin_auth.json"`, so **every test starts pre-authenticated as admin with no login code needed**.

When a test needs a different user, use API-based login — never drive the login UI:

```typescript
import { loginAs } from "@tests/e2e/utils/auth";

await page.context().clearCookies();
await loginAs(page, "admin2");

// Log in as the worker-specific user (preferred for test isolation):
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
await page.context().clearCookies();
await loginAsWorkerUser(page, testInfo.workerIndex);
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

**User isolation** — tests that modify visible app state (creating assistants, sending chat messages, pinning items) should run as a **worker-specific user** and clean up resources in `afterAll`. Global setup provisions a pool of worker users (`worker0@example.com` through `worker7@example.com`). `loginAsWorkerUser` maps `testInfo.workerIndex` to a pool slot via modulo, so retry workers (which get incrementing indices beyond the pool size) safely reuse existing users. This ensures parallel workers never share user state, keeps usernames deterministic for screenshots, and avoids cross-contamination:

```typescript
import { test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";

test.beforeEach(async ({ page }, testInfo) => {
  await page.context().clearCookies();
  await loginAsWorkerUser(page, testInfo.workerIndex);
});
```

If the test requires admin privileges *and* modifies visible state, use `"admin2"` instead — it's a pre-provisioned admin account that keeps the primary `"admin"` clean for other parallel tests. Switch to `"admin"` only for privileged setup (creating providers, configuring tools), then back to the worker user for the actual test. See `chat/default_assistant.spec.ts` for a full example.

`loginAsRandomUser` exists for the rare case where the test requires a brand-new user (e.g. onboarding flows). Avoid it elsewhere — it produces non-deterministic usernames that complicate screenshots.

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

### `theme` (`@tests/e2e/utils/theme`)

- `THEMES` — `["light", "dark"] as const` array for iterating over both themes
- `setThemeBeforeNavigation(page, theme)` — sets `next-themes` theme via `localStorage` before navigation

When tests need light/dark screenshots, loop over `THEMES` at the `test.describe` level and call `setThemeBeforeNavigation` in `beforeEach` **before** any `page.goto()`. Include the theme in screenshot names. See `admin/admin_pages.spec.ts` or `chat/chat_message_rendering.spec.ts` for examples:

```typescript
import { THEMES, setThemeBeforeNavigation } from "@tests/e2e/utils/theme";

for (const theme of THEMES) {
  test.describe(`Feature (${theme} mode)`, () => {
    test.beforeEach(async ({ page }) => {
      await setThemeBeforeNavigation(page, theme);
    });

    test("renders correctly", async ({ page }) => {
      await page.goto("/app");
      await expectScreenshot(page, { name: `feature-${theme}` });
    });
  });
}
```

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
3. **User isolation** — tests that modify visible app state (sidebar, chat history) should run as the worker-specific user via `loginAsWorkerUser(page, testInfo.workerIndex)` (not admin) and clean up resources in `afterAll`. Each parallel worker gets its own user, preventing cross-contamination. Reserve `loginAsRandomUser` for flows that require a brand-new user (e.g. onboarding)
4. **DRY helpers** — extract reusable logic into `utils/` with JSDoc comments
5. **No hardcoded waits** — use `waitFor`, `waitForLoadState`, or web-first assertions
6. **Parallel-safe** — no shared mutable state between tests. Prefer static, human-readable names (e.g. `"E2E-CMD Chat 1"`) and clean up resources by ID in `afterAll`. This keeps screenshots deterministic and avoids needing to mask/hide dynamic text. Only fall back to timestamps (`\`test-${Date.now()}\``) when resources cannot be reliably cleaned up or when name collisions across parallel workers would cause functional failures
7. **Error context** — catch and re-throw with useful debug info (page text, URL, etc.)
8. **Tag slow tests** — mark serial/slow tests with `@exclusive` in the test title
9. **Visual regression** — use `expectScreenshot()` for UI consistency checks
10. **Minimal comments** — only comment to clarify non-obvious intent; never restate what the next line of code does
