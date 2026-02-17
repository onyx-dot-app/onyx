import { test, expect } from "@playwright/test";
import type { Page, Locator } from "@playwright/test";
import { loginAs, apiLogin } from "../utils/auth";
import { OnyxApiClient } from "../utils/onyxApiClient";
import { startMcpOauthServer, McpServerProcess } from "../utils/mcpServer";
import { TEST_ADMIN_CREDENTIALS } from "../constants";
import { logPageState } from "../utils/pageStateLogger";
import {
  getPacketObjectsByType,
  sendMessageAndCaptureStreamPackets,
} from "../utils/chatStream";

const REQUIRED_ENV_VARS = [
  "MCP_OAUTH_CLIENT_ID",
  "MCP_OAUTH_CLIENT_SECRET",
  "MCP_OAUTH_ISSUER",
  "MCP_OAUTH_JWKS_URI",
  "MCP_OAUTH_USERNAME",
  "MCP_OAUTH_PASSWORD",
];

const missingEnvVars = REQUIRED_ENV_VARS.filter(
  (envVar) => !process.env[envVar]
);

if (missingEnvVars.length > 0) {
  throw new Error(
    `Missing required environment variables for MCP OAuth tests: ${missingEnvVars.join(
      ", "
    )}`
  );
}

const DEFAULT_MCP_SERVER_URL =
  process.env.MCP_TEST_SERVER_URL || "http://127.0.0.1:8004/mcp";
let runtimeMcpServerUrl = DEFAULT_MCP_SERVER_URL;
const CLIENT_ID = process.env.MCP_OAUTH_CLIENT_ID!;
const CLIENT_SECRET = process.env.MCP_OAUTH_CLIENT_SECRET!;
const IDP_USERNAME = process.env.MCP_OAUTH_USERNAME!;
const IDP_PASSWORD = process.env.MCP_OAUTH_PASSWORD!;
const APP_BASE_URL = process.env.MCP_TEST_APP_BASE || "http://localhost:3000";
const APP_HOST = new URL(APP_BASE_URL).host;
const IDP_HOST = new URL(process.env.MCP_OAUTH_ISSUER!).host;
const QUICK_CONFIRM_CONNECTED_TIMEOUT_MS = Number(
  process.env.MCP_OAUTH_QUICK_CONFIRM_TIMEOUT_MS || 2000
);
const POST_CLICK_URL_CHANGE_WAIT_MS = Number(
  process.env.MCP_OAUTH_POST_CLICK_URL_CHANGE_WAIT_MS || 5000
);
const MCP_OAUTH_FLOW_TEST_TIMEOUT_MS = Number(
  process.env.MCP_OAUTH_TEST_TIMEOUT_MS || 300_000
);

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
  toolId: number | null;
};

type StepLogger = (message: string) => void;

const DEFAULT_USERNAME_SELECTORS = [
  'input[name="identifier"]',
  "#identifier-input",
  'input[name="username"]',
  "#okta-signin-username",
  "#idp-discovery-username",
  'input[id="idp-discovery-username"]',
  'input[name="email"]',
  'input[type="email"]',
  "#username",
  'input[name="user"]',
];

const DEFAULT_PASSWORD_SELECTORS = [
  'input[name="credentials.passcode"]',
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
  'button:has-text("Verify")',
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

const SPEC_START_MS = Date.now();

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

function buildMcpServerUrl(baseUrl: string): string {
  const trimmed = baseUrl.replace(/\/+$/, "");
  return trimmed.endsWith("/mcp") ? trimmed : `${trimmed}/mcp`;
}

const logOauthEvent = (page: Page | null, message: string) => {
  const location = page ? ` url=${page.url()}` : "";
  console.log(`[mcp-oauth-test] ${message}${location}`);
};

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

async function clickAndWaitForPossibleUrlChange(
  page: Page,
  clickAction: () => Promise<void>,
  context: string
) {
  const startingUrl = page.url();
  const urlChangePromise = page
    .waitForURL(
      (url) => {
        const href = typeof url === "string" ? url : url.toString();
        return href !== startingUrl;
      },
      { timeout: POST_CLICK_URL_CHANGE_WAIT_MS }
    )
    .then(() => true)
    .catch(() => false);

  await clickAction();
  const changed = await urlChangePromise;
  if (changed) {
    logOauthEvent(page, `${context}: observed URL change after click`);
  } else {
    logOauthEvent(
      page,
      `${context}: no immediate URL change; continuing OAuth flow`
    );
  }
}

function createStepLogger(testName: string) {
  const start = Date.now();
  return (message: string) => {
    const elapsed = ((Date.now() - start) / 1000).toFixed(1);
    console.log(`[mcp-oauth-step][${testName}] ${message} (+${elapsed}s)`);
  };
}

const getToolName = (packetObject: Record<string, unknown>): string | null => {
  const value = packetObject.tool_name;
  return typeof value === "string" ? value : null;
};

async function verifyToolInvocationFromChat(
  page: Page,
  toolName: string,
  contextLabel: string,
  forcedToolId?: number | null
) {
  const prompt = [
    `Call the MCP tool "${toolName}" now.`,
    `Pass {"name":"playwright-${Date.now()}"} as the arguments.`,
    "Return the exact tool output.",
  ].join(" ");

  const packets = await sendMessageAndCaptureStreamPackets(page, prompt, {
    mockLlmResponse: JSON.stringify({
      name: toolName,
      arguments: { name: `playwright-${Date.now()}` },
    }),
    payloadOverrides:
      forcedToolId != null
        ? {
            forced_tool_id: forcedToolId,
            forced_tool_ids: [forcedToolId],
          }
        : undefined,
    waitForAiMessage: false,
  });
  const startPackets = getPacketObjectsByType(
    packets,
    "custom_tool_start"
  ).filter((packetObject) => getToolName(packetObject) === toolName);
  const deltaPackets = getPacketObjectsByType(
    packets,
    "custom_tool_delta"
  ).filter((packetObject) => getToolName(packetObject) === toolName);
  const debugPackets = getPacketObjectsByType(
    packets,
    "tool_call_debug"
  ).filter((packetObject) => getToolName(packetObject) === toolName);

  expect(startPackets.length).toBeGreaterThan(0);
  expect(deltaPackets.length).toBeGreaterThan(0);
  expect(debugPackets.length).toBeGreaterThan(0);

  console.log(
    `[mcp-oauth-test] ${contextLabel}: tool invocation packets received for ${toolName}`
  );
}

async function fetchMcpToolIdByName(
  page: Page,
  serverId: number,
  toolName: string,
  timeoutMs: number = 15_000
): Promise<number | null> {
  const start = Date.now();
  let visibleToolNames: string[] = [];

  while (Date.now() - start < timeoutMs) {
    const response = await page.request.get(
      `/api/admin/mcp/server/${serverId}/db-tools`
    );
    if (!response.ok()) {
      await page.waitForTimeout(500);
      continue;
    }

    const data = (await response.json()) as {
      tools?: Array<Record<string, unknown>>;
    };
    const tools = Array.isArray(data.tools) ? data.tools : [];
    visibleToolNames = tools
      .map((tool) => {
        const value =
          tool.name ??
          tool.display_name ??
          tool.in_code_tool_id ??
          tool.displayName;
        return typeof value === "string" ? value : "";
      })
      .filter(Boolean);

    const matchedTool = tools.find((tool) => {
      const candidates = [
        tool.name,
        tool.display_name,
        tool.in_code_tool_id,
        tool.displayName,
      ].filter((value): value is string => typeof value === "string");
      return candidates.includes(toolName);
    });
    if (matchedTool) {
      const id = matchedTool.id;
      if (typeof id === "number") {
        return id;
      }
      if (typeof id === "string") {
        const parsed = Number(id);
        if (!Number.isNaN(parsed)) {
          return parsed;
        }
      }
    }

    await page.waitForTimeout(500);
  }

  console.warn(
    `[mcp-oauth-test] Could not resolve tool id for ${toolName} on server ${serverId}. Visible tools: ${visibleToolNames.join(
      ", "
    )}`
  );
  return null;
}

async function logoutSession(page: Page, contextLabel: string) {
  try {
    const response = await page.request.post(`${APP_BASE_URL}/api/auth/logout`);
    const status = response.status();
    if (!response.ok() && status !== 401) {
      const body = await response.text();
      console.warn(
        `[mcp-oauth-test] ${contextLabel}: Logout returned ${status} - ${body}`
      );
    } else {
      console.log(
        `[mcp-oauth-test] ${contextLabel}: Logout request completed with status ${status}`
      );
    }
  } catch (error) {
    console.warn(
      `[mcp-oauth-test] ${contextLabel}: Logout request failed - ${String(
        error
      )}`
    );
  }
}

async function verifySessionUser(
  page: Page,
  expected: { email: string; role: string },
  contextLabel: string
) {
  const response = await page.request.get(`${APP_BASE_URL}/api/me`);
  const status = response.status();
  expect(response.ok()).toBeTruthy();
  const data = await response.json();
  expect(data.email).toBe(expected.email);
  expect(data.role).toBe(expected.role);
  console.log(
    `[mcp-oauth-test] ${contextLabel}: Verified session user ${data.email} (${data.role}) via /api/me (status ${status})`
  );
}

async function logPageStateWithTag(page: Page, context: string) {
  const elapsed = ((Date.now() - SPEC_START_MS) / 1000).toFixed(1);
  await logPageState(page, `${context} (+${elapsed}s)`, "[mcp-oauth-debug]");
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
      logOauthEvent(page, `Selector ${selector} not found`);
      continue;
    }
    logOauthEvent(page, `Filling first visible selector: ${selector}`);
    let isVisible = await locator.isVisible().catch(() => false);
    logOauthEvent(page, `Selector ${selector} is visible: ${isVisible}`);
    if (!isVisible) {
      logOauthEvent(
        page,
        `Selector ${selector} is not visible, waiting for it to be visible`
      );
      try {
        await locator.waitFor({ state: "visible", timeout: 500 });
        isVisible = true;
      } catch {
        continue;
      }
    }
    if (!isVisible) {
      continue;
    }
    const existing = await locator
      .inputValue()
      .catch(() => "")
      .then((val) => val ?? "");
    if (existing !== value) {
      await locator.fill(value);
    }
    return true;
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
    let isVisible = await locator.isVisible().catch(() => false);
    if (!isVisible) {
      try {
        await locator.waitFor({ state: "visible", timeout: 500 });
        isVisible = true;
      } catch {
        continue;
      }
    }
    try {
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

async function waitForAnySelector(
  page: Page,
  selectors: string[],
  options: { timeout?: number } = {}
): Promise<boolean> {
  const timeout = options.timeout ?? 5000;
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    for (const selector of selectors) {
      const locator = page.locator(selector).first();
      if ((await locator.count()) === 0) {
        continue;
      }
      try {
        if (await locator.isVisible()) {
          return true;
        }
      } catch {
        continue;
      }
    }
    await page.waitForTimeout(50);
  }
  return false;
}

async function scrollToBottom(page: Page): Promise<void> {
  try {
    await page.evaluate(() => {
      const section = document.querySelector(
        '[data-testid="available-tools-section"]'
      );
      if (section && "scrollIntoView" in section) {
        section.scrollIntoView({ behavior: "instant", block: "end" });
      } else {
        window.scrollTo(0, document.body.scrollHeight);
      }
    });
    await page.waitForTimeout(200);
  } catch {
    // ignore scrolling failures in test environment
  }
}

const isOnHost = (url: string, host: string): boolean => {
  try {
    return new URL(url).host === host;
  } catch {
    return false;
  }
};

const isOnAppHost = (url: string): boolean => isOnHost(url, APP_HOST);
const isOnIdpHost = (url: string): boolean => isOnHost(url, IDP_HOST);

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
  const passwordSelectorString = passwordSelectors.join(",");

  await page
    .waitForLoadState("domcontentloaded", { timeout: 1000 })
    .catch(() => {});

  logOauthEvent(page, "Attempting IdP login");
  await waitForAnySelector(page, usernameSelectors, { timeout: 1000 });
  logOauthEvent(page, `Username selectors: ${usernameSelectors.join(", ")}`);
  const usernameFilled = await fillFirstVisible(
    page,
    usernameSelectors,
    IDP_USERNAME
  );
  if (usernameFilled) {
    logOauthEvent(page, "Filled username");
    await clickFirstVisible(page, nextSelectors, { optional: true });
    await waitForAnySelector(page, passwordSelectors, { timeout: 2000 });
  }

  const submitPasswordAttempt = async (attemptLabel: string) => {
    const passwordReady = await waitForAnySelector(page, passwordSelectors, {
      timeout: 8000,
    });
    if (!passwordReady) {
      await logPageStateWithTag(
        page,
        `Password input did not appear during ${attemptLabel}`
      );
      return false;
    }
    const filled = await fillFirstVisible(
      page,
      passwordSelectors,
      IDP_PASSWORD
    );
    if (!filled) {
      await logPageStateWithTag(
        page,
        `Unable to find password input during ${attemptLabel}`
      );
      return false;
    }
    logOauthEvent(page, `Filled password (${attemptLabel})`);
    const clickedSubmit = await clickFirstVisible(page, submitSelectors, {
      optional: true,
    });
    if (!clickedSubmit) {
      // As a fallback, press Enter in the password field
      const passwordLocator = page.locator(passwordSelectorString).first();
      if ((await passwordLocator.count()) > 0) {
        await passwordLocator.press("Enter").catch(() => {});
      } else {
        await page.keyboard.press("Enter").catch(() => {});
      }
    }
    logOauthEvent(page, `Submitted IdP credentials (${attemptLabel})`);
    await page
      .waitForLoadState("domcontentloaded", { timeout: 15000 })
      .catch(() => {});
    await page.waitForTimeout(300);
    return true;
  };

  const hasVisiblePasswordField = async (): Promise<boolean> => {
    const locator = page.locator(passwordSelectorString);
    const count = await locator.count();
    for (let i = 0; i < count; i++) {
      try {
        if (await locator.nth(i).isVisible()) {
          return true;
        }
      } catch {
        continue;
      }
    }
    return false;
  };

  await submitPasswordAttempt("initial");

  const MAX_PASSWORD_RETRIES = 3;
  for (let retry = 1; retry <= MAX_PASSWORD_RETRIES; retry++) {
    await page.waitForTimeout(250);
    if (!isOnIdpHost(page.url())) {
      break;
    }
    if (!(await hasVisiblePasswordField())) {
      break;
    }
    logOauthEvent(page, `Password challenge still visible (retry ${retry})`);
    const success = await submitPasswordAttempt(`retry ${retry}`);
    if (!success) {
      break;
    }
  }

  await clickFirstVisible(page, consentSelectors, { optional: true });
  logOauthEvent(page, "Handled consent prompt if present");
  await page
    .waitForLoadState("networkidle", { timeout: 10000 })
    .catch(() => {});
}

async function completeOauthFlow(
  page: Page,
  options: {
    expectReturnPathContains: string;
    confirmConnected?: () => Promise<void>;
    scrollToBottomOnReturn?: boolean;
  }
): Promise<void> {
  logOauthEvent(
    page,
    `Completing OAuth flow with options: ${JSON.stringify(options)}`
  );
  const returnSubstring = options.expectReturnPathContains;
  const matchesExpectedReturnPath = (url: string) => {
    if (!isOnAppHost(url)) {
      return false;
    }
    if (url.includes(returnSubstring)) {
      return true;
    }
    // Re-auth flows can return to a chat session URL instead of assistantId URL.
    if (
      returnSubstring.includes("/app?assistantId=") &&
      url.includes("/app?chatId=")
    ) {
      return true;
    }
    return false;
  };

  logOauthEvent(page, `Current page URL: ${page.url()}`);

  const waitForUrlOrRedirect = async (
    description: string,
    timeout: number,
    predicate: (url: string) => boolean
  ) => {
    const waitStart = Date.now();
    const current = page.url();
    if (predicate(current)) {
      logOauthEvent(
        page,
        `${description} already satisfied (elapsed ${Date.now() - waitStart}ms)`
      );
      return;
    }
    logOauthEvent(page, `Waiting for ${description} (timeout ${timeout}ms)`);
    try {
      await page.waitForURL(
        (url) => {
          const href = typeof url === "string" ? url : url.toString();
          try {
            return predicate(href);
          } catch (err) {
            logOauthEvent(
              null,
              `Predicate threw while waiting for ${description}: ${String(err)}`
            );
            return false;
          }
        },
        { timeout }
      );
      logOauthEvent(
        page,
        `${description} satisfied after ${Date.now() - waitStart}ms`
      );
    } catch (error) {
      // If the predicate became true after the timeout (e.g., navigation finished
      // just before the rejection), treat it as success.
      if (predicate(page.url())) {
        logOauthEvent(
          page,
          `${description} satisfied (after timeout) in ${
            Date.now() - waitStart
          }ms`
        );
        return;
      }
      await logPageStateWithTag(page, `Timeout waiting for ${description}`);
      throw error;
    }
  };

  const tryConfirmConnected = async (
    suppressErrors: boolean
  ): Promise<boolean> => {
    if (!options.confirmConnected) {
      return false;
    }
    if (page.isClosed()) {
      const message = "Page closed before confirmConnected check";
      if (suppressErrors) {
        logOauthEvent(null, message);
        return false;
      }
      throw new Error(message);
    }
    if (!isOnAppHost(page.url())) {
      const message = `confirmConnected requested while not on app host (url=${page.url()})`;
      if (suppressErrors) {
        logOauthEvent(page, message);
        return false;
      }
      throw new Error(message);
    }
    const confirmPromise = options
      .confirmConnected()
      .then(() => ({ status: "success" as const }))
      .catch((error) => ({ status: "error" as const, error }));
    if (suppressErrors) {
      const result = await Promise.race([
        confirmPromise,
        delay(QUICK_CONFIRM_CONNECTED_TIMEOUT_MS).then(() => ({
          status: "timeout" as const,
        })),
      ]);
      if (result.status === "success") {
        return true;
      }
      if (result.status === "error") {
        logOauthEvent(page, "confirmConnected check failed, continuing");
        return false;
      }
      logOauthEvent(
        page,
        `confirmConnected quick check timed out after ${QUICK_CONFIRM_CONNECTED_TIMEOUT_MS}ms`
      );
      return false;
    }
    const finalResult = await confirmPromise;
    if (finalResult.status === "success") {
      return true;
    }
    throw finalResult.error;
  };

  if (
    matchesExpectedReturnPath(page.url()) &&
    (await tryConfirmConnected(true))
  ) {
    return;
  }

  if (isOnAppHost(page.url()) && !page.url().includes("/mcp/oauth/callback")) {
    logOauthEvent(page, "Waiting for redirect away from app host");
    await waitForUrlOrRedirect("IdP redirect", 10000, (url) => {
      const parsed = new URL(url);
      return (
        parsed.host !== APP_HOST ||
        parsed.pathname.includes("/mcp/oauth/callback")
      );
    });
  }

  if (!isOnAppHost(page.url())) {
    logOauthEvent(page, "Starting IdP login step");
    await performIdpLogin(page);
  } else if (!page.url().includes("/mcp/oauth/callback")) {
    logOauthEvent(page, "Still on app host, waiting for OAuth callback");
    await waitForUrlOrRedirect(
      "OAuth callback",
      60000,
      (url) =>
        url.includes("/mcp/oauth/callback") || matchesExpectedReturnPath(url)
    );
  }

  if (!page.url().includes("/mcp/oauth/callback")) {
    logOauthEvent(page, "Waiting for OAuth callback redirect");
    await waitForUrlOrRedirect(
      "OAuth callback",
      60000,
      (url) =>
        url.includes("/mcp/oauth/callback") || matchesExpectedReturnPath(url)
    );
  }

  const waitForReturnStart = Date.now();
  await page
    .waitForLoadState("domcontentloaded", { timeout: 5000 })
    .catch(() => {});
  logOauthEvent(
    page,
    `Initial post-return load wait completed in ${
      Date.now() - waitForReturnStart
    }ms`
  );

  await waitForUrlOrRedirect(`return path ${returnSubstring}`, 60000, (url) =>
    matchesExpectedReturnPath(url)
  );
  const returnLoadStart = Date.now();
  await page
    .waitForLoadState("domcontentloaded", { timeout: 5000 })
    .catch(() => {});
  logOauthEvent(
    page,
    `Post-return domcontentloaded wait finished in ${
      Date.now() - returnLoadStart
    }ms`
  );
  if (!matchesExpectedReturnPath(page.url())) {
    throw new Error(
      `Redirected but final URL (${page.url()}) does not contain expected substring ${returnSubstring}`
    );
  }
  logOauthEvent(page, `Returned to ${returnSubstring}`);

  if (options.scrollToBottomOnReturn) {
    await scrollToBottom(page);
  }

  await tryConfirmConnected(false);
}

async function selectMcpTools(page: Page, serverId: number) {
  // Find the server toggle switch by its name attribute
  const toggleButton = page.locator(
    `button[role="switch"][name="mcp_server_${serverId}.enabled"]`
  );
  const toggleExists = await toggleButton.count();
  if (toggleExists === 0) {
    throw new Error(
      `MCP server section ${serverId} not found in assistant form`
    );
  }

  // Check if the server is enabled (switch is checked)
  const isEnabled = await toggleButton.getAttribute("aria-checked");
  if (isEnabled !== "true") {
    await toggleButton.click();
  }

  // Individual tools are automatically enabled when the server switch is turned on
  // The new AgentEditorPage enables all tools when the server is enabled
}

const escapeRegex = (value: string): string =>
  value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const ACTION_POPOVER_SELECTOR = '[data-testid="tool-options"]';
const LINE_ITEM_SELECTOR = ".group\\/LineItem";

async function ensureActionPopoverInPrimaryView(page: Page) {
  const popover = page.locator(ACTION_POPOVER_SELECTOR);
  const isVisible = await popover.isVisible().catch(() => false);
  if (!isVisible) {
    return;
  }

  const serverRows = page.locator("[data-mcp-server-name]");
  if ((await serverRows.count()) > 0) {
    return;
  }

  const backButton = popover.getByRole("button", { name: /Back/i }).first();
  if ((await backButton.count()) === 0) {
    return;
  }
  await backButton.click().catch(() => {});
  await page.waitForTimeout(200);
}

async function waitForMcpSecondaryView(page: Page) {
  const toggleControls = page
    .locator(ACTION_POPOVER_SELECTOR)
    .locator(LINE_ITEM_SELECTOR)
    .filter({ hasText: /(Enable|Disable) All/i })
    .first();
  await toggleControls
    .waitFor({ state: "visible", timeout: 5000 })
    .catch(() => {});
}

async function findMcpToolLineItemButton(
  page: Page,
  toolName: string,
  timeoutMs = 5000
): Promise<Locator | null> {
  const deadline = Date.now() + timeoutMs;
  const toolRegex = new RegExp(escapeRegex(toolName), "i");

  while (Date.now() < deadline) {
    const lineItem = page
      .locator(
        `${ACTION_POPOVER_SELECTOR} [data-testid^="tool-option-"] ${LINE_ITEM_SELECTOR}, ` +
          `${ACTION_POPOVER_SELECTOR} ${LINE_ITEM_SELECTOR}`
      )
      .filter({ hasText: toolRegex })
      .first();
    if ((await lineItem.count()) > 0) {
      return lineItem;
    }
    await page.waitForTimeout(200);
  }

  return null;
}

async function logActionPopoverHtml(page: Page, context: string) {
  try {
    const popover = page.locator(ACTION_POPOVER_SELECTOR);
    if ((await popover.count()) === 0) {
      console.log(
        `[mcp-oauth-debug] ${context} action-popover-html="<unavailable>" reason=popover-missing`
      );
      return;
    }
    const isVisible = await popover.isVisible().catch(() => false);
    if (!isVisible) {
      console.log(
        `[mcp-oauth-debug] ${context} action-popover-html="<unavailable>" reason=popover-hidden`
      );
      return;
    }
    const html = await popover.evaluate((node) => node.innerHTML || "");
    const snippet = html.replace(/\s+/g, " ").slice(0, 2000);
    console.log(
      `[mcp-oauth-debug] ${context} action-popover-html=${JSON.stringify(
        snippet
      )}`
    );
  } catch (error) {
    console.log(
      `[mcp-oauth-debug] ${context} action-popover-html="<unavailable>" reason=${String(
        error
      )}`
    );
  }
}

async function closeActionsPopover(page: Page) {
  if (page.isClosed()) {
    return;
  }

  const popover = page.locator(ACTION_POPOVER_SELECTOR);
  if ((await popover.count()) === 0) {
    return;
  }
  const isVisible = await popover.isVisible().catch(() => false);
  if (!isVisible) {
    return;
  }

  const backButton = popover.getByRole("button", { name: /Back/i }).first();
  if ((await backButton.count()) > 0) {
    await backButton.click().catch(() => {});
    await page.waitForTimeout(200).catch(() => {});
  }

  if (!page.isClosed()) {
    await page.keyboard.press("Escape").catch(() => {});
  }
}

async function openActionsPopover(page: Page) {
  const popover = page.locator(ACTION_POPOVER_SELECTOR);
  const isVisible = await popover.isVisible().catch(() => false);
  if (!isVisible) {
    await page.locator('[data-testid="action-management-toggle"]').click();
    await popover.waitFor({ state: "visible", timeout: 10000 });
  }
  await ensureActionPopoverInPrimaryView(page);
}

async function restoreAssistantContext(page: Page, assistantId: number) {
  const assistantPath = `/app?assistantId=${assistantId}`;
  logOauthEvent(
    page,
    `Restoring assistant context for assistantId=${assistantId} (current url=${page.url()})`
  );

  // Clear chat-focused URL state first, then explicitly reselect assistant.
  await page.goto(`${APP_BASE_URL}/app`, { waitUntil: "domcontentloaded" });
  await page
    .waitForLoadState("networkidle", { timeout: 10000 })
    .catch(() => {});

  const assistantLink = page
    .locator(`a[href*="assistantId=${assistantId}"]`)
    .first();
  if ((await assistantLink.count()) > 0) {
    await clickAndWaitForPossibleUrlChange(
      page,
      () => assistantLink.click(),
      `Restore assistant ${assistantId} from sidebar`
    );
  } else {
    await page.goto(`${APP_BASE_URL}${assistantPath}`, {
      waitUntil: "domcontentloaded",
    });
  }

  await page
    .waitForLoadState("networkidle", { timeout: 10000 })
    .catch(() => {});
  logOauthEvent(page, `Assistant context restore landed on ${page.url()}`);
}

function getServerRowLocator(page: Page, serverName: string) {
  const labelRegex = new RegExp(escapeRegex(serverName));
  return page
    .locator(
      `${ACTION_POPOVER_SELECTOR} [data-mcp-server-name] ${LINE_ITEM_SELECTOR}, ` +
        `${ACTION_POPOVER_SELECTOR} ${LINE_ITEM_SELECTOR}`
    )
    .filter({ hasText: labelRegex })
    .first();
}

async function collectActionPopoverEntries(page: Page): Promise<string[]> {
  const locator = page
    .locator(ACTION_POPOVER_SELECTOR)
    .locator(
      `[data-mcp-server-name] ${LINE_ITEM_SELECTOR}, ` +
        `[data-testid^="tool-option-"] ${LINE_ITEM_SELECTOR}, ` +
        `${LINE_ITEM_SELECTOR}`
    );
  try {
    return await locator.evaluateAll((nodes) =>
      nodes
        .map((node) =>
          (node.textContent || "")
            .replace(/\s+/g, " ")
            .replace(/\u00a0/g, " ")
            .trim()
        )
        .filter(Boolean)
    );
  } catch {
    return [];
  }
}

async function waitForServerRow(
  page: Page,
  serverName: string,
  timeoutMs: number = 10_000
): Promise<Locator | null> {
  await page
    .locator(ACTION_POPOVER_SELECTOR)
    .waitFor({ state: "visible", timeout: 5000 })
    .catch(() => {});

  const locator = getServerRowLocator(page, serverName);
  const pollInterval = 100;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    if ((await locator.count()) > 0) {
      return locator;
    }
    await page.waitForTimeout(pollInterval);
  }

  return null;
}

async function clickServerRowAndWaitForPossibleUrlChangeWithRetry(
  page: Page,
  serverName: string,
  actionName: string,
  timeoutMs: number = 15_000
): Promise<boolean> {
  let serverLocator: Locator | null = await waitForServerRow(
    page,
    serverName,
    timeoutMs
  );
  if (!serverLocator) {
    return false;
  }

  for (let attempt = 0; attempt < 5; attempt++) {
    if (!serverLocator) {
      const refreshedServerLocator = await waitForServerRow(
        page,
        serverName,
        5000
      );
      if (!refreshedServerLocator) {
        continue;
      }
      serverLocator = refreshedServerLocator;
    }
    const locatorToClick = serverLocator;
    try {
      await clickAndWaitForPossibleUrlChange(
        page,
        () => locatorToClick.click({ force: true, timeout: 3000 }),
        actionName
      );
      return true;
    } catch {
      if (attempt === 4) {
        break;
      }
      await page.waitForTimeout(150);
      await ensureActionPopoverInPrimaryView(page);
      const refreshedServerLocator = await waitForServerRow(
        page,
        serverName,
        5000
      );
      if (refreshedServerLocator) {
        serverLocator = refreshedServerLocator;
      }
    }
  }

  return false;
}

async function ensureToolOptionVisible(
  page: Page,
  toolName: string,
  serverName: string
) {
  await page
    .waitForSelector(ACTION_POPOVER_SELECTOR, {
      state: "visible",
      timeout: 5000,
    })
    .catch(() => {});

  let toolOption = page
    .getByTestId(`tool-option-${toolName}`)
    .locator(LINE_ITEM_SELECTOR)
    .first();
  if ((await toolOption.count()) > 0) {
    return toolOption;
  }

  await ensureActionPopoverInPrimaryView(page);
  let serverLocator = await waitForServerRow(page, serverName, 10_000);
  if (!serverLocator) {
    const entries = await collectActionPopoverEntries(page);
    await logPageStateWithTag(
      page,
      `MCP server row ${serverName} not found while forcing tool ${toolName}. Visible entries: ${JSON.stringify(
        entries
      )}`
    );
    throw new Error(`Unable to locate MCP server row for ${serverName}`);
  }

  let serverClicked = false;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await serverLocator.click({ force: true, timeout: 3000 });
      serverClicked = true;
      break;
    } catch (error) {
      if (attempt === 2) {
        throw error;
      }
      await page.waitForTimeout(150);
      await ensureActionPopoverInPrimaryView(page);
      const refreshedServerLocator = await waitForServerRow(
        page,
        serverName,
        5000
      );
      if (refreshedServerLocator) {
        serverLocator = refreshedServerLocator;
      }
    }
  }
  if (!serverClicked) {
    throw new Error(`Unable to click MCP server row for ${serverName}`);
  }

  await waitForMcpSecondaryView(page);

  for (let attempt = 0; attempt < 3; attempt++) {
    const mcpToolButton = await findMcpToolLineItemButton(
      page,
      toolName,
      10000
    );
    if (mcpToolButton) {
      const isVisible = await mcpToolButton.isVisible().catch(() => false);
      if (isVisible) {
        return mcpToolButton;
      }
    }
    if (attempt < 2) {
      await closeActionsPopover(page);
      await openActionsPopover(page);
      await ensureActionPopoverInPrimaryView(page);
      const refreshedServerLocator = await waitForServerRow(
        page,
        serverName,
        7000
      );
      if (!refreshedServerLocator) {
        break;
      }
      await refreshedServerLocator.click({ force: true, timeout: 3000 });
      await waitForMcpSecondaryView(page);
    }
  }

  await logPageStateWithTag(
    page,
    `Tool option ${toolName} still missing after selecting MCP server ${serverName}`
  );
  await logActionPopoverHtml(
    page,
    `Tool option ${toolName} missing after selecting ${serverName}`
  );
  throw new Error(
    `Tool option ${toolName} not available after selecting server ${serverName}`
  );
}

async function verifyMcpToolRowVisible(
  page: Page,
  serverName: string,
  toolName: string
) {
  await openActionsPopover(page);
  const toolButton = await ensureToolOptionVisible(page, toolName, serverName);
  await expect(toolButton).toBeVisible({ timeout: 5000 });
  await closeActionsPopover(page);
}

async function ensureMcpToolEnabledInActions(
  page: Page,
  serverName: string,
  toolName: string
) {
  await openActionsPopover(page);
  const toolButton = await ensureToolOptionVisible(page, toolName, serverName);
  await expect(toolButton).toBeVisible({ timeout: 5000 });

  let toolToggle = toolButton.getByRole("switch").first();
  if ((await toolToggle.count()) === 0) {
    toolToggle = page.getByLabel(`Toggle ${toolName}`).first();
  }
  await expect(toolToggle).toBeVisible({ timeout: 5000 });

  const isToggleChecked = async () => {
    const dataState = await toolToggle.getAttribute("data-state");
    if (typeof dataState === "string") {
      return dataState === "checked";
    }
    return (await toolToggle.getAttribute("aria-checked")) === "true";
  };

  if (!(await isToggleChecked())) {
    await toolToggle.click();
  }
  await expect.poll(isToggleChecked, { timeout: 5000 }).toBe(true);
  await closeActionsPopover(page);
}

async function reauthenticateFromChat(
  page: Page,
  serverName: string,
  returnSubstring: string
) {
  await openActionsPopover(page);
  const beforeClickUrl = page.url();
  const clickedServerRow =
    await clickServerRowAndWaitForPossibleUrlChangeWithRetry(
      page,
      serverName,
      "Re-authenticate server row click",
      15_000
    );
  if (!clickedServerRow) {
    const entries = await collectActionPopoverEntries(page);
    await logPageStateWithTag(
      page,
      `reauthenticateFromChat could not click ${serverName}; visible entries: ${JSON.stringify(
        entries
      )}`
    );
    throw new Error(
      `Unable to click MCP server row ${serverName} while reauthenticating`
    );
  }

  // Some MCP rows trigger OAuth directly instead of showing a footer action.
  if (page.url() !== beforeClickUrl || !isOnAppHost(page.url())) {
    await completeOauthFlow(page, {
      expectReturnPathContains: returnSubstring,
    });
    return;
  }

  await waitForMcpSecondaryView(page);
  const reauthItem = page.getByText("Re-Authenticate").first();
  let reauthVisible = await reauthItem.isVisible().catch(() => false);
  if (!reauthVisible) {
    // Popover state can rerender; retry selection once before failing.
    await closeActionsPopover(page);
    await openActionsPopover(page);
    const retryBeforeClickUrl = page.url();
    const clickedRetry =
      await clickServerRowAndWaitForPossibleUrlChangeWithRetry(
        page,
        serverName,
        "Re-authenticate server row click retry",
        10_000
      );
    if (!clickedRetry) {
      const entries = await collectActionPopoverEntries(page);
      await logPageStateWithTag(
        page,
        `reauthenticateFromChat retry could not click ${serverName}; visible entries: ${JSON.stringify(
          entries
        )}`
      );
      throw new Error(
        `Unable to click MCP server row ${serverName} on reauth retry`
      );
    }

    if (page.url() !== retryBeforeClickUrl || !isOnAppHost(page.url())) {
      await completeOauthFlow(page, {
        expectReturnPathContains: returnSubstring,
      });
      return;
    }

    await waitForMcpSecondaryView(page);
    reauthVisible = await reauthItem.isVisible().catch(() => false);
  }

  await expect(reauthItem).toBeVisible({ timeout: 15000 });
  await clickAndWaitForPossibleUrlChange(
    page,
    () => reauthItem.click(),
    "Re-authenticate click"
  );
  await completeOauthFlow(page, {
    expectReturnPathContains: returnSubstring,
  });
}

async function ensureServerVisibleInActions(
  page: Page,
  serverName: string,
  options?: {
    assistantId?: number;
  }
) {
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.keyboard.press("Escape").catch(() => {});
    await openActionsPopover(page);
    const locatorToUse = await waitForServerRow(page, serverName, 15_000);

    if (locatorToUse) {
      await expect(locatorToUse).toBeVisible({ timeout: 15000 });
      await page.keyboard.press("Escape").catch(() => {});
      return;
    }

    const entries = await collectActionPopoverEntries(page);
    await logPageStateWithTag(
      page,
      `ensureServerVisibleInActions could not find ${serverName}; visible entries: ${JSON.stringify(
        entries
      )}`
    );
    await page.keyboard.press("Escape").catch(() => {});

    if (attempt === 0 && options?.assistantId) {
      logOauthEvent(
        page,
        `Server ${serverName} missing in actions, retrying after restoring assistant ${options.assistantId} context`
      );
      await restoreAssistantContext(page, options.assistantId);
      continue;
    }

    throw new Error(`Server ${serverName} not visible in actions popover`);
  }
}

async function waitForUserRecord(
  client: OnyxApiClient,
  email: string,
  timeoutMs: number = 10_000
) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const record = await client.getUserByEmail(email);
    if (record) {
      return record;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out waiting for user record ${email}`);
}

async function waitForAssistantByName(
  client: OnyxApiClient,
  assistantName: string,
  timeoutMs: number = 20_000
) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const assistant = await client.findAssistantByName(assistantName, {
      getEditable: true,
    });
    if (assistant) {
      return assistant;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out waiting for assistant ${assistantName}`);
}

async function waitForAssistantTools(
  client: OnyxApiClient,
  assistantName: string,
  requiredToolNames: string[],
  timeoutMs: number = 30_000
) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const assistant = await client.findAssistantByName(assistantName, {
      getEditable: true,
    });
    if (
      assistant &&
      Array.isArray(assistant.tools) &&
      requiredToolNames.every((name) =>
        assistant.tools.some(
          (tool: any) =>
            tool?.name === name ||
            tool?.in_code_tool_id === name ||
            tool?.display_name === name
        )
      )
    ) {
      return assistant;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(
    `Timed out waiting for assistant ${assistantName} to include tools: ${requiredToolNames.join(
      ", "
    )}`
  );
}

async function mockEmptyOauthStatus(page: Page): Promise<void> {
  await page.route("**/api/mcp/oauth/status*", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ statuses: [] }),
    })
  );
}

function getNumericQueryParam(
  urlString: string,
  paramName: string
): number | null {
  try {
    const value = new URL(urlString).searchParams.get(paramName);
    if (!value) {
      return null;
    }
    const parsed = Number(value);
    return Number.isNaN(parsed) ? null : parsed;
  } catch {
    return null;
  }
}

async function configureOauthServerAndEnableTool(
  page: Page,
  options: {
    serverName: string;
    serverDescription: string;
    serverUrl: string;
    toolName: string;
    connectContext: string;
    logStep: StepLogger;
  }
): Promise<number> {
  const { serverName, serverDescription, serverUrl, toolName, connectContext } =
    options;

  await page.goto("/admin/actions/mcp");
  await page.waitForURL("**/admin/actions/mcp**", { timeout: 15000 });
  options.logStep("Opened MCP actions page");

  await page.getByRole("button", { name: /Add MCP Server/i }).click();
  await expect(page.locator("input#name")).toBeVisible({ timeout: 10000 });
  options.logStep("Opened Add MCP Server modal");

  await page.locator("input#name").fill(serverName);
  await page.locator("textarea#description").fill(serverDescription);
  await page.locator("input#server_url").fill(serverUrl);
  options.logStep(`Filled server URL: ${serverUrl}`);

  await page.getByRole("button", { name: "Add Server" }).click();
  await expect(page.getByTestId("mcp-auth-method-select")).toBeVisible({
    timeout: 10000,
  });
  options.logStep("Created MCP server, auth modal opened");

  const authMethodSelect = page.getByTestId("mcp-auth-method-select");
  await authMethodSelect.click();
  await page.getByRole("option", { name: "OAuth" }).click();
  options.logStep("Selected OAuth authentication method");

  await page.locator('input[name="oauth_client_id"]').fill(CLIENT_ID);
  await page.locator('input[name="oauth_client_secret"]').fill(CLIENT_SECRET);
  options.logStep("Filled OAuth credentials");

  const connectButton = page.getByTestId("mcp-auth-connect-button");
  await clickAndWaitForPossibleUrlChange(
    page,
    () => connectButton.click(),
    connectContext
  );
  options.logStep("Triggered OAuth connection");

  let serverId: number | null = null;
  await completeOauthFlow(page, {
    expectReturnPathContains: "/admin/actions/mcp",
    confirmConnected: async () => {
      serverId = getNumericQueryParam(page.url(), "server_id");
      if (serverId === null) {
        throw new Error("Missing or invalid server_id in OAuth return URL");
      }
      await expect(
        page.getByText(serverName, { exact: false }).first()
      ).toBeVisible({ timeout: 15000 });
    },
    scrollToBottomOnReturn: false,
  });
  options.logStep("Completed OAuth flow for MCP server");

  if (serverId === null) {
    serverId = getNumericQueryParam(page.url(), "server_id");
  }
  if (serverId === null) {
    throw new Error("Expected numeric server_id in URL after OAuth flow");
  }

  await expect(
    page.getByText(serverName, { exact: false }).first()
  ).toBeVisible({
    timeout: 20000,
  });
  const toolToggles = page.getByLabel(`tool-toggle-${toolName}`);
  await expect(toolToggles.first()).toBeVisible({ timeout: 20000 });
  options.logStep("Verified server card and tool toggles are visible");

  const toggleCount = await toolToggles.count();
  options.logStep(`Found ${toggleCount} instance(s) of ${toolName}`);
  for (let i = 0; i < toggleCount; i++) {
    const toggle = toolToggles.nth(i);
    const isEnabled = await toggle.getAttribute("aria-checked");
    if (isEnabled !== "true") {
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-checked", "true", {
        timeout: 5000,
      });
      options.logStep(`Enabled tool instance ${i + 1}: ${toolName}`);
    }
  }
  options.logStep("Tools auto-fetched and enabled via UI");

  return serverId;
}

async function openAssistantEditor(
  page: Page,
  options: {
    logStep: StepLogger;
    onLoginRedirect?: () => Promise<void>;
  }
): Promise<void> {
  const assistantEditorUrl = `${APP_BASE_URL}/app/agents/create?admin=true`;
  let assistantPageLoaded = false;

  for (let attempt = 0; attempt < 2 && !assistantPageLoaded; attempt++) {
    await page.goto(assistantEditorUrl);
    try {
      await page.waitForURL("**/app/agents/create**", {
        timeout: 15000,
      });
      assistantPageLoaded = true;
    } catch (error) {
      const currentUrl = page.url();
      if (currentUrl.includes("/app/agents/create")) {
        assistantPageLoaded = true;
        break;
      }
      if (currentUrl.includes("/app?from=login") && options.onLoginRedirect) {
        await options.onLoginRedirect();
        continue;
      }
      await logPageStateWithTag(
        page,
        "Timed out waiting for /app/agents/create"
      );
      throw error;
    }
  }

  if (!assistantPageLoaded) {
    throw new Error("Unable to navigate to /app/agents/create");
  }
  options.logStep("Assistant editor loaded");
}

async function createAssistantAndWaitForTool(
  page: Page,
  options: {
    apiClient: OnyxApiClient;
    assistantName: string;
    instructions: string;
    description: string;
    serverId: number;
    toolName: string;
    logStep: StepLogger;
  }
): Promise<number> {
  const {
    apiClient,
    assistantName,
    instructions,
    description,
    serverId,
    toolName,
    logStep,
  } = options;

  await page.locator('input[name="name"]').fill(assistantName);
  await page.locator('textarea[name="instructions"]').fill(instructions);
  await page.locator('textarea[name="description"]').fill(description);
  await selectMcpTools(page, serverId);

  await page.getByRole("button", { name: "Create" }).click();
  await page.waitForURL(
    (url) => {
      const href = typeof url === "string" ? url : url.toString();
      return (
        /\/app\?assistantId=\d+/.test(href) ||
        href.includes("/admin/assistants")
      );
    },
    { timeout: 20000 }
  );

  let assistantId = getNumericQueryParam(page.url(), "assistantId");
  if (assistantId === null) {
    const assistantRecord = await waitForAssistantByName(
      apiClient,
      assistantName
    );
    assistantId = assistantRecord.id;
    await page.goto(`/app?assistantId=${assistantId}`);
    await page.waitForURL(/\/app\?assistantId=\d+/, { timeout: 20000 });
  }
  if (assistantId === null) {
    throw new Error("Assistant ID could not be determined");
  }
  logStep(`Assistant created with id ${assistantId}`);

  await waitForAssistantTools(apiClient, assistantName, [toolName]);
  logStep("Confirmed assistant tools are available");
  return assistantId;
}

test.describe("MCP OAuth flows", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(MCP_OAUTH_FLOW_TEST_TIMEOUT_MS);

  let serverProcess: McpServerProcess | null = null;
  let adminArtifacts: FlowArtifacts | null = null;
  let curatorArtifacts: FlowArtifacts | null = null;
  let curatorCredentials: Credentials | null = null;
  let curatorTwoCredentials: Credentials | null = null;
  let curatorGroupId: number | null = null;
  let curatorTwoGroupId: number | null = null;

  test.beforeAll(async ({ browser }, workerInfo) => {
    if (workerInfo.project.name !== "admin") {
      return;
    }

    if (!process.env.MCP_TEST_SERVER_URL) {
      const basePort = Number(process.env.MCP_TEST_SERVER_PORT || "8004");
      const allocatedPort = basePort + workerInfo.workerIndex;
      serverProcess = await startMcpOauthServer({
        port: allocatedPort,
        bindHost: process.env.MCP_TEST_SERVER_BIND_HOST,
        publicHost: process.env.MCP_TEST_SERVER_PUBLIC_HOST,
      });
      const explicitPublicUrl = process.env.MCP_TEST_SERVER_PUBLIC_URL;
      if (explicitPublicUrl) {
        runtimeMcpServerUrl = buildMcpServerUrl(explicitPublicUrl);
      } else {
        const { host: publicHost, port } = serverProcess.address;
        runtimeMcpServerUrl = buildMcpServerUrl(`http://${publicHost}:${port}`);
      }
    } else {
      runtimeMcpServerUrl = buildMcpServerUrl(process.env.MCP_TEST_SERVER_URL);
    }

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminPage = await adminContext.newPage();
    const adminClient = new OnyxApiClient(adminPage.request);
    try {
      const existingServers = await adminClient.listMcpServers();
      for (const server of existingServers) {
        if (server.server_url === runtimeMcpServerUrl) {
          await adminClient.deleteMcpServer(server.id);
        }
      }
    } catch (error) {
      console.warn("Failed to cleanup existing MCP servers", error);
    }

    const basePassword = "TestPassword123!";
    curatorCredentials = {
      email: `pw-curator-${Date.now()}@example.com`,
      password: basePassword,
    };
    await adminClient.registerUser(
      curatorCredentials.email,
      curatorCredentials.password
    );
    const curatorRecord = await waitForUserRecord(
      adminClient,
      curatorCredentials.email
    );
    curatorGroupId = await adminClient.createUserGroup(
      `Playwright Curator Group ${Date.now()}`,
      [curatorRecord.id]
    );
    await adminClient.setCuratorStatus(
      String(curatorGroupId),
      curatorRecord.id,
      true
    );
    curatorTwoCredentials = {
      email: `pw-curator-${Date.now()}-b@example.com`,
      password: basePassword,
    };
    await adminClient.registerUser(
      curatorTwoCredentials.email,
      curatorTwoCredentials.password
    );
    const curatorTwoRecord = await waitForUserRecord(
      adminClient,
      curatorTwoCredentials.email
    );
    curatorTwoGroupId = await adminClient.createUserGroup(
      `Playwright Curator Group ${Date.now()}-2`,
      [curatorTwoRecord.id]
    );
    await adminClient.setCuratorStatus(
      String(curatorTwoGroupId),
      curatorTwoRecord.id,
      true
    );

    await adminContext.close();
  });

  test.afterAll(async ({ browser }, workerInfo) => {
    if (workerInfo.project.name !== "admin") {
      return;
    }

    if (serverProcess) {
      await serverProcess.stop();
    }

    const adminContext = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const adminPage = await adminContext.newPage();
    const adminClient = new OnyxApiClient(adminPage.request);

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

    if (curatorGroupId) {
      await adminClient.deleteUserGroup(curatorGroupId);
    }
    if (curatorTwoGroupId) {
      await adminClient.deleteUserGroup(curatorTwoGroupId);
    }

    await adminContext.close();
  });

  test("Admin can configure OAuth MCP server and use tools end-to-end", async ({
    page,
  }, testInfo) => {
    test.setTimeout(MCP_OAUTH_FLOW_TEST_TIMEOUT_MS);
    const logStep = createStepLogger("AdminFlow");
    test.skip(
      testInfo.project.name !== "admin",
      "MCP OAuth flows run only in admin project"
    );
    logStep("Starting admin MCP OAuth flow");

    await mockEmptyOauthStatus(page);

    await page.context().clearCookies();
    logStep("Cleared cookies");
    await loginAs(page, "admin");
    await verifySessionUser(
      page,
      { email: TEST_ADMIN_CREDENTIALS.email, role: "admin" },
      "AdminFlow primary login"
    );
    const adminApiClient = new OnyxApiClient(page.request);
    logStep("Logged in as admin");

    const serverName = `PW MCP Admin ${Date.now()}`;
    const assistantName = `PW Admin Assistant ${Date.now()}`;

    const serverId = await configureOauthServerAndEnableTool(page, {
      serverName,
      serverDescription: "Playwright MCP OAuth server (admin)",
      serverUrl: runtimeMcpServerUrl,
      toolName: TOOL_NAMES.admin,
      connectContext: "Admin connect click",
      logStep,
    });

    await openAssistantEditor(page, {
      logStep,
      onLoginRedirect: async () => {
        await loginAs(page, "admin");
        await verifySessionUser(
          page,
          { email: TEST_ADMIN_CREDENTIALS.email, role: "admin" },
          "AdminFlow assistant editor relogin"
        );
      },
    });

    const assistantId = await createAssistantAndWaitForTool(page, {
      apiClient: adminApiClient,
      assistantName,
      instructions: "Assist with MCP OAuth testing.",
      description: "Playwright admin MCP assistant.",
      serverId,
      toolName: TOOL_NAMES.admin,
      logStep,
    });
    const adminToolId = await fetchMcpToolIdByName(
      page,
      serverId,
      TOOL_NAMES.admin
    );

    await ensureServerVisibleInActions(page, serverName, { assistantId });
    await verifyMcpToolRowVisible(page, serverName, TOOL_NAMES.admin);
    await ensureMcpToolEnabledInActions(page, serverName, TOOL_NAMES.admin);
    logStep("Verified admin MCP tool row visible before reauth");
    await verifyToolInvocationFromChat(
      page,
      TOOL_NAMES.admin,
      "AdminFlow pre-reauth",
      adminToolId
    );
    logStep("Verified admin MCP tool invocation before reauth");

    await reauthenticateFromChat(
      page,
      serverName,
      `/app?assistantId=${assistantId}`
    );
    await ensureServerVisibleInActions(page, serverName, { assistantId });
    await verifyMcpToolRowVisible(page, serverName, TOOL_NAMES.admin);
    await ensureMcpToolEnabledInActions(page, serverName, TOOL_NAMES.admin);
    logStep("Verified admin MCP tool row visible after reauth");
    await verifyToolInvocationFromChat(
      page,
      TOOL_NAMES.admin,
      "AdminFlow post-reauth",
      adminToolId
    );
    logStep("Verified admin MCP tool invocation after reauth");

    // Verify server card still shows the server and tools
    await page.goto("/admin/actions/mcp");
    await page.waitForURL("**/admin/actions/mcp**", { timeout: 15000 });
    await expect(
      page.getByText(serverName, { exact: false }).first()
    ).toBeVisible({ timeout: 15000 });
    logStep("Verified MCP server card is still visible on actions page");

    adminArtifacts = {
      serverId,
      serverName,
      assistantId,
      assistantName,
      toolName: TOOL_NAMES.admin,
      toolId: adminToolId,
    };
  });

  test("Curator flow with access isolation", async ({
    page,
    browser,
  }, testInfo) => {
    test.setTimeout(MCP_OAUTH_FLOW_TEST_TIMEOUT_MS);
    const logStep = createStepLogger("CuratorFlow");
    test.skip(
      testInfo.project.name !== "admin",
      "MCP OAuth flows run only in admin project"
    );
    logStep("Starting curator MCP OAuth flow");
    await mockEmptyOauthStatus(page);

    if (!curatorCredentials || !curatorTwoCredentials) {
      test.skip(true, "Curator credentials were not initialized");
    }

    await page.context().clearCookies();
    logStep("Cleared cookies");
    await apiLogin(
      page,
      curatorCredentials!.email,
      curatorCredentials!.password
    );
    await verifySessionUser(
      page,
      { email: curatorCredentials!.email, role: "curator" },
      "CuratorFlow primary login"
    );
    logStep("Logged in as curator");
    const curatorApiClient = new OnyxApiClient(page.request);

    const serverName = `PW MCP Curator ${Date.now()}`;
    const assistantName = `PW Curator Assistant ${Date.now()}`;

    let curatorServerProcess: McpServerProcess | null = null;
    let curatorRuntimeMcpServerUrl = runtimeMcpServerUrl;

    try {
      if (!process.env.MCP_TEST_SERVER_URL) {
        const basePort =
          (serverProcess?.address.port ??
            Number(process.env.MCP_TEST_SERVER_PORT || "8004")) + 1;
        curatorServerProcess = await startMcpOauthServer({ port: basePort });
        const { host, port } = curatorServerProcess.address;
        curatorRuntimeMcpServerUrl = `http://${host}:${port}/mcp`;
      }

      const serverId = await configureOauthServerAndEnableTool(page, {
        serverName,
        serverDescription: "Playwright MCP OAuth server (curator)",
        serverUrl: curatorRuntimeMcpServerUrl,
        toolName: TOOL_NAMES.curator,
        connectContext: "Curator connect click",
        logStep,
      });

      await openAssistantEditor(page, { logStep });

      const assistantId = await createAssistantAndWaitForTool(page, {
        apiClient: curatorApiClient,
        assistantName,
        instructions: "Curator MCP OAuth assistant.",
        description: "Playwright curator MCP assistant.",
        serverId,
        toolName: TOOL_NAMES.curator,
        logStep,
      });

      await ensureServerVisibleInActions(page, serverName, { assistantId });
      await verifyMcpToolRowVisible(page, serverName, TOOL_NAMES.curator);
      logStep("Verified curator MCP tool row visible before reauth");

      await reauthenticateFromChat(
        page,
        serverName,
        `/app?assistantId=${assistantId}`
      );
      await ensureServerVisibleInActions(page, serverName, { assistantId });
      await verifyMcpToolRowVisible(page, serverName, TOOL_NAMES.curator);
      logStep("Verified curator MCP tool row visible after reauth");

      curatorArtifacts = {
        serverId,
        serverName,
        assistantId,
        assistantName,
        toolName: TOOL_NAMES.curator,
        toolId: null,
      };

      // Verify isolation: second curator must not be able to edit first curator's server
      const curatorTwoContext = await browser.newContext();
      const curatorTwoPage = await curatorTwoContext.newPage();
      await logoutSession(
        curatorTwoPage,
        "CuratorFlow secondary pre-login logout"
      );
      await apiLogin(
        curatorTwoPage,
        curatorTwoCredentials!.email,
        curatorTwoCredentials!.password
      );
      await verifySessionUser(
        curatorTwoPage,
        { email: curatorTwoCredentials!.email, role: "curator" },
        "CuratorFlow secondary login"
      );
      await curatorTwoPage.goto("/admin/actions/mcp");
      const serverLocator = curatorTwoPage.getByText(serverName, {
        exact: false,
      });
      await expect(serverLocator).not.toHaveCount(0, { timeout: 15000 });

      const editResponse = await curatorTwoPage.request.get(
        `${APP_BASE_URL}/api/admin/mcp/servers/${serverId}`
      );
      expect(editResponse.status()).toBe(403);
      await curatorTwoContext.close();
    } finally {
      await curatorServerProcess?.stop().catch(() => {});
    }
  });

  test("End user can authenticate and invoke MCP tools via chat", async ({
    page,
  }, testInfo) => {
    test.setTimeout(MCP_OAUTH_FLOW_TEST_TIMEOUT_MS);
    const logStep = createStepLogger("UserFlow");
    test.skip(
      testInfo.project.name !== "admin",
      "MCP OAuth flows run only in admin project"
    );
    logStep("Starting end-user MCP OAuth flow");
    await mockEmptyOauthStatus(page);

    test.skip(!adminArtifacts, "Admin flow must complete before user test");

    await page.context().clearCookies();
    logStep("Cleared cookies");
    await loginAs(page, "user");
    logStep("Logged in as user");

    const assistantId = adminArtifacts!.assistantId;
    const serverName = adminArtifacts!.serverName;
    const toolName = adminArtifacts!.toolName;

    await page.goto(`/app?assistantId=${assistantId}`, {
      waitUntil: "load",
    });
    await ensureServerVisibleInActions(page, serverName, { assistantId });
    logStep("Opened chat as user and ensured server visible");

    await openActionsPopover(page);
    const serverLineItem = await waitForServerRow(page, serverName, 15_000);
    if (!serverLineItem) {
      const entries = await collectActionPopoverEntries(page);
      await logPageStateWithTag(
        page,
        `UserFlow reauth locate failed for ${serverName}; visible entries: ${JSON.stringify(
          entries
        )}`
      );
      throw new Error(
        `Unable to locate MCP server row ${serverName} for user reauth`
      );
    }
    await expect(serverLineItem).toBeVisible({ timeout: 15000 });

    const clickedServerRow =
      await clickServerRowAndWaitForPossibleUrlChangeWithRetry(
        page,
        serverName,
        "End-user reauth click",
        15_000
      );
    if (!clickedServerRow) {
      const entries = await collectActionPopoverEntries(page);
      await logPageStateWithTag(
        page,
        `UserFlow reauth click failed for ${serverName}; visible entries: ${JSON.stringify(
          entries
        )}`
      );
      throw new Error(
        `Unable to click MCP server row ${serverName} for user reauth`
      );
    }

    await completeOauthFlow(page, {
      expectReturnPathContains: `/app?assistantId=${assistantId}`,
    });
    logStep("Completed user OAuth reauthentication");

    await ensureServerVisibleInActions(page, serverName, { assistantId });
    await verifyMcpToolRowVisible(page, serverName, toolName);
    await ensureMcpToolEnabledInActions(page, serverName, toolName);
    logStep("Verified user MCP tool row visible after reauth");
    await verifyToolInvocationFromChat(
      page,
      toolName,
      "UserFlow post-reauth",
      adminArtifacts!.toolId
    );
    logStep("Verified user MCP tool invocation after reauth");
  });
});
