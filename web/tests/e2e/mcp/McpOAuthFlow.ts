/**
 * Encapsulates the external-IdP OAuth dance for MCP servers: driving the IdP
 * login form, waiting through the connect → IdP → callback → return-path
 * redirect chain, and re-authenticating from the chat actions popover.
 *
 * The redirect/timing logic here is ported from the original mcp_oauth_flow
 * spec — it encodes hard-won handling of IdP quirks and should not be
 * casually rewritten. It is exposed as a class so specs call
 * `oauthFlow.completeFlow(...)` instead of inlining ~400 lines of glue.
 */

import { type Page, expect } from "@playwright/test";
import { logPageState } from "@tests/e2e/utils/pageStateLogger";
import { ActionsPopover } from "@tests/e2e/pages/ActionsPopover";

const REQUIRED_ENV_VARS = [
  "MCP_OAUTH_CLIENT_ID",
  "MCP_OAUTH_CLIENT_SECRET",
  "MCP_OAUTH_ISSUER",
  "MCP_OAUTH_JWKS_URI",
  "MCP_OAUTH_USERNAME",
  "MCP_OAUTH_PASSWORD",
];

export interface McpOAuthConfig {
  clientId: string;
  clientSecret: string;
  idpUsername: string;
  idpPassword: string;
  appBaseUrl: string;
  appHost: string;
  idpHost: string;
}

/**
 * Read + validate the OAuth env vars the MCP OAuth tests require. Throws if any
 * are missing so the spec fails loudly during setup rather than mid-flow.
 */
export function getMcpOAuthConfig(): McpOAuthConfig {
  const missing = REQUIRED_ENV_VARS.filter((envVar) => !process.env[envVar]);
  if (missing.length > 0) {
    throw new Error(
      `Missing required environment variables for MCP OAuth tests: ${missing.join(
        ", "
      )}`
    );
  }
  const appBaseUrl = process.env.MCP_TEST_APP_BASE || "http://localhost:3000";
  return {
    clientId: process.env.MCP_OAUTH_CLIENT_ID!,
    clientSecret: process.env.MCP_OAUTH_CLIENT_SECRET!,
    idpUsername: process.env.MCP_OAUTH_USERNAME!,
    idpPassword: process.env.MCP_OAUTH_PASSWORD!,
    appBaseUrl,
    appHost: new URL(appBaseUrl).host,
    idpHost: new URL(process.env.MCP_OAUTH_ISSUER!).host,
  };
}

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

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

// Cap every IdP form interaction. Playwright's default action timeout is
// unbounded, so a field/button that never becomes actionable — e.g. a real Okta
// org re-rendering its "Sign in" button mid-submit — makes `click()`/`fill()`
// hang until the whole test times out (observed: a submit click eating the full
// 300s budget). Bounding each action lets it fail fast so the password-retry
// loop and Enter-key fallback can recover, and so per-test retries get real
// budget instead of one long hang.
const IDP_ACTION_TIMEOUT_MS = Number(
  process.env.MCP_OAUTH_IDP_ACTION_TIMEOUT_MS || 15_000
);

export interface CompleteFlowOptions {
  expectReturnPathContains: string;
  confirmConnected?: () => Promise<void>;
  scrollToBottomOnReturn?: boolean;
}

export class McpOAuthFlow {
  readonly page: Page;
  readonly config: McpOAuthConfig;

  private readonly quickConfirmTimeoutMs = Number(
    process.env.MCP_OAUTH_QUICK_CONFIRM_TIMEOUT_MS || 2000
  );
  private readonly postClickUrlChangeWaitMs = Number(
    process.env.MCP_OAUTH_POST_CLICK_URL_CHANGE_WAIT_MS || 5000
  );

  constructor(page: Page, config: McpOAuthConfig = getMcpOAuthConfig()) {
    this.page = page;
    this.config = config;
  }

  private log(message: string): void {
    console.log(`[mcp-oauth] ${message} url=${this.page.url()}`);
  }

  private isOnHost(url: string, host: string): boolean {
    try {
      return new URL(url).host === host;
    } catch {
      return false;
    }
  }

  private isOnAppHost(url: string): boolean {
    return this.isOnHost(url, this.config.appHost);
  }

  private isOnIdpHost(url: string): boolean {
    return this.isOnHost(url, this.config.idpHost);
  }

  // ---------------------------------------------------------------------------
  // Low-level form helpers
  // ---------------------------------------------------------------------------

  private async fillFirstVisible(
    selectors: string[],
    value: string
  ): Promise<boolean> {
    for (const selector of selectors) {
      const locator = this.page.locator(selector).first();
      if ((await locator.count()) === 0) continue;
      let visible = await locator.isVisible().catch(() => false);
      if (!visible) {
        try {
          await locator.waitFor({ state: "visible", timeout: 500 });
          visible = true;
        } catch {
          continue;
        }
      }
      const existing = await locator
        .inputValue()
        .catch(() => "")
        .then((val) => val ?? "");
      if (existing !== value) {
        await locator.fill(value, { timeout: IDP_ACTION_TIMEOUT_MS });
      }
      return true;
    }
    return false;
  }

  private async clickFirstVisible(
    selectors: string[],
    options: { optional?: boolean } = {}
  ): Promise<boolean> {
    for (const selector of selectors) {
      const locator = this.page.locator(selector).first();
      if ((await locator.count()) === 0) continue;
      let visible = await locator.isVisible().catch(() => false);
      if (!visible) {
        try {
          await locator.waitFor({ state: "visible", timeout: 500 });
          visible = true;
        } catch {
          continue;
        }
      }
      try {
        await locator.click({ timeout: IDP_ACTION_TIMEOUT_MS });
        return true;
      } catch (err) {
        if (!options.optional) throw err;
      }
    }
    return false;
  }

  private async waitForAnySelector(
    selectors: string[],
    options: { timeout?: number } = {}
  ): Promise<boolean> {
    const deadline = Date.now() + (options.timeout ?? 5000);
    while (Date.now() < deadline) {
      for (const selector of selectors) {
        const locator = this.page.locator(selector).first();
        if ((await locator.count()) === 0) continue;
        if (await locator.isVisible().catch(() => false)) {
          return true;
        }
      }
      await this.page.waitForTimeout(50);
    }
    return false;
  }

  private async scrollToBottom(): Promise<void> {
    await this.page
      .evaluate(() => {
        const section = document.querySelector(
          '[data-testid="available-tools-section"]'
        );
        if (section && "scrollIntoView" in section) {
          section.scrollIntoView({ behavior: "instant", block: "end" });
        } else {
          window.scrollTo(0, document.body.scrollHeight);
        }
      })
      .catch(() => {});
  }

  /** Click `action`, then briefly wait to log whether the URL changed. */
  async clickAndWaitForPossibleUrlChange(
    action: () => Promise<void>,
    context: string
  ): Promise<void> {
    const startingUrl = this.page.url();
    const urlChange = this.page
      .waitForURL((url) => url.toString() !== startingUrl, {
        timeout: this.postClickUrlChangeWaitMs,
      })
      .then(() => true)
      .catch(() => false);
    await action();
    const changed = await urlChange;
    this.log(`${context}: url changed=${changed}`);
  }

  // ---------------------------------------------------------------------------
  // IdP login
  // ---------------------------------------------------------------------------

  async performIdpLogin(): Promise<void> {
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

    await this.page
      .waitForLoadState("domcontentloaded", { timeout: 1000 })
      .catch(() => {});

    const sawLoginForm = await this.waitForAnySelector(usernameSelectors, {
      timeout: 1000,
    });
    // The mock OIDC IdP has no login page — /authorize auto-issues a code and
    // bounces straight back to the app. If no username field appeared and we've
    // already left the IdP host, there's nothing to drive; return so the caller
    // proceeds to wait for the OAuth callback instead of timing out on a form
    // that will never render. The real-IdP path (form present) is unchanged.
    if (!sawLoginForm && !this.isOnIdpHost(this.page.url())) {
      this.log("performIdpLogin: no login form (auto-issued); skipping");
      return;
    }

    const usernameFilled = await this.fillFirstVisible(
      usernameSelectors,
      this.config.idpUsername
    );
    if (usernameFilled) {
      await this.clickFirstVisible(nextSelectors, { optional: true });
      await this.waitForAnySelector(passwordSelectors, { timeout: 2000 });
    }

    const submitPasswordAttempt = async (): Promise<boolean> => {
      const ready = await this.waitForAnySelector(passwordSelectors, {
        timeout: 8000,
      });
      if (!ready) return false;
      const filled = await this.fillFirstVisible(
        passwordSelectors,
        this.config.idpPassword
      );
      if (!filled) return false;
      const clickedSubmit = await this.clickFirstVisible(submitSelectors, {
        optional: true,
      });
      if (!clickedSubmit) {
        const passwordLocator = this.page
          .locator(passwordSelectorString)
          .first();
        if ((await passwordLocator.count()) > 0) {
          await passwordLocator
            .press("Enter", { timeout: IDP_ACTION_TIMEOUT_MS })
            .catch(() => {});
        } else {
          await this.page.keyboard.press("Enter").catch(() => {});
        }
      }
      await this.page
        .waitForLoadState("domcontentloaded", { timeout: 15000 })
        .catch(() => {});
      return true;
    };

    const hasVisiblePasswordField = async (): Promise<boolean> => {
      const locator = this.page.locator(passwordSelectorString);
      const count = await locator.count();
      for (let i = 0; i < count; i++) {
        if (
          await locator
            .nth(i)
            .isVisible()
            .catch(() => false)
        ) {
          return true;
        }
      }
      return false;
    };

    await submitPasswordAttempt();

    const MAX_PASSWORD_RETRIES = 3;
    for (let retry = 1; retry <= MAX_PASSWORD_RETRIES; retry++) {
      await this.page.waitForTimeout(250);
      if (!this.isOnIdpHost(this.page.url())) break;
      if (!(await hasVisiblePasswordField())) break;
      const success = await submitPasswordAttempt();
      if (!success) break;
    }

    await this.clickFirstVisible(consentSelectors, { optional: true });
    await this.page
      .waitForLoadState("networkidle", { timeout: 10000 })
      .catch(() => {});
  }

  // ---------------------------------------------------------------------------
  // Full connect → callback → return-path flow
  // ---------------------------------------------------------------------------

  async completeFlow(options: CompleteFlowOptions): Promise<void> {
    const returnSubstring = options.expectReturnPathContains;
    const matchesReturnPath = (url: string): boolean => {
      if (!this.isOnAppHost(url)) return false;
      if (url.includes(returnSubstring)) return true;
      // Re-auth flows can land on a chat-session URL instead of agentId URL.
      return (
        returnSubstring.includes("/app?agentId=") &&
        url.includes("/app?chatId=")
      );
    };

    const waitForUrlOrRedirect = async (
      description: string,
      timeout: number,
      predicate: (url: string) => boolean
    ): Promise<void> => {
      if (predicate(this.page.url())) return;
      try {
        await this.page.waitForURL(
          (url) => {
            try {
              return predicate(url.toString());
            } catch {
              return false;
            }
          },
          { timeout }
        );
      } catch (error) {
        if (predicate(this.page.url())) return;
        await logPageState(
          this.page,
          `Timeout waiting for ${description}`,
          "[mcp-oauth]"
        );
        throw error;
      }
    };

    const tryConfirmConnected = async (
      suppressErrors: boolean
    ): Promise<boolean> => {
      if (!options.confirmConnected) return false;
      if (this.page.isClosed() || !this.isOnAppHost(this.page.url())) {
        if (suppressErrors) return false;
        throw new Error("confirmConnected requested while not on app host");
      }
      const confirmPromise = options
        .confirmConnected()
        .then(() => ({ status: "success" as const }))
        .catch((error) => ({ status: "error" as const, error }));
      if (suppressErrors) {
        const result = await Promise.race([
          confirmPromise,
          delay(this.quickConfirmTimeoutMs).then(() => ({
            status: "timeout" as const,
          })),
        ]);
        return result.status === "success";
      }
      const finalResult = await confirmPromise;
      if (finalResult.status === "success") return true;
      throw finalResult.error;
    };

    if (matchesReturnPath(this.page.url())) {
      // Already on the return path. With no confirmConnected check there is
      // nothing left to wait for, so a finished round-trip can exit here
      // instead of waiting out the (now-impossible) IdP redirect.
      if (!options.confirmConnected) {
        return;
      }
      if (await tryConfirmConnected(true)) {
        return;
      }
    }

    if (
      this.isOnAppHost(this.page.url()) &&
      !this.page.url().includes("/mcp/oauth/callback")
    ) {
      await waitForUrlOrRedirect("IdP redirect", 10000, (url) => {
        const parsed = new URL(url);
        return (
          parsed.host !== this.config.appHost ||
          parsed.pathname.includes("/mcp/oauth/callback")
        );
      });
    }

    if (!this.isOnAppHost(this.page.url())) {
      await this.performIdpLogin();
    } else if (!this.page.url().includes("/mcp/oauth/callback")) {
      await waitForUrlOrRedirect(
        "OAuth callback",
        60000,
        (url) => url.includes("/mcp/oauth/callback") || matchesReturnPath(url)
      );
    }

    if (!this.page.url().includes("/mcp/oauth/callback")) {
      await waitForUrlOrRedirect(
        "OAuth callback",
        60000,
        (url) => url.includes("/mcp/oauth/callback") || matchesReturnPath(url)
      );
    }

    await this.page
      .waitForLoadState("domcontentloaded", { timeout: 5000 })
      .catch(() => {});
    await waitForUrlOrRedirect(`return path ${returnSubstring}`, 60000, (url) =>
      matchesReturnPath(url)
    );
    await this.page
      .waitForLoadState("domcontentloaded", { timeout: 5000 })
      .catch(() => {});

    if (!matchesReturnPath(this.page.url())) {
      throw new Error(
        `Redirected but final URL (${this.page.url()}) does not contain expected substring ${returnSubstring}`
      );
    }

    if (options.scrollToBottomOnReturn) {
      await this.scrollToBottom();
    }

    await tryConfirmConnected(false);
  }

  // ---------------------------------------------------------------------------
  // Re-authentication from the chat actions popover
  // ---------------------------------------------------------------------------

  /**
   * Re-authenticate an OAuth MCP server from chat. Clicking the server row may
   * either kick off OAuth directly or drill into the tool list with a
   * "Re-Authenticate" footer row; both are handled.
   */
  async reauthenticateFromChat(
    actions: ActionsPopover,
    serverName: string,
    returnSubstring: string
  ): Promise<void> {
    const outcome = await actions.clickServerRowDetectingNavigation(serverName);

    // An already-authenticated server drills into its tool list, where a
    // "Re-Authenticate" footer row kicks off OAuth. Only take that path if the
    // tool list actually appears.
    if (outcome === "drilled" && (await actions.toolListVisible(3000))) {
      await this.clickAndWaitForPossibleUrlChange(
        () => actions.clickReauthRow(),
        "Re-authenticate click"
      );
    }

    // For an unauthenticated server the row click already started OAuth. With
    // the auto-issuing mock IdP the round-trip can complete before any url
    // change is observable, so clickServerRowDetectingNavigation may report a
    // false "drilled". completeFlow drives the redirect chain and tolerates an
    // already-completed round-trip (it returns immediately if we are back on
    // the return path), so it handles both the navigated and false-drilled cases.
    await this.completeFlow({ expectReturnPathContains: returnSubstring });
  }
}
