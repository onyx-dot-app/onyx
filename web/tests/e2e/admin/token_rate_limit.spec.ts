import { test, expect } from "@playwright/test";
import { ChatPage } from "@tests/e2e/chat/ChatPage";

/**
 * Rate-limit enforcement is a server-side gate, so this is a REAL e2e: it does
 * NOT mock the chat endpoint (mocking would bypass the gate). It creates a tiny
 * per-user token budget, sends real chats until usage accrues past it, and
 * asserts the structured 429 renders as the "usage limit reached" banner.
 *
 * Requires a working LLM provider in the e2e environment (chats must actually
 * produce token usage). The same admin user creates the limit and sends the
 * chats, so the USER scope applies to them.
 */
test.use({ storageState: "admin_auth.json" });

const RATE_LIMIT_API = "/api/admin/token-rate-limits";

test.describe("usage budget blocks chat", () => {
  let limitId: number | undefined;

  test.afterEach(async ({ page }) => {
    if (limitId != null) {
      await page.request.delete(`${RATE_LIMIT_API}/rate-limit/${limitId}`);
      limitId = undefined;
    }
  });

  test("a per-user token budget surfaces the usage-limit banner", async ({
    page,
  }) => {
    // 1) Tiny per-user token budget (1 => 1,000 tokens enforced).
    const res = await page.request.post(`${RATE_LIMIT_API}/users`, {
      data: {
        enabled: true,
        token_budget: 1,
        period_hours: 168,
        cost_budget_cents: null,
      },
    });
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    limitId = body.token_id ?? body.id;

    const chat = new ChatPage(page);
    await chat.goto();

    // 2) Usage accrues server-side and the gate reads the recorded total before
    //    each request, so the first turn starts at 0 and it takes a few turns to
    //    cross the budget. Stop as soon as the banner appears.
    const banner = page.getByText(/you've reached the usage budget/i);
    for (let turn = 0; turn < 8 && !(await banner.isVisible()); turn++) {
      await chat.inputBar.fill(`write a few sentences about topic ${turn}`);
      await chat.inputBar.send();
      await Promise.race([
        banner.waitFor({ state: "visible", timeout: 45_000 }).catch(() => {}),
        chat
          .aiMessage(turn)
          .waitFor({ state: "visible", timeout: 45_000 })
          .catch(() => {}),
      ]);
    }

    // 3) The structured 429 renders as a friendly, scope-aware banner.
    await expect(banner).toBeVisible();
    await expect(page.getByText(/your account/i)).toBeVisible();
  });
});
