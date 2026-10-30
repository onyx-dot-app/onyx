import { test } from "@playwright/test";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { AdminSpendingLimitsPage } from "@tests/e2e/pages/AdminSpendingLimitsPage";

/**
 * Spending limits are a server-side gate, so this is a real e2e: it sets a tiny
 * per-user token budget on the admin page, checks it persists, then sends real
 * chats until usage passes it and the usage-limit banner shows.
 *
 * Requires a working LLM provider in the e2e environment. The same admin user
 * sets the limit and chats, so the per-user default applies to them. The limit
 * applies to every user, so the spec runs @exclusive, apart from other chats.
 */
test.use({ storageState: "admin_auth.json" });

const PER_USER_CARD = "workspace/per-user";

test.describe("spending limits block chat @exclusive", () => {
  test.afterEach(async ({ page }) => {
    await page.request.put(`/api/admin/spending-limits/${PER_USER_CARD}`, {
      data: { enabled: true, limits: [] },
    });
  });

  test("a per-user token limit saved on the page surfaces the usage-limit banner", async ({
    page,
  }) => {
    const limits = new AdminSpendingLimitsPage(page);
    await limits.goto();
    // 1 => 1,000 tokens enforced.
    await limits.addTokenLimit(PER_USER_CARD, 1);
    await limits.save(PER_USER_CARD);
    await limits.reload();
    await limits.expectTokenLimit(PER_USER_CARD, 1);

    const chat = new ChatPage(page);
    await chat.goto();
    await chat.sendUntilUsageLimit(8);
    await chat.expectAccountUsageLimit();
  });
});
