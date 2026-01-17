/**
 * Playwright fixtures for Discord bot admin UI tests.
 *
 * Note: These tests run under the "admin" project which uses storageState: "admin_auth.json",
 * so authentication is already handled by the global setup. No need to call loginAs().
 */

import { test as base, expect, Page } from "@playwright/test";

// Extend base test with Discord bot fixtures
export const test = base.extend<{
  adminPage: Page;
  seededGuild: { id: number; name: string; registrationKey: string };
}>({
  // Admin page fixture - uses the already-authenticated page from storage state
  adminPage: async ({ page }, use) => {
    await use(page);
  },

  // Seeded guild fixture - creates a guild via API for testing
  seededGuild: async ({ request }, use) => {
    // Create a new guild config via API
    const createResponse = await request.post(
      "/api/manage/admin/discord-bot/guilds",
      {
        headers: {
          "Content-Type": "application/json",
        },
      }
    );

    if (!createResponse.ok()) {
      throw new Error(
        `Failed to create test guild: ${createResponse.status()} ${await createResponse.text()}`
      );
    }

    const guild = await createResponse.json();

    await use({
      id: guild.id,
      name: guild.guild_name || "Pending",
      registrationKey: guild.registration_key,
    });

    // Cleanup - delete the guild after test
    await request.delete(`/api/manage/admin/discord-bot/guilds/${guild.id}`);
  },
});

export { expect };
