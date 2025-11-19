import { test, expect } from "@chromatic-com/playwright";
import type { Page, Browser, Locator } from "@playwright/test";
import { loginAs, loginWithCredentials } from "../utils/auth";
import { OnyxApiClient } from "../utils/onyxApiClient";
import { startMcpOauthServer, McpServerProcess } from "../utils/mcpServer";
import { TEST_ADMIN_CREDENTIALS } from "../constants";
import { logPageState } from "../utils/pageStateLogger";

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
  "#idp-discovery-username",
  'input[id="idp-discovery-username"]',
  'input[name="email"]',
  'input[type="email"]',
  'input[name="identifier"]',
  "#identifier-input",
  "#username",
  'input[name="user"]',
];

const DEFAULT_PASSWORD_SELECTORS = [
  'input[name="password"]',
  "#okta-signin-password",
  'input[name="credentials.passcode"]',
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

function createStepLogger(testName: string) {
  const start = Date.now();
  return (message: string) => {
    const elapsed = ((Date.now() - start) / 1000).toFixed(1);
    console.log(`[mcp-oauth-step][${testName}] ${message} (+${elapsed}s)`);
  };
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
    await page.waitForTimeout(100);
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
    await page.waitForTimeout(500);
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
    await page.waitForTimeout(1000);
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
    await page.waitForTimeout(750);
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
    .waitForLoadState("networkidle", { timeout: 15000 })
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
    isOnAppHost(page.url()) &&
    page.url().includes(returnSubstring) &&
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
        url.includes("/mcp/oauth/callback") ||
        (isOnAppHost(url) && url.includes(returnSubstring))
    );
  }

  if (!page.url().includes("/mcp/oauth/callback")) {
    logOauthEvent(page, "Waiting for OAuth callback redirect");
    await waitForUrlOrRedirect(
      "OAuth callback",
      60000,
      (url) =>
        url.includes("/mcp/oauth/callback") ||
        (isOnAppHost(url) && url.includes(returnSubstring))
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

  await waitForUrlOrRedirect(
    `return path ${returnSubstring}`,
    60000,
    (url) => isOnAppHost(url) && url.includes(returnSubstring)
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
  if (!page.url().includes(returnSubstring)) {
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

    const labelLocator = sectionLocator.getByLabel(new RegExp(toolName, "i"));
    if ((await labelLocator.count()) > 0) {
      await labelLocator.first().check({ force: true });
      continue;
    }

    throw new Error(`Unable to locate MCP tool checkbox for ${toolName}`);
  }
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
    const lineItems = page
      .locator(
        `${ACTION_POPOVER_SELECTOR} [data-testid^="tool-option-"] ${LINE_ITEM_SELECTOR}, ` +
          `${ACTION_POPOVER_SELECTOR} ${LINE_ITEM_SELECTOR}`
      )
      .filter({ hasText: toolRegex });
    const count = await lineItems.count();
    for (let i = 0; i < count; i++) {
      const lineItem = lineItems.nth(i);
      const textContent = await lineItem.evaluate(
        (el) => el.textContent?.trim().replace(/\s+/g, " ") || ""
      );
      if (toolRegex.test(textContent)) {
        return lineItem;
      }
    }
    await page.waitForTimeout(200);
  }

  return null;
}

async function logActionPopoverHtml(page: Page, context: string) {
  try {
    const html = await page
      .locator(ACTION_POPOVER_SELECTOR)
      .evaluate((node) => node.innerHTML || "");
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
    await page.waitForTimeout(200);
  }

  await page.keyboard.press("Escape").catch(() => {});
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
  const pollInterval = 250;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    if ((await locator.count()) > 0) {
      return locator;
    }
    await page.waitForTimeout(pollInterval);
  }

  return null;
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
  const serverLocator = await waitForServerRow(page, serverName, 10_000);
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

  await serverLocator.click();
  await waitForMcpSecondaryView(page);

  const mcpToolButton = await findMcpToolLineItemButton(page, toolName, 7000);
  if (mcpToolButton) {
    return mcpToolButton;
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
  await page.locator('[data-testid="action-management-toggle"]').click();
  await ensureActionPopoverInPrimaryView(page);
  const toolButton = await ensureToolOptionVisible(page, toolName, serverName);
  await expect(toolButton).toBeVisible({ timeout: 5000 });
  await closeActionsPopover(page);
}

async function reauthenticateFromChat(
  page: Page,
  serverName: string,
  returnSubstring: string
) {
  await page.locator('[data-testid="action-management-toggle"]').click();
  await ensureActionPopoverInPrimaryView(page);
  const serverLineItem = await waitForServerRow(page, serverName, 15_000);
  if (!serverLineItem) {
    const entries = await collectActionPopoverEntries(page);
    await logPageStateWithTag(
      page,
      `reauthenticateFromChat could not find ${serverName}; visible entries: ${JSON.stringify(
        entries
      )}`
    );
    throw new Error(
      `Unable to locate MCP server row ${serverName} while reauthenticating`
    );
  }
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
  await ensureActionPopoverInPrimaryView(page);
  const locatorToUse = await waitForServerRow(page, serverName, 15_000);

  if (!locatorToUse) {
    const entries = await collectActionPopoverEntries(page);
    await logPageStateWithTag(
      page,
      `ensureServerVisibleInActions could not find ${serverName}; visible entries: ${JSON.stringify(
        entries
      )}`
    );
    throw new Error(`Server ${serverName} not visible in actions popover`);
  }

  await expect(locatorToUse).toBeVisible({ timeout: 15000 });
  await page.keyboard.press("Escape").catch(() => {});
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

test.describe("MCP OAuth flows", () => {
  test.describe.configure({ mode: "serial" });

  let serverProcess: McpServerProcess | null = null;
  let adminArtifacts: FlowArtifacts | null = null;
  let curatorArtifacts: FlowArtifacts | null = null;
  let curatorCredentials: Credentials | null = null;
  let curatorTwoCredentials: Credentials | null = null;
  let curatorGroupId: string | null = null;
  let curatorTwoGroupId: string | null = null;

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
    const adminClient = new OnyxApiClient(adminPage);
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
      email: `pw-curator-${Date.now()}@test.com`,
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
    const curatorGroup = await adminClient.createUserGroup(
      `Playwright Curator Group ${Date.now()}`,
      [curatorRecord.id]
    );
    await adminClient.setCuratorStatus(
      curatorGroup.toString(),
      curatorRecord.id,
      true
    );
    curatorTwoCredentials = {
      email: `pw-curator-${Date.now()}-b@test.com`,
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
    const curatorTwoGroupId = await adminClient.createUserGroup(
      `Playwright Curator Group ${Date.now()}-2`,
      [curatorTwoRecord.id]
    );
    await adminClient.setCuratorStatus(
      curatorTwoGroupId.toString(),
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
    const logStep = createStepLogger("AdminFlow");
    test.skip(
      testInfo.project.name !== "admin",
      "MCP OAuth flows run only in admin project"
    );
    logStep("Starting admin MCP OAuth flow");

    await page.route("**/api/mcp/oauth/status*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ statuses: [] }),
      })
    );

    await page.context().clearCookies();
    logStep("Cleared cookies");
    await loginAs(page, "admin");
    await verifySessionUser(
      page,
      { email: TEST_ADMIN_CREDENTIALS.email, role: "admin" },
      "AdminFlow primary login"
    );
    const adminApiClient = new OnyxApiClient(page);
    logStep("Logged in as admin");

    const serverName = `PW MCP Admin ${Date.now()}`;
    const assistantName = `PW Admin Assistant ${Date.now()}`;

    await page.goto("http://localhost:3000/admin/actions/edit-mcp");
    await page.waitForURL("**/admin/actions/edit-mcp**", { timeout: 15000 });
    logStep("Opened MCP edit page");

    await page.locator('input[name="name"]').fill(serverName);
    await page
      .locator('input[name="description"]')
      .fill("Playwright MCP OAuth server (admin)");
    await page.locator('input[name="server_url"]').fill(runtimeMcpServerUrl);
    logStep(`Filled server URL: ${runtimeMcpServerUrl}`);

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
    logStep("Triggered OAuth connection");
    await completeOauthFlow(page, {
      expectReturnPathContains: "/admin/actions/edit-mcp",
      confirmConnected: async () => {
        await expect(page.getByTestId("connect-oauth-button")).toContainText(
          "OAuth Connected",
          { timeout: 15000 }
        );
      },
      scrollToBottomOnReturn: true,
    });
    logStep("Completed OAuth flow for MCP server");

    await page.getByRole("button", { name: "List Actions" }).click();
    await page.waitForURL("**listing_tools=true**", { timeout: 15000 });
    await scrollToBottom(page);
    await expect(page.getByText("Available Tools")).toBeVisible({
      timeout: 15000,
    });
    logStep("Listed available tools");

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

    const toolSearchInput = page.getByPlaceholder("Search tools...");
    await toolSearchInput.fill(TOOL_NAMES.admin);
    await page.waitForTimeout(500); // allow filtering to apply

    const adminToolCheckboxLocator = page
      .getByTestId(`tool-checkbox-${TOOL_NAMES.admin}`)
      .first();
    const checkboxCount = await adminToolCheckboxLocator.count();

    if (checkboxCount === 0) {
      await toolSearchInput.fill("");
      await page.waitForTimeout(500);
      const selectAllCheckbox = page
        .getByTestId("tool-checkbox-select-all")
        .first();
      await selectAllCheckbox.click({ force: true });
      await expect(selectAllCheckbox).toHaveAttribute("data-state", "checked", {
        timeout: 10000,
      });
      logStep("Selected tool via select-all fallback");
    } else {
      await adminToolCheckboxLocator.waitFor({
        state: "visible",
        timeout: 10000,
      });
      // Ensure the tool ends up selected before proceeding
      if (
        (await adminToolCheckboxLocator.getAttribute("data-state")) !==
        "checked"
      ) {
        await adminToolCheckboxLocator.click({ force: true });
      }
      await expect(adminToolCheckboxLocator).toHaveAttribute(
        "data-state",
        "checked",
        {
          timeout: 10000,
        }
      );
      logStep("Selected tool via direct checkbox");
    }

    await expect(page.getByText(/tool(s)? selected/i).first()).toContainText(
      "tool",
      { timeout: 10000 }
    );

    const createActionsButtonLocator = page.getByRole("button", {
      name: /(?:Create|Update) MCP Server Actions/,
    });
    const createButtonCount = await createActionsButtonLocator.count();
    if (createButtonCount === 0) {
      await logPageStateWithTag(
        page,
        "(Create|Update) MCP Server Actions button not found"
      );
      throw new Error("(Create|Update) MCP Server Actions button not found");
    }
    await expect(createActionsButtonLocator).toBeVisible({ timeout: 15000 });
    await expect(createActionsButtonLocator).toBeEnabled({ timeout: 15000 });
    try {
      await createActionsButtonLocator.click();
    } catch (error) {
      await logPageStateWithTag(
        page,
        "Failed to click Create MCP Server Actions button"
      );
      throw error;
    }

    await page.waitForURL("**/admin/actions**", { timeout: 20000 });
    await expect(
      page.getByText(serverName, { exact: false }).first()
    ).toBeVisible({ timeout: 20000 });
    logStep("Created/updated MCP server actions");

    const assistantEditorUrl =
      "http://localhost:3000/assistants/new?admin=true";
    let assistantPageLoaded = false;
    for (let attempt = 0; attempt < 2 && !assistantPageLoaded; attempt++) {
      await page.goto(assistantEditorUrl);
      try {
        await page.waitForURL("**/assistants/new**", {
          timeout: 15000,
        });
        assistantPageLoaded = true;
      } catch (error) {
        const currentUrl = page.url();
        if (currentUrl.includes("/assistants/new")) {
          assistantPageLoaded = true;
          break;
        }
        if (currentUrl.includes("/chat?from=login")) {
          await loginAs(page, "admin");
          await verifySessionUser(
            page,
            { email: TEST_ADMIN_CREDENTIALS.email, role: "admin" },
            "AdminFlow assistant editor relogin"
          );
          continue;
        }
        await logPageStateWithTag(
          page,
          "Timed out waiting for /assistants/new"
        );
        throw error;
      }
    }
    if (!assistantPageLoaded) {
      throw new Error("Unable to navigate to /assistants/new");
    }
    logStep("Assistant editor loaded");

    await page.locator('input[name="name"]').fill(assistantName);
    await page
      .locator('textarea[name="system_prompt"]')
      .fill("Assist with MCP OAuth testing.");
    await page
      .locator('input[name="description"]')
      .fill("Playwright admin MCP assistant.");

    await page
      .getByRole("button", { name: /Advanced Options/i })
      .click()
      .catch(() => {});
    await ensurePublicAssistant(page);
    await selectMcpTools(page, serverId, [TOOL_NAMES.admin]);

    await page.getByRole("button", { name: "Create" }).click();
    await page.waitForURL(
      (url) => {
        const href = typeof url === "string" ? url : url.toString();
        return (
          /\/chat\?assistantId=\d+/.test(href) ||
          href.includes("/admin/assistants")
        );
      },
      { timeout: 20000 }
    );

    let assistantId: number | null = null;
    if (/\/chat\?assistantId=\d+/.test(page.url())) {
      const chatUrl = new URL(page.url());
      const assistantIdParam = chatUrl.searchParams.get("assistantId");
      if (!assistantIdParam) {
        throw new Error("Assistant ID missing from chat redirect URL");
      }
      assistantId = Number(assistantIdParam);
      if (Number.isNaN(assistantId)) {
        throw new Error(`Invalid assistantId ${assistantIdParam}`);
      }
    } else {
      const assistantRecord = await waitForAssistantByName(
        adminApiClient,
        assistantName
      );
      assistantId = assistantRecord.id;
      await page.goto(`http://localhost:3000/chat?assistantId=${assistantId}`);
      await page.waitForURL(/\/chat\?assistantId=\d+/, { timeout: 20000 });
    }
    if (assistantId === null) {
      throw new Error("Assistant ID could not be determined");
    }
    logStep(`Assistant created with id ${assistantId}`);

    await waitForAssistantTools(adminApiClient, assistantName, [
      TOOL_NAMES.admin,
    ]);
    logStep("Confirmed assistant tools are available");

    await ensureServerVisibleInActions(page, serverName);
    await verifyMcpToolRowVisible(page, serverName, TOOL_NAMES.admin);
    logStep("Verified admin MCP tool row visible before reauth");

    await reauthenticateFromChat(
      page,
      serverName,
      `/chat?assistantId=${assistantId}`
    );
    await ensureServerVisibleInActions(page, serverName);
    await verifyMcpToolRowVisible(page, serverName, TOOL_NAMES.admin);
    logStep("Verified admin MCP tool row visible after reauth");

    await page.goto(
      `http://localhost:3000/admin/actions/edit-mcp?server_id=${serverId}`
    );
    await page.waitForURL("**listing_tools=true**", { timeout: 15000 });
    await scrollToBottom(page);
    await expect(page.getByText("Available Tools")).toBeVisible({
      timeout: 15000,
    });
    const retentionCheckbox = page
      .getByTestId(`tool-checkbox-${TOOL_NAMES.admin}`)
      .first();
    if ((await retentionCheckbox.count()) > 0) {
      const isVisible = await retentionCheckbox.isVisible().catch(() => false);
      if (isVisible) {
        await expect(retentionCheckbox).toHaveAttribute(
          "data-state",
          "checked"
        );
        logStep(
          "Verified MCP server retains tool selection (checkbox visible)"
        );
      } else {
        logStep(
          "Checkbox was found but not visible; skipping state assertion due to layout"
        );
      }
    } else {
      logStep(
        "Tool checkbox not found after returning to edit page; skipping state assertion"
      );
    }

    adminArtifacts = {
      serverId,
      serverName,
      assistantId,
      assistantName,
      toolName: TOOL_NAMES.admin,
    };
  });

  test("Curator flow with access isolation", async ({
    page,
    browser,
  }, testInfo) => {
    const logStep = createStepLogger("CuratorFlow");
    test.skip(
      testInfo.project.name !== "admin",
      "MCP OAuth flows run only in admin project"
    );
    logStep("Starting curator MCP OAuth flow");
    await page.route("**/api/mcp/oauth/status*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ statuses: [] }),
      })
    );

    if (!curatorCredentials || !curatorTwoCredentials) {
      test.skip(true, "Curator credentials were not initialized");
    }

    await page.context().clearCookies();
    logStep("Cleared cookies");
    await loginWithCredentials(
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
    const curatorApiClient = new OnyxApiClient(page);

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

      await page.goto("http://localhost:3000/admin/actions/edit-mcp");
      await page.waitForURL("**/admin/actions/edit-mcp**", { timeout: 15000 });
      logStep("Opened MCP edit page (curator)");

      await page.locator('input[name="name"]').fill(serverName);
      await page
        .locator('input[name="description"]')
        .fill("Playwright MCP OAuth server (curator)");
      await page
        .locator('input[name="server_url"]')
        .fill(curatorRuntimeMcpServerUrl);

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
      logStep("Triggered OAuth connect button");
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
      await scrollToBottom(page);
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

      // Click the checkbox and wait for it to be checked
      const curatorCheckbox = page.getByTestId(
        `tool-checkbox-${TOOL_NAMES.curator}`
      );
      await curatorCheckbox.waitFor({ state: "visible", timeout: 10000 });
      await curatorCheckbox.click();

      // Verify the checkbox is actually checked
      await expect(curatorCheckbox).toHaveAttribute("data-state", "checked", {
        timeout: 10000,
      });

      // Verify the selection count updated to show 1 tool selected
      await expect(page.getByText("1 tool selected")).toBeVisible({
        timeout: 10000,
      });
      logStep("Selected curator tool checkbox");

      await scrollToBottom(page);

      // Wait for the button to be enabled before clicking
      const createButton = page.getByRole("button", {
        name: /(?:Create|Update) MCP Server Actions/,
      });
      await expect(createButton).toBeEnabled({ timeout: 10000 });
      await createButton.click();
      logStep("Created MCP server actions (curator)");

      await page.waitForURL("**/admin/actions**", { timeout: 20000 });
      await expect(
        page.getByText(serverName, { exact: false }).first()
      ).toBeVisible({ timeout: 20000 });

      await page.goto("http://localhost:3000/assistants/new?admin=true");
      await page.waitForURL("**/assistants/new**", { timeout: 15000 });
      logStep("Assistant editor loaded (curator)");

      await page.locator('input[name="name"]').fill(assistantName);
      await page
        .locator('textarea[name="system_prompt"]')
        .fill("Curator MCP OAuth assistant.");
      await page
        .locator('input[name="description"]')
        .fill("Playwright curator MCP assistant.");

      await page
        .getByRole("button", { name: /Advanced Options/i })
        .click()
        .catch(() => {});
      await ensurePublicAssistant(page);
      await selectMcpTools(page, serverId, [TOOL_NAMES.curator]);

      await page.getByRole("button", { name: "Create" }).click();
      await page.waitForURL(
        (url) => {
          const href = typeof url === "string" ? url : url.toString();
          return (
            /\/chat\?assistantId=\d+/.test(href) ||
            href.includes("/admin/assistants")
          );
        },
        { timeout: 20000 }
      );

      let assistantId: number | null = null;
      if (/\/chat\?assistantId=\d+/.test(page.url())) {
        const chatUrl = new URL(page.url());
        const assistantIdParam = chatUrl.searchParams.get("assistantId");
        if (!assistantIdParam) {
          throw new Error("Assistant ID missing from chat redirect URL");
        }
        assistantId = Number(assistantIdParam);
        if (Number.isNaN(assistantId)) {
          throw new Error(`Invalid assistantId ${assistantIdParam}`);
        }
      } else {
        const assistantRecord = await waitForAssistantByName(
          curatorApiClient,
          assistantName
        );
        assistantId = assistantRecord.id;
        await page.goto(
          `http://localhost:3000/chat?assistantId=${assistantId}`
        );
        await page.waitForURL(/\/chat\?assistantId=\d+/, { timeout: 20000 });
      }
      if (assistantId === null) {
        throw new Error("Assistant ID could not be determined");
      }

      logStep(`Curator assistant created with id ${assistantId}`);

      await waitForAssistantTools(curatorApiClient, assistantName, [
        TOOL_NAMES.curator,
      ]);

      await ensureServerVisibleInActions(page, serverName);
      await verifyMcpToolRowVisible(page, serverName, TOOL_NAMES.curator);
      logStep("Verified curator MCP tool row visible before reauth");

      await reauthenticateFromChat(
        page,
        serverName,
        `/chat?assistantId=${assistantId}`
      );
      await ensureServerVisibleInActions(page, serverName);
      await verifyMcpToolRowVisible(page, serverName, TOOL_NAMES.curator);
      logStep("Verified curator MCP tool row visible after reauth");

      curatorArtifacts = {
        serverId,
        serverName,
        assistantId,
        assistantName,
        toolName: TOOL_NAMES.curator,
      };

      // Verify isolation: second curator must not be able to edit first curator's server
      const curatorTwoContext = await browser.newContext();
      const curatorTwoPage = await curatorTwoContext.newPage();
      await logoutSession(
        curatorTwoPage,
        "CuratorFlow secondary pre-login logout"
      );
      await loginWithCredentials(
        curatorTwoPage,
        curatorTwoCredentials!.email,
        curatorTwoCredentials!.password
      );
      await verifySessionUser(
        curatorTwoPage,
        { email: curatorTwoCredentials!.email, role: "curator" },
        "CuratorFlow secondary login"
      );
      await curatorTwoPage.goto("http://localhost:3000/admin/actions");
      const serverLocator = curatorTwoPage.getByText(serverName, {
        exact: false,
      });
      const visibleCount = await serverLocator.count();
      await expect(visibleCount).toBeGreaterThan(0);

      const editResponse = await curatorTwoPage.request.get(
        `http://localhost:3000/api/admin/mcp/servers/${serverId}`
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
    const logStep = createStepLogger("UserFlow");
    test.skip(
      testInfo.project.name !== "admin",
      "MCP OAuth flows run only in admin project"
    );
    logStep("Starting end-user MCP OAuth flow");
    await page.route("**/api/mcp/oauth/status*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ statuses: [] }),
      })
    );

    test.skip(!adminArtifacts, "Admin flow must complete before user test");

    await page.context().clearCookies();
    logStep("Cleared cookies");
    await loginAs(page, "user");
    logStep("Logged in as user");

    const assistantId = adminArtifacts!.assistantId;
    const serverName = adminArtifacts!.serverName;
    const toolName = adminArtifacts!.toolName;

    await page.goto(`http://localhost:3000/chat?assistantId=${assistantId}`, {
      waitUntil: "load",
    });
    await ensureServerVisibleInActions(page, serverName);
    logStep("Opened chat as user and ensured server visible");

    await page.locator('[data-testid="action-management-toggle"]').click();
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

    const navPromise = page
      .waitForNavigation({ waitUntil: "load" })
      .catch(() => null);
    await serverLineItem.click();
    await navPromise;
    await completeOauthFlow(page, {
      expectReturnPathContains: `/chat?assistantId=${assistantId}`,
    });
    logStep("Completed user OAuth reauthentication");

    await verifyMcpToolRowVisible(page, serverName, toolName);
    logStep("Verified user MCP tool row visible after reauth");
  });
});
