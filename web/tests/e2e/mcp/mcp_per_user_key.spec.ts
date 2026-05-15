import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { loginAs, apiLogin } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import {
  startMcpPerUserKeyServer,
  McpServerProcess,
} from "@tests/e2e/utils/mcpServer";

// API keys baked into run_mcp_server_per_user_key.py. The script's middleware
// also requires every /mcp/* request to carry a non-empty `X-Username` header
// when launched with `--require-header X-Username`, which is exactly the
// scenario this spec exercises end-to-end.
const ADMIN_API_KEY =
  process.env.MCP_PER_USER_KEY_ADMIN_KEY ||
  "mcp_live-kid_alice_001-S3cr3tAlice";
const BASIC_USER_API_KEY =
  process.env.MCP_PER_USER_KEY_USER_KEY || "mcp_live-kid_bob_001-S3cr3tBob";
const ADMIN_USERNAME = "admin-pw";
const BASIC_USERNAME = "basic-pw";
const REQUIRED_USERNAME_HEADER = "X-Username";
const DEFAULT_PORT = Number(process.env.MCP_PER_USER_KEY_TEST_PORT || "8007");
const MCP_PER_USER_KEY_TEST_URL = process.env.MCP_PER_USER_KEY_TEST_URL;

async function ensureOnboardingComplete(page: Page): Promise<void> {
  await page.evaluate(async () => {
    try {
      await fetch("/api/user/personalization", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ name: "Playwright User" }),
      });
    } catch {
      // ignore personalization failures
    }
  });

  await page.reload();
  await page.waitForLoadState("networkidle");
}

async function scrollToBottom(page: Page): Promise<void> {
  try {
    await page.evaluate(() => {
      window.scrollTo(0, document.body.scrollHeight);
    });
    await page.waitForTimeout(200);
  } catch {
    // ignore scrolling failures
  }
}

test.describe("MCP per-user API key auth (multi-field template)", () => {
  test.describe.configure({ mode: "serial" });

  let serverProcess: McpServerProcess | null = null;
  let serverId: number | null = null;
  let serverName: string;
  let serverUrl: string;
  let basicUserEmail: string;
  let basicUserPassword: string;
  let createdProviderId: number | null = null;

  test.beforeAll(async ({ browser }) => {
    if (MCP_PER_USER_KEY_TEST_URL) {
      serverUrl = MCP_PER_USER_KEY_TEST_URL;
      console.log(
        `[test-setup] Using dockerized MCP per-user key server at ${serverUrl}`
      );
    } else {
      serverProcess = await startMcpPerUserKeyServer({
        port: DEFAULT_PORT,
        requiredHeaders: [REQUIRED_USERNAME_HEADER],
      });
      serverUrl = `http://${serverProcess.address.host}:${serverProcess.address.port}/mcp`;
      console.log(
        `[test-setup] MCP per-user key server started locally at ${serverUrl}`
      );
    }

    serverName = `PW Per-User Key Server ${Date.now()}`;

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminPage = await adminContext.newPage();
    const adminClient = new OnyxApiClient(adminPage.request);

    createdProviderId = await adminClient.ensurePublicProvider();

    try {
      const existingServers = await adminClient.listMcpServers();
      for (const server of existingServers) {
        if (server.server_url === serverUrl) {
          await adminClient.deleteMcpServer(server.id);
        }
      }
    } catch (error) {
      console.warn("Failed to cleanup existing MCP servers", error);
    }

    basicUserEmail = `pw-per-user-key-${Date.now()}@example.com`;
    basicUserPassword = "BasicUserPass123!";
    await adminClient.registerUser(basicUserEmail, basicUserPassword);

    await adminContext.close();
  });

  test.afterAll(async ({ browser }) => {
    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminPage = await adminContext.newPage();
    const adminClient = new OnyxApiClient(adminPage.request);

    if (createdProviderId !== null) {
      await adminClient.deleteProvider(createdProviderId);
    }
    if (serverId) {
      await adminClient.deleteMcpServer(serverId);
    }

    await adminContext.close();

    if (serverProcess) {
      await serverProcess.stop();
    }
  });

  test("Admin configures per-user MCP server with two required template fields", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    await page.goto("/admin/actions/mcp");
    await page.waitForURL("**/admin/actions/mcp**");

    // Open the Add MCP Server modal and fill basic info
    await page.getByRole("button", { name: /Add MCP Server/i }).click();
    await page.waitForTimeout(500);

    await page.locator("input#name").fill(serverName);
    await page
      .locator("textarea#description")
      .fill("Test per-user multi-field API key MCP server");
    await page.locator("input#server_url").fill(serverUrl);

    const createServerResponsePromise = page.waitForResponse((resp) => {
      try {
        const url = new URL(resp.url());
        return (
          url.pathname === "/api/admin/mcp/server" &&
          resp.request().method() === "POST" &&
          resp.ok()
        );
      } catch {
        return false;
      }
    });
    await page.getByRole("button", { name: "Add Server" }).click();
    const createServerResponse = await createServerResponsePromise;
    const createdServer = (await createServerResponse.json()) as {
      id?: number;
    };
    expect(createdServer.id).toBeTruthy();
    serverId = Number(createdServer.id);
    expect(serverId).toBeGreaterThan(0);

    // Auth modal opens automatically after server creation.
    await page.waitForTimeout(500);

    // Switch auth method to API Key (default is OAuth).
    const authMethodSelect = page.getByTestId("mcp-auth-method-select");
    await authMethodSelect.click();
    await page.getByRole("option", { name: "API Key" }).click();
    await page.waitForTimeout(300);

    // Per-user tab is the default for API Key, but click it explicitly so the
    // test fails loudly if that default ever changes.
    const perUserTab = page.getByRole("tab", {
      name: /Individual Key.*Per User/i,
    });
    await expect(perUserTab).toBeVisible({ timeout: 5000 });
    await perUserTab.click();
    await page.waitForTimeout(200);

    // The headers section is rendered by InputKeyValue, which exposes a
    // role="group" wrapper named "<keyTitle> and <valueTitle> pairs" and gives
    // each input an aria-label of "<keyPlaceholder|"Key"> <index+1>" /
    // "<valuePlaceholder|"Value"> <index+1>". PerUserAuthConfig doesn't pass
    // placeholders, so the row 1 inputs end up as "Key 1" / "Value 1" rather
    // than the visible column titles. Scope to the group so other "Key N"
    // labels elsewhere on the page can't collide.
    const headerGroup = page.getByRole("group", {
      name: /Header Name and Header Value pairs/i,
    });

    // Header row 1 is pre-populated with "Authorization" / "Bearer {api_key}"
    // by PerUserAuthConfig's initialization effect; we just need to confirm
    // and add row 2.
    const firstHeaderName = headerGroup.getByLabel("Key 1");
    const firstHeaderValue = headerGroup.getByLabel("Value 1");
    await expect(firstHeaderName).toHaveValue("Authorization");
    await expect(firstHeaderValue).toHaveValue("Bearer {api_key}");

    // Add a second header row for the X-Username placeholder. The button's
    // accessible name is "Add Header Name and Header Value pair" (built from
    // the column titles), so the regex matches via the "Add Header" prefix.
    const addHeaderButton = headerGroup.getByRole("button", {
      name: /Add Header Name and Header Value pair/i,
    });
    await addHeaderButton.click();

    const secondHeaderName = headerGroup.getByLabel("Key 2");
    const secondHeaderValue = headerGroup.getByLabel("Value 2");
    await expect(secondHeaderName).toBeVisible({ timeout: 5000 });
    await secondHeaderName.fill(REQUIRED_USERNAME_HEADER);
    await secondHeaderValue.fill("{username}");

    // The "Only for your own account" section should reveal once placeholders
    // are detected. Fill the admin's own credentials.
    const adminApiKeyInput = page.locator(
      'input[name="user_credentials.api_key"]'
    );
    const adminUsernameInput = page.locator(
      'input[name="user_credentials.username"]'
    );
    await expect(adminApiKeyInput).toBeVisible({ timeout: 5000 });
    await expect(adminUsernameInput).toBeVisible({ timeout: 5000 });
    await adminApiKeyInput.fill(ADMIN_API_KEY);
    await adminUsernameInput.fill(ADMIN_USERNAME);

    // Save the server. The upsert call hits POST /api/admin/mcp/servers/create
    // (not the singular /server endpoint that creates the bare record) and the
    // backend validates admin's creds against the running mock server during
    // this call, so a failure here means the substitution path or the mock
    // middleware is broken. We watch for the response so the assertion below
    // doesn't race the credential roundtrip.
    const upsertResponsePromise = page.waitForResponse(
      (resp) =>
        resp.url().endsWith("/api/admin/mcp/servers/create") &&
        resp.request().method() === "POST"
    );

    const connectButton = page.getByTestId("mcp-auth-connect-button");
    await expect(connectButton).toBeVisible({ timeout: 5000 });
    await expect(connectButton).toBeEnabled({ timeout: 5000 });
    await connectButton.click();
    const upsertResponse = await upsertResponsePromise;
    expect(upsertResponse.ok()).toBeTruthy();

    // Non-OAuth flow closes the modal in-place and triggers a tools fetch via
    // onTriggerFetchTools (no hard navigation). Verify we land back on the
    // MCP admin page with the server card visible and tools loadable.
    await expect(
      page.getByText(serverName, { exact: false }).first()
    ).toBeVisible({ timeout: 20000 });

    const refreshButton = page.getByRole("button", { name: "Refresh tools" });
    await expect(refreshButton).toBeVisible({ timeout: 10000 });
    await refreshButton.click();

    await expect(page.getByText("No tools available")).not.toBeVisible({
      timeout: 15000,
    });
  });

  test("Admin attaches the MCP server to the default agent", async ({
    page,
  }) => {
    test.skip(!serverId, "MCP server must be created first");

    await page.context().clearCookies();
    await loginAs(page, "admin");

    await page.goto("/admin/configuration/chat-preferences");
    await page.waitForURL("**/admin/configuration/chat-preferences**");

    await expect(page.locator('[aria-label="admin-page-title"]')).toBeVisible({
      timeout: 10000,
    });

    await scrollToBottom(page);

    const serverCard = page
      .locator(".opal-card-expandable")
      .filter({ hasText: serverName })
      .first();
    await expect(serverCard).toBeVisible({ timeout: 10000 });
    await serverCard.scrollIntoViewIfNeeded();

    const serverSwitch = serverCard.getByRole("switch").first();
    await expect(serverSwitch).toBeVisible({ timeout: 5000 });

    const serverState = await serverSwitch.getAttribute("aria-checked");
    if (serverState !== "true") {
      await serverSwitch.click();
      await expect(page.getByText("Tools updated").first()).toBeVisible({
        timeout: 10000,
      });
    }
  });

  test("Basic user is prompted for every template field and can authenticate", async ({
    page,
  }) => {
    test.skip(!serverId, "MCP server must be configured first");
    test.skip(!basicUserEmail, "Basic user must be created first");

    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);

    await page.goto("/app");
    await page.waitForURL("**/app**");
    await ensureOnboardingComplete(page);

    const actionsButton = page.getByTestId("action-management-toggle");
    await expect(actionsButton).toBeVisible({ timeout: 10000 });
    await actionsButton.click();

    const popover = page.locator('[data-testid="tool-options"]');
    await expect(popover).toBeVisible({ timeout: 5000 });

    const serverLineItem = popover
      .locator(".group\\/LineItem")
      .filter({ hasText: serverName })
      .first();
    await expect(serverLineItem).toBeVisible({ timeout: 10000 });

    // Clicking the line item before authenticating opens the auth modal
    // (per-user, API_TOKEN, not yet authenticated).
    await serverLineItem.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 5000 });
    await expect(dialog.getByText(/Enter Credentials/i)).toBeVisible({
      timeout: 5000,
    });

    // === The actual regression check ===
    // Both required fields must be rendered as inputs. Before the
    // `required_fields` persistence fix, only `api_key` was shown and the
    // user could submit without filling `username`, leaving the literal
    // `{username}` in the X-Username header sent to the upstream server.
    const apiKeyField = dialog.locator("input#api_key");
    const usernameField = dialog.locator("input#username");
    await expect(apiKeyField).toBeVisible({ timeout: 5000 });
    await expect(usernameField).toBeVisible({ timeout: 5000 });

    // The save button stays disabled until both fields are non-empty.
    const saveButton = dialog.getByRole("button", {
      name: /Save Credentials/i,
    });
    await expect(saveButton).toBeVisible({ timeout: 5000 });
    await expect(saveButton).toBeDisabled();

    await apiKeyField.fill(BASIC_USER_API_KEY);
    await expect(saveButton).toBeDisabled();

    await usernameField.fill(BASIC_USERNAME);
    await expect(saveButton).toBeEnabled({ timeout: 5000 });

    const credentialsResponsePromise = page.waitForResponse((resp) => {
      try {
        const url = new URL(resp.url());
        return (
          url.pathname === "/api/mcp/user-credentials" &&
          resp.request().method() === "POST"
        );
      } catch {
        return false;
      }
    });
    await saveButton.click();
    const credentialsResponse = await credentialsResponsePromise;
    expect(credentialsResponse.ok()).toBeTruthy();

    // The actions popover closes when the auth modal opens (Radix focus
    // semantics), so after the modal closes there's no popover to re-acquire
    // the line item from. Reopen it explicitly.
    await expect(dialog).not.toBeVisible({ timeout: 10000 });

    await actionsButton.click();
    const reopenedPopover = page.locator('[data-testid="tool-options"]');
    await expect(reopenedPopover).toBeVisible({ timeout: 5000 });

    // Now that the user is authenticated, clicking the line item should drill
    // into the tool list view (mcpView) rather than reopening the auth modal.
    const refreshedServerLineItem = reopenedPopover
      .locator(".group\\/LineItem")
      .filter({ hasText: serverName })
      .first();
    await expect(refreshedServerLineItem).toBeVisible({ timeout: 10000 });
    await refreshedServerLineItem.click();
    await expect(
      reopenedPopover.getByText(/(Enable|Disable) All/i).first()
    ).toBeVisible({ timeout: 10000 });
  });

  test("Re-authenticate row exposes the multi-field modal with the same gating", async ({
    page,
  }) => {
    test.skip(!serverId, "MCP server must be configured first");
    test.skip(!basicUserEmail, "Basic user must be created first");

    await page.context().clearCookies();
    await apiLogin(page, basicUserEmail, basicUserPassword);

    await page.goto("/app");
    await page.waitForURL("**/app**");
    await ensureOnboardingComplete(page);

    const actionsButton = page.getByTestId("action-management-toggle");
    await expect(actionsButton).toBeVisible({ timeout: 10000 });
    await actionsButton.click();

    const popover = page.locator('[data-testid="tool-options"]');
    await expect(popover).toBeVisible({ timeout: 5000 });

    const serverLineItem = popover
      .locator(".group\\/LineItem")
      .filter({ hasText: serverName })
      .first();
    await expect(serverLineItem).toBeVisible({ timeout: 10000 });

    // Already authenticated from the previous test, so this drills into the
    // tool list rather than opening the auth modal.
    await serverLineItem.click();
    await expect(
      popover.getByText(/(Enable|Disable) All/i).first()
    ).toBeVisible({ timeout: 10000 });

    // The Re-Authenticate row is rendered as a footer line item inside the
    // drilled-in tool list view (see `mcpFooter` in ActionsPopover/index.tsx).
    const reauthRow = popover
      .locator(".group\\/LineItem")
      .filter({ hasText: /Re-Authenticate/i })
      .first();
    await expect(reauthRow).toBeVisible({ timeout: 5000 });
    await reauthRow.click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 5000 });
    await expect(dialog.getByText(/Manage Credentials/i)).toBeVisible({
      timeout: 5000,
    });

    // Both fields still rendered; gating still enforces "all-or-nothing".
    const apiKeyField = dialog.locator("input#api_key");
    const usernameField = dialog.locator("input#username");
    await expect(apiKeyField).toBeVisible({ timeout: 5000 });
    await expect(usernameField).toBeVisible({ timeout: 5000 });

    const updateButton = dialog.getByRole("button", {
      name: /Update Credentials/i,
    });
    await expect(updateButton).toBeVisible({ timeout: 5000 });

    await apiKeyField.fill("");
    await usernameField.fill("");
    await expect(updateButton).toBeDisabled();

    await apiKeyField.fill(BASIC_USER_API_KEY);
    await expect(updateButton).toBeDisabled();

    await usernameField.fill(BASIC_USERNAME);
    await expect(updateButton).toBeEnabled({ timeout: 5000 });
  });
});
