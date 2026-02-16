import { test, expect } from "@playwright/test";
import {
  expectScreenshot,
  expectElementScreenshot,
} from "./utils/visualRegression";
import { GREETING_MESSAGES } from "@/lib/chat/greetingMessages";

test.use({ storageState: "admin_auth.json" });
test.describe.configure({ mode: "parallel" });

const THEMES = ["light", "dark"] as const;

for (const theme of THEMES) {
  test.describe(`Welcome page — /app (${theme} mode)`, () => {
    test.beforeEach(async ({ page }) => {
      // Inject theme into localStorage so next-themes picks it up immediately.
      await page.addInitScript((t: string) => {
        localStorage.setItem("theme", t);
      }, theme);

      await page.goto("/app");
      await page.waitForLoadState("networkidle");
    });

    // ── Full-page screenshot ──────────────────────────────────────────

    test("full page visual snapshot", async ({ page }) => {
      // Wait for the welcome greeting to ensure the page has fully rendered
      await page
        .getByTestId("chat-intro")
        .waitFor({ state: "visible", timeout: 10000 });

      await expectScreenshot(page, {
        name: `welcome-${theme}-full-page`,
        hide: ['[data-testid="onyx-logo"]'], // greeting text is random, hide to prevent size variation
      });
    });

    // ── Input bar element screenshot ──────────────────────────────────

    test("input bar element snapshot", async ({ page }) => {
      const inputBar = page.locator("#onyx-chat-input");
      await inputBar.waitFor({ state: "visible", timeout: 10000 });

      await expectElementScreenshot(inputBar, {
        name: `welcome-${theme}-input-bar`,
      });
    });

    // ── Sidebar element screenshot ────────────────────────────────────

    test("sidebar element snapshot", async ({ page }) => {
      // SidebarWrapper renders a div with `group/SidebarWrapper` Tailwind
      // group class — this is the most stable identifier for the sidebar
      // container element.
      const sidebar = page.locator(".group\\/SidebarWrapper");
      await sidebar.waitFor({ state: "visible", timeout: 10000 });

      await expectElementScreenshot(sidebar, {
        name: `welcome-${theme}-sidebar`,
      });
    });

    // ── Content assertions ────────────────────────────────────────────

    test("displays greeting from default assistant", async ({ page }) => {
      const greetingContainer = page.getByTestId("onyx-logo");
      await greetingContainer.waitFor({ state: "visible", timeout: 10000 });

      const text = await greetingContainer.textContent();
      expect(GREETING_MESSAGES).toContain(text?.trim());
    });

    test("chat input is visible and focusable", async ({ page }) => {
      const textarea = page.locator("#onyx-chat-input-textarea");
      await expect(textarea).toBeVisible({ timeout: 10000 });

      await textarea.click();
      await expect(textarea).toBeFocused();
    });

    test("new session button is visible in the sidebar", async ({ page }) => {
      const newSessionBtn = page.getByTestId("AppSidebar/new-session");
      await expect(newSessionBtn).toBeVisible({ timeout: 10000 });
    });

    test.skip("send button is visible in the input bar", async ({ page }) => {
      const sendButton = page.locator("#onyx-chat-input-send-button");
      await expect(sendButton).toBeVisible({ timeout: 10000 });

      await expectElementScreenshot(sendButton, {
        name: `welcome-${theme}-send-button`,
      });
    });
  });
}
