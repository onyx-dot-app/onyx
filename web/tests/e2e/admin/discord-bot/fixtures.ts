/**
 * Playwright fixtures for Discord bot admin UI tests.
 */

import { test as base, expect, Page } from "@playwright/test";
import { loginAs } from "../../utils/auth";

// Extend base test with Discord bot fixtures
export const test = base.extend<{
  adminPage: Page;
  seededGuild: { id: number; name: string; registrationKey: string };
}>({
  // Admin page fixture - logs in as admin using standard auth
  adminPage: async ({ page }, use) => {
    await loginAs(page, "admin");
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
