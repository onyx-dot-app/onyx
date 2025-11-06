import { test, expect } from "@chromatic-com/playwright";
import type { Page, Browser } from "@playwright/test";
import {
  loginAs,
  loginAsRandomUser,
  loginWithCredentials,
} from "../utils/auth";
import { OnyxApiClient } from "../utils/onyxApiClient";
import { startMcpOauthServer, McpServerProcess } from "../utils/mcpServer";

const REQUIRED_ENV_VARS = [
  "MCP_TEST_CLIENT_ID",
  "MCP_TEST_CLIENT_SECRET",
  "MCP_OAUTH_TEST_USERNAME",
  "MCP_OAUTH_TEST_PASSWORD",
];

const missingEnvVars = REQUIRED_ENV_VARS.filter(
  (envVar) => !process.env[envVar]
);

test.skip(
  missingEnvVars.length > 0,
  `Missing required environment variables for MCP OAuth tests: ${missingEnvVars.join(
    ", "
  )}`
);

const MCP_SERVER_URL =
  process.env.MCP_TEST_SERVER_URL || "http://127.0.0.1:8004/mcp";
const CLIENT_ID = process.env.MCP_TEST_CLIENT_ID!;
const CLIENT_SECRET = process.env.MCP_TEST_CLIENT_SECRET!;
const OAUTH_USERNAME = process.env.MCP_OAUTH_TEST_USERNAME!;
const OAUTH_PASSWORD = process.env.MCP_OAUTH_TEST_PASSWORD!;
const APP_BASE_URL = process.env.MCP_TEST_APP_BASE || "http://localhost:3000";
const APP_HOST = new URL(APP_BASE_URL).host;

type Credentials = {
  email: string;
  password: string;
};

type FlowArtifacts = {
  serverId: number;
  serverName: string;
  assistantId: number;
  assistantName: string;
  toolName: string;
};

const DEFAULT_USERNAME_SELECTORS = [
  'input[name="username"]',
  "#okta-signin-username",
  'input[name="email"]',
  'input[type="email"]',
  "#username",
  'input[name="user"]',
];

const DEFAULT_PASSWORD_SELECTORS = [
  'input[name="password"]',
  "#okta-signin-password",
  'input[type="password"]',
  "#password",
];

const DEFAULT_SUBMIT_SELECTORS = [
  'button[type="submit"]',
  'input[type="submit"]',
  'button:has-text("Sign in")',
  'button:has-text("Log in")',
  'button:has-text("Continue")',
];

const DEFAULT_NEXT_SELECTORS = [
  'button:has-text("Next")',
  'button:has-text("Continue")',
  'input[type="submit"][value="Next"]',
];

const DEFAULT_CONSENT_SELECTORS = [
  'button:has-text("Allow")',
  'button:has-text("Authorize")',
  'button:has-text("Accept")',
  'button:has-text("Grant")',
];

const TOOL_NAMES = {
  admin: "tool_0",
  curator: "tool_1",
};

const TOOL_RUN_TIMEOUT_MS = Number(
  process.env.MCP_TEST_TOOL_TIMEOUT_MS || "90000"
);

function parseSelectorList(
  value: string | undefined,
  defaults: string[]
): string[] {
  if (!value) return defaults;
  return value
    .split(",")
    .map((selector) => selector.trim())
    .filter(Boolean);
}

async function fillFirstVisible(
  page: Page,
  selectors: string[],
  value: string
): Promise<boolean> {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    const count = await locator.count();
    if (count === 0) {
      continue;
    }
    try {
      await locator.waitFor({ state: "visible", timeout: 3000 });
      const existing = await locator
        .inputValue()
        .catch(() => "")
        .then((val) => val ?? "");
      if (existing !== value) {
        await locator.fill(value);
      }
      return true;
    } catch (err) {
      continue;
    }
  }
  return false;
}

async function clickFirstVisible(
  page: Page,
  selectors: string[],
  options: { optional?: boolean } = {}
): Promise<boolean> {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    const count = await locator.count();
    if (count === 0) continue;
    try {
      await locator.waitFor({ state: "visible", timeout: 3000 });
      await locator.click();
      return true;
    } catch (err) {
      if (!options.optional) {
        throw err;
      }
    }
  }
  return false;
}

async function performIdpLogin(page: Page): Promise<void> {
  const usernameSelectors = parseSelectorList(
    process.env.MCP_OAUTH_TEST_USERNAME_SELECTOR,
    DEFAULT_USERNAME_SELECTORS
  );
  const passwordSelectors = parseSelectorList(
    process.env.MCP_OAUTH_TEST_PASSWORD_SELECTOR,
    DEFAULT_PASSWORD_SELECTORS
  );
  const submitSelectors = parseSelectorList(
    process.env.MCP_OAUTH_TEST_SUBMIT_SELECTOR,
    DEFAULT_SUBMIT_SELECTORS
  );
  const nextSelectors = parseSelectorList(
    process.env.MCP_OAUTH_TEST_NEXT_SELECTOR,
    DEFAULT_NEXT_SELECTORS
  );
  const consentSelectors = parseSelectorList(
    process.env.MCP_OAUTH_TEST_CONSENT_SELECTOR,
    DEFAULT_CONSENT_SELECTORS
  );

  await page
    .waitForLoadState("domcontentloaded", { timeout: 15000 })
    .catch(() => {});

  const usernameFilled = await fillFirstVisible(
    page,
    usernameSelectors,
    OAUTH_USERNAME
  );
  if (usernameFilled) {
    await clickFirstVisible(page, nextSelectors, { optional: true });
    await page.waitForTimeout(500);
  }

  await fillFirstVisible(page, passwordSelectors, OAUTH_PASSWORD);
  const clickedSubmit = await clickFirstVisible(page, submitSelectors, {
    optional: true,
  });
  if (!clickedSubmit) {
    // As a fallback, press Enter in the password field
    const passwordLocator = page.locator(passwordSelectors.join(",")).first();
    if ((await passwordLocator.count()) > 0) {
      await passwordLocator.press("Enter").catch(() => {});
    } else {
      await page.keyboard.press("Enter").catch(() => {});
    }
  }

  await page
    .waitForLoadState("networkidle", { timeout: 15000 })
    .catch(() => {});

  await clickFirstVisible(page, consentSelectors, { optional: true });
  await page
    .waitForLoadState("networkidle", { timeout: 15000 })
    .catch(() => {});
}

async function completeOauthFlow(
  page: Page,
  options: {
    expectReturnPathContains: string;
    confirmConnected?: () => Promise<void>;
  }
): Promise<void> {
  const returnSubstring = options.expectReturnPathContains;

  const isOnAppHost = (url: string) => {
    try {
      return new URL(url).host === APP_HOST;
    } catch {
      return false;
    }
  };

  // If we're already on the expected page, just run the confirmation step
  if (
    isOnAppHost(page.url()) &&
    page.url().includes(returnSubstring) &&
    options.confirmConnected
  ) {
    await options.confirmConnected();
    return;
  }

  if (!isOnAppHost(page.url())) {
    await performIdpLogin(page);
  }

  if (!page.url().includes("/mcp/oauth/callback")) {
    await page
      .waitForURL("**/mcp/oauth/callback**", { timeout: 60000 })
      .catch(() => {});
  }

  await page
    .waitForLoadState("networkidle", { timeout: 15000 })
    .catch(() => {});

  await page
    .waitForURL(`**${returnSubstring}**`, { timeout: 60000 })
    .catch(() => {});
  await page
    .waitForLoadState("networkidle", { timeout: 15000 })
    .catch(() => {});

  if (options.confirmConnected) {
    await options.confirmConnected();
  }
}

async function ensurePublicAssistant(page: Page) {
  const publicRow = page
    .locator("div.flex.items-center")
    .filter({ hasText: "Organization Public" })
    .first();
  const switchLocator = publicRow.locator('[role="switch"]').first();
  const state = await switchLocator.getAttribute("data-state");
  if (state !== "checked") {
    await switchLocator.click();
  }
}

async function selectMcpTools(
  page: Page,
  serverId: number,
  toolNames: string[]
) {
  const sectionLocator = page.getByTestId(`mcp-server-section-${serverId}`);
  const sectionExists = await sectionLocator.count();
  if (sectionExists === 0) {
    throw new Error(
      `MCP server section ${serverId} not found in assistant form`
    );
  }
  const toggleButton = page.getByTestId(`mcp-server-toggle-${serverId}`);
  const dataState = await toggleButton.getAttribute("aria-expanded");
  if (dataState === "false") {
    await toggleButton.click();
  }

  for (const toolName of toolNames) {
    const attributeLocator = sectionLocator.locator(
      `[data-tool-name="${toolName}"], [data-tool-display-name="${toolName}"]`
    );
    if ((await attributeLocator.count()) > 0) {
      await attributeLocator.first().check({ force: true });
      continue;
    }

    const labelLocator = sectionLocator.getByRole("checkbox", {
      name: new RegExp(toolName, "i"),
    });
    if ((await labelLocator.count()) > 0) {
      await labelLocator.first().check({ force: true });
      continue;
    }

    throw new Error(`Unable to locate MCP tool checkbox for ${toolName}`);
  }
}

async function forceToolInChat(page: Page, toolName: string) {
  await page.locator('[data-testid="action-management-toggle"]').click();
  const toolOption = page.getByTestId(`tool-option-${toolName}`).first();
  await expect(toolOption).toBeVisible({ timeout: 15000 });
  await toolOption.click();
  await page.keyboard.press("Escape").catch(() => {});
}

async function waitForToolResult(page: Page, toolName: string) {
  await expect(
    page.getByText(new RegExp(`${toolName}\\s+(running|completed)`, "i"))
  ).toBeVisible({ timeout: TOOL_RUN_TIMEOUT_MS });
  await expect(page.getByText(new RegExp(`Secret value`, "i"))).toBeVisible({
    timeout: TOOL_RUN_TIMEOUT_MS,
  });
}

async function reauthenticateFromChat(
  page: Page,
  serverName: string,
  returnSubstring: string
) {
  await page.locator('[data-testid="action-management-toggle"]').click();
  const serverLineItem = page
    .locator(`[data-mcp-server-name="${serverName}"]`)
    .first();
  await expect(serverLineItem).toBeVisible({ timeout: 15000 });
  await serverLineItem.click();

  const reauthItem = page.getByText("Re-Authenticate").first();
  await expect(reauthItem).toBeVisible({ timeout: 15000 });
  const navigationPromise = page
    .waitForNavigation({ waitUntil: "load" })
    .catch(() => null);
  await reauthItem.click();
  await navigationPromise;
  await completeOauthFlow(page, {
    expectReturnPathContains: returnSubstring,
  });
}

async function ensureServerVisibleInActions(page: Page, serverName: string) {
  await page.locator('[data-testid="action-management-toggle"]').click();
  const serverLineItem = page
    .locator(`[data-mcp-server-name="${serverName}"]`)
    .first();
  await expect(serverLineItem).toBeVisible({ timeout: 15000 });
  await page.keyboard.press("Escape").catch(() => {});
}

test.describe("MCP OAuth flows", () => {
  test.describe.configure({ mode: "serial" });

  let serverProcess: McpServerProcess | null = null;
  let adminArtifacts: FlowArtifacts | null = null;
  let curatorArtifacts: FlowArtifacts | null = null;
  let curatorCredentials: Credentials | null = null;
  let curatorTwoCredentials: Credentials | null = null;

  test.beforeAll(async ({ browser }) => {
    serverProcess = await startMcpOauthServer();

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminPage = await adminContext.newPage();
    const adminClient = new OnyxApiClient(adminPage);

    const curatorContext = await browser.newContext();
    const curatorPage = await curatorContext.newPage();
    curatorCredentials = await loginAsRandomUser(curatorPage);
    await adminClient.setUserRole(curatorCredentials.email, "curator");
    await curatorContext.close();

    const curatorTwoContext = await browser.newContext();
    const curatorTwoPage = await curatorTwoContext.newPage();
    curatorTwoCredentials = await loginAsRandomUser(curatorTwoPage);
    await adminClient.setUserRole(curatorTwoCredentials.email, "curator");
    await curatorTwoContext.close();

    await adminContext.close();
  });

  test.afterAll(async ({ browser }) => {
    if (serverProcess) {
      await serverProcess.stop();
    }

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminPage = await adminContext.newPage();
    const adminClient = new OnyxApiClient(adminPage);

    if (adminArtifacts?.assistantId) {
      await adminClient.deleteAssistant(adminArtifacts.assistantId);
    }
    if (adminArtifacts?.serverId) {
      await adminClient.deleteMcpServer(adminArtifacts.serverId);
    }

    if (curatorArtifacts?.assistantId) {
      await adminClient.deleteAssistant(curatorArtifacts.assistantId);
    }
    if (curatorArtifacts?.serverId) {
      await adminClient.deleteMcpServer(curatorArtifacts.serverId);
    }

    if (curatorCredentials) {
      await adminClient.setUserRole(curatorCredentials.email, "basic");
    }
    if (curatorTwoCredentials) {
      await adminClient.setUserRole(curatorTwoCredentials.email, "basic");
    }

    await adminContext.close();
  });

  test("Admin can configure OAuth MCP server and use tools end-to-end", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await loginAs(page, "admin");

    const serverName = `PW MCP Admin ${Date.now()}`;
    const assistantName = `PW Admin Assistant ${Date.now()}`;

    await page.goto("http://localhost:3000/admin/actions/edit-mcp");
    await page.waitForURL("**/admin/actions/edit-mcp**", { timeout: 15000 });

    await page.locator('input[name="name"]').fill(serverName);
    await page
      .locator('textarea[name="description"]')
      .fill("Playwright MCP OAuth server (admin)");
    await page.locator('input[name="server_url"]').fill(MCP_SERVER_URL);

    await page.getByTestId("auth-type-select").click();
    await page.getByRole("option", { name: "OAuth" }).click();

    await page.locator("#oauth_client_id").fill(CLIENT_ID);
    await page.locator("#oauth_client_secret").fill(CLIENT_SECRET);

    const connectButton = page.getByTestId("connect-oauth-button");
    const navPromise = page
      .waitForNavigation({ waitUntil: "load" })
      .catch(() => null);
    await connectButton.click();
    await navPromise;
    await completeOauthFlow(page, {
      expectReturnPathContains: "/admin/actions/edit-mcp",
      confirmConnected: async () => {
        await expect(page.getByTestId("connect-oauth-button")).toContainText(
          "OAuth Connected",
          { timeout: 15000 }
        );
      },
    });

    await page.getByRole("button", { name: "List Actions" }).click();
    await page.waitForURL("**listing_tools=true**", { timeout: 15000 });
    await expect(page.getByText("Available Tools")).toBeVisible({
      timeout: 15000,
    });

    const currentUrl = new URL(page.url());
    const serverIdParam = currentUrl.searchParams.get("server_id");
    if (!serverIdParam) {
      throw new Error("Expected server_id in URL after listing tools");
    }
    const serverId = Number(serverIdParam);
    if (Number.isNaN(serverId)) {
      throw new Error(
        `Invalid server_id parsed from URL: ${currentUrl.searchParams.get(
          "server_id"
        )}`
      );
    }

    await page
      .getByTestId(`tool-checkbox-${TOOL_NAMES.admin}`)
      .click({ force: true });

    await page
      .getByRole("button", { name: "Create MCP Server Actions" })
      .click();

    await page.waitForURL("**/admin/actions**", { timeout: 20000 });
    await expect(
      page.getByText(serverName, { exact: false }).first()
    ).toBeVisible({ timeout: 20000 });

    await page.goto("http://localhost:3000/admin/assistants/new");
    await page.waitForURL("**/admin/assistants/new**", { timeout: 15000 });

    await page.locator('input[name="name"]').fill(assistantName);
    await page
      .locator('textarea[name="system_prompt"]')
      .fill("Assist with MCP OAuth testing.");
    await page
      .locator('textarea[name="description"]')
      .fill("Playwright admin MCP assistant.");

    await page
      .getByRole("button", { name: /Advanced Options/i })
      .click()
      .catch(() => {});
    await ensurePublicAssistant(page);
    await selectMcpTools(page, serverId, [TOOL_NAMES.admin]);

    await page.getByRole("button", { name: "Create" }).click();
    await page.waitForURL(/\/chat\?assistantId=\d+/, { timeout: 20000 });

    const chatUrl = new URL(page.url());
    const assistantIdParam = chatUrl.searchParams.get("assistantId");
    if (!assistantIdParam) {
      throw new Error("Assistant ID missing from chat redirect URL");
    }
    const assistantId = Number(assistantIdParam);
    if (Number.isNaN(assistantId)) {
      throw new Error(`Invalid assistantId ${assistantIdParam}`);
    }

    await forceToolInChat(page, TOOL_NAMES.admin);
    await page.fill("#onyx-chat-input-textarea", "Test tool call");
    await page.keyboard.press("Enter");
    await waitForToolResult(page, TOOL_NAMES.admin);

    await reauthenticateFromChat(
      page,
      serverName,
      `/chat?assistantId=${assistantId}`
    );
    await forceToolInChat(page, TOOL_NAMES.admin);
    await page.fill("#onyx-chat-input-textarea", "Test tool call after reauth");
    await page.keyboard.press("Enter");
    await waitForToolResult(page, TOOL_NAMES.admin);

    await page.goto(
      `http://localhost:3000/admin/actions/edit-mcp?server_id=${serverId}`
    );
    await page.waitForURL("**listing_tools=true**", { timeout: 15000 });
    await expect(page.getByText("Available Tools")).toBeVisible({
      timeout: 15000,
    });
    await expect(
      page.getByTestId(`tool-checkbox-${TOOL_NAMES.admin}`)
    ).toHaveAttribute("data-state", "checked");

    adminArtifacts = {
      serverId,
      serverName,
      assistantId,
      assistantName,
      toolName: TOOL_NAMES.admin,
    };
  });

  test("Curator flow with access isolation", async ({ page, browser }) => {
    if (!curatorCredentials || !curatorTwoCredentials) {
      test.skip(true, "Curator credentials were not initialized");
    }

    await page.context().clearCookies();
    await loginWithCredentials(
      page,
      curatorCredentials!.email,
      curatorCredentials!.password
    );

    const serverName = `PW MCP Curator ${Date.now()}`;
    const assistantName = `PW Curator Assistant ${Date.now()}`;

    await page.goto("http://localhost:3000/admin/actions/edit-mcp");
    await page.waitForURL("**/admin/actions/edit-mcp**", { timeout: 15000 });

    await page.locator('input[name="name"]').fill(serverName);
    await page
      .locator('textarea[name="description"]')
      .fill("Playwright MCP OAuth server (curator)");
    await page.locator('input[name="server_url"]').fill(MCP_SERVER_URL);

    await page.getByTestId("auth-type-select").click();
    await page.getByRole("option", { name: "OAuth" }).click();

    await page.locator("#oauth_client_id").fill(CLIENT_ID);
    await page.locator("#oauth_client_secret").fill(CLIENT_SECRET);

    const connectButton = page.getByTestId("connect-oauth-button");
    const navPromise = page
      .waitForNavigation({ waitUntil: "load" })
      .catch(() => null);
    await connectButton.click();
    await navPromise;
    await completeOauthFlow(page, {
      expectReturnPathContains: "/admin/actions/edit-mcp",
      confirmConnected: async () => {
        await expect(page.getByTestId("connect-oauth-button")).toContainText(
          "OAuth Connected",
          { timeout: 15000 }
        );
      },
    });

    await page.getByRole("button", { name: "List Actions" }).click();
    await page.waitForURL("**listing_tools=true**", { timeout: 15000 });
    await expect(page.getByText("Available Tools")).toBeVisible({
      timeout: 15000,
    });

    const currentUrl = new URL(page.url());
    const serverIdParam = currentUrl.searchParams.get("server_id");
    if (!serverIdParam) {
      throw new Error("Expected server_id in URL after listing tools");
    }
    const serverId = Number(serverIdParam);
    if (Number.isNaN(serverId)) {
      throw new Error(`Invalid server_id ${serverIdParam}`);
    }

    await page
      .getByTestId(`tool-checkbox-${TOOL_NAMES.curator}`)
      .click({ force: true });

    await page
      .getByRole("button", { name: "Create MCP Server Actions" })
      .click();

    await page.waitForURL("**/admin/actions**", { timeout: 20000 });
    await expect(
      page.getByText(serverName, { exact: false }).first()
    ).toBeVisible({ timeout: 20000 });

    await page.goto("http://localhost:3000/admin/assistants/new");
    await page.waitForURL("**/admin/assistants/new**", { timeout: 15000 });

    await page.locator('input[name="name"]').fill(assistantName);
    await page
      .locator('textarea[name="system_prompt"]')
      .fill("Curator MCP OAuth assistant.");
    await page
      .locator('textarea[name="description"]')
      .fill("Playwright curator MCP assistant.");

    await page
      .getByRole("button", { name: /Advanced Options/i })
      .click()
      .catch(() => {});
    await ensurePublicAssistant(page);
    await selectMcpTools(page, serverId, [TOOL_NAMES.curator]);

    await page.getByRole("button", { name: "Create" }).click();
    await page.waitForURL(/\/chat\?assistantId=\d+/, { timeout: 20000 });

    const chatUrl = new URL(page.url());
    const assistantIdParam = chatUrl.searchParams.get("assistantId");
    if (!assistantIdParam) {
      throw new Error("Assistant ID missing from chat redirect URL");
    }
    const assistantId = Number(assistantIdParam);
    if (Number.isNaN(assistantId)) {
      throw new Error(`Invalid assistantId ${assistantIdParam}`);
    }

    await forceToolInChat(page, TOOL_NAMES.curator);
    await page.fill("#onyx-chat-input-textarea", "Curator tool call");
    await page.keyboard.press("Enter");
    await waitForToolResult(page, TOOL_NAMES.curator);

    await reauthenticateFromChat(
      page,
      serverName,
      `/chat?assistantId=${assistantId}`
    );
    await forceToolInChat(page, TOOL_NAMES.curator);
    await page.fill(
      "#onyx-chat-input-textarea",
      "Curator tool call post reauth"
    );
    await page.keyboard.press("Enter");
    await waitForToolResult(page, TOOL_NAMES.curator);

    curatorArtifacts = {
      serverId,
      serverName,
      assistantId,
      assistantName,
      toolName: TOOL_NAMES.curator,
    };

    // Verify isolation: second curator must not see first curator's server
    const curatorTwoContext = await browser.newContext();
    const curatorTwoPage = await curatorTwoContext.newPage();
    await loginWithCredentials(
      curatorTwoPage,
      curatorTwoCredentials!.email,
      curatorTwoCredentials!.password
    );
    await curatorTwoPage.goto("http://localhost:3000/admin/actions");
    const serverLocator = curatorTwoPage.getByText(serverName, {
      exact: false,
    });
    await expect(serverLocator).toHaveCount(0);
    await curatorTwoContext.close();
  });

  test("End user can authenticate and invoke MCP tools via chat", async ({
    page,
  }) => {
    test.skip(!adminArtifacts, "Admin flow must complete before user test");

    await page.context().clearCookies();
    await loginAs(page, "user");

    const assistantId = adminArtifacts!.assistantId;
    const serverName = adminArtifacts!.serverName;
    const toolName = adminArtifacts!.toolName;

    await page.goto(`http://localhost:3000/chat?assistantId=${assistantId}`, {
      waitUntil: "load",
    });
    await ensureServerVisibleInActions(page, serverName);

    await page.locator('[data-testid="action-management-toggle"]').click();
    const serverLineItem = page
      .locator(`[data-mcp-server-name="${serverName}"]`)
      .first();
    await expect(serverLineItem).toBeVisible({ timeout: 15000 });

    const navPromise = page
      .waitForNavigation({ waitUntil: "load" })
      .catch(() => null);
    await serverLineItem.click();
    await navPromise;
    await completeOauthFlow(page, {
      expectReturnPathContains: `/chat?assistantId=${assistantId}`,
    });

    await forceToolInChat(page, toolName);
    await page.fill("#onyx-chat-input-textarea", "User tool call");
    await page.keyboard.press("Enter");
    await waitForToolResult(page, toolName);
  });
});
