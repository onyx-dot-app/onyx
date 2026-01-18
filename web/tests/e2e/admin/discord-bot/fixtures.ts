/**
 * Playwright fixtures for Discord bot admin UI tests.
 *
 * These fixtures provide:
 * - Authenticated admin page
 * - API client for backend operations
 * - Mock data for guilds and channels (since real Discord integration isn't available in tests)
 */

import { test as base, expect, Page } from "@playwright/test";
import { loginAs } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

/**
 * Mock data types matching backend response schemas
 */
interface MockGuild {
  id: number;
  guild_id: string | null;
  guild_name: string | null;
  registration_key: string;
  registered_at: string | null;
  enabled: boolean;
  default_persona_id: number | null;
}

interface MockChannel {
  id: number;
  channel_id: string;
  channel_name: string;
  channel_type: "text" | "forum";
  is_private: boolean;
  enabled: boolean;
  require_bot_invocation: boolean;
  thread_only_mode: boolean;
  persona_override_id: number | null;
}

/**
 * Constants for mock data
 */
const MOCK_GUILD_ID = 999;

/**
 * Helper to authenticate and clear cookies
 */
async function authenticateAdmin(page: Page): Promise<void> {
  await page.context().clearCookies();
  await loginAs(page, "admin");
}

/**
 * Helper to create JSON response
 */
function jsonResponse(data: unknown, status = 200) {
  return {
    status,
    contentType: "application/json",
    body: JSON.stringify(data),
  };
}

/**
 * Creates mock channel data for a registered guild
 */
function createMockChannels(): MockChannel[] {
  return [
    {
      id: 1,
      channel_id: "1234567890123456789",
      channel_name: "general",
      channel_type: "text",
      is_private: false,
      enabled: true,
      require_bot_invocation: false,
      thread_only_mode: false,
      persona_override_id: null,
    },
    {
      id: 2,
      channel_id: "1234567890123456790",
      channel_name: "help-forum",
      channel_type: "forum",
      is_private: false,
      enabled: false,
      require_bot_invocation: true,
      thread_only_mode: false,
      persona_override_id: null,
    },
    {
      id: 3,
      channel_id: "1234567890123456791",
      channel_name: "private-support",
      channel_type: "text",
      is_private: true,
      enabled: true,
      require_bot_invocation: true,
      thread_only_mode: true,
      persona_override_id: null,
    },
  ];
}

/**
 * Creates a mock registered guild
 */
function createMockRegisteredGuild(id: number): MockGuild {
  return {
    id,
    guild_id: "987654321098765432",
    guild_name: "Test Discord Server",
    registration_key: "test-key-12345",
    registered_at: new Date().toISOString(),
    enabled: true,
    default_persona_id: null,
  };
}

/**
 * Creates a mock pending guild (not yet registered)
 */
function createMockPendingGuild(id: number): MockGuild {
  return {
    id,
    guild_id: null,
    guild_name: null,
    registration_key: "pending-key-67890",
    registered_at: null,
    enabled: false,
    default_persona_id: null,
  };
}

// Extend base test with Discord bot fixtures
export const test = base.extend<{
  adminPage: Page;
  apiClient: OnyxApiClient;
  seededGuild: { id: number; name: string; registrationKey: string };
  mockRegisteredGuild: {
    id: number;
    name: string;
    guild: MockGuild;
    channels: MockChannel[];
  };
  mockBotConfigured: boolean;
}>({
  // Admin page fixture - ensures proper authentication before each test
  adminPage: async ({ page }, use) => {
    await authenticateAdmin(page);
    await use(page);
  },

  // API client fixture - provides access to OnyxApiClient for backend operations
  apiClient: async ({ page }, use) => {
    await authenticateAdmin(page);
    const client = new OnyxApiClient(page);
    await use(client);
  },

  // Seeded guild fixture - creates a real pending guild via API
  seededGuild: async ({ page }, use) => {
    await authenticateAdmin(page);

    const apiClient = new OnyxApiClient(page);
    const guild = await apiClient.createDiscordGuild();

    await use({
      id: guild.id,
      name: guild.guild_name || "Pending",
      registrationKey: guild.registration_key,
    });

    // Cleanup
    await apiClient.deleteDiscordGuild(guild.id);
  },

  // Mock registered guild fixture - provides a fully mocked registered guild with channels
  // This intercepts API calls to simulate a registered guild without needing Discord
  mockRegisteredGuild: async ({ page }, use) => {
    await authenticateAdmin(page);

    // Use a mutable object so we can update it when PATCH requests come in
    let mockGuild = createMockRegisteredGuild(MOCK_GUILD_ID);
    const mockChannels = createMockChannels();

    // Mock the guild list endpoint
    await page.route(
      "**/api/manage/admin/discord-bot/guilds",
      async (route) => {
        const method = route.request().method();
        if (method === "GET") {
          await route.fulfill(jsonResponse([mockGuild]));
        } else if (method === "POST") {
          // Allow creating new guilds - return a new pending guild
          const newGuild = createMockPendingGuild(MOCK_GUILD_ID + 1);
          await route.fulfill(jsonResponse(newGuild));
        } else {
          await route.continue();
        }
      }
    );

    // Mock the specific guild endpoint
    await page.route(
      `**/api/manage/admin/discord-bot/guilds/${MOCK_GUILD_ID}`,
      async (route) => {
        const method = route.request().method();
        if (method === "GET") {
          await route.fulfill(jsonResponse(mockGuild));
        } else if (method === "PATCH") {
          // Handle updates - merge with current state and update mockGuild
          const body = (await route.request().postDataJSON()) || {};
          mockGuild = { ...mockGuild, ...body };
          await route.fulfill(jsonResponse(mockGuild));
        } else if (method === "DELETE") {
          await route.fulfill({ status: 204, body: "" });
        } else {
          await route.continue();
        }
      }
    );

    // Mock the channels endpoint for this guild
    await page.route(
      `**/api/manage/admin/discord-bot/guilds/${MOCK_GUILD_ID}/channels`,
      async (route) => {
        await route.fulfill(jsonResponse(mockChannels));
      }
    );

    // Mock channel update endpoint
    await page.route(
      `**/api/manage/admin/discord-bot/guilds/${MOCK_GUILD_ID}/channels/*`,
      async (route) => {
        if (route.request().method() === "PATCH") {
          const body = (await route.request().postDataJSON()) || {};
          // Extract channel ID from URL: .../channels/{id}
          const urlMatch = route
            .request()
            .url()
            .match(/\/channels\/(\d+)/);
          const channelIdStr = urlMatch?.[1];
          const channelId = channelIdStr ? parseInt(channelIdStr, 10) : null;
          const channel = channelId
            ? mockChannels.find((c) => c.id === channelId)
            : null;

          if (channel) {
            const updatedChannel = { ...channel, ...body };
            await route.fulfill(jsonResponse(updatedChannel));
          } else {
            await route.fulfill(
              jsonResponse({ error: "Channel not found" }, 404)
            );
          }
        } else {
          await route.continue();
        }
      }
    );

    await use({
      id: MOCK_GUILD_ID,
      name: mockGuild.guild_name!,
      guild: mockGuild,
      channels: mockChannels,
    });

    // No cleanup needed - routes are automatically cleared when page closes
  },

  // Mock bot configuration state
  mockBotConfigured: async ({ page }, use) => {
    const configResponse = {
      configured: true,
      created_at: new Date().toISOString(),
    };

    await page.route(
      "**/api/manage/admin/discord-bot/config",
      async (route) => {
        const method = route.request().method();
        if (method === "GET" || method === "POST") {
          await route.fulfill(jsonResponse(configResponse));
        } else if (method === "DELETE") {
          await route.fulfill({ status: 204, body: "" });
        } else {
          await route.continue();
        }
      }
    );

    await use(true);
  },
});

export { expect };

/**
 * Navigation helpers for Discord bot pages.
 * These wait for specific UI elements that indicate the page has loaded.
 */
export async function gotoDiscordBotPage(adminPage: Page): Promise<void> {
  await adminPage.goto("/admin/discord-bot");
  await adminPage.waitForLoadState("networkidle");
  // Wait for the page title
  await adminPage.waitForSelector("text=Discord Bots", { timeout: 15000 });
}

export async function gotoGuildDetailPage(
  adminPage: Page,
  guildId: number
): Promise<void> {
  await adminPage.goto(`/admin/discord-bot/${guildId}`);
  await adminPage.waitForLoadState("networkidle");
  // Wait for Channel Configuration section (the main content area on guild detail page)
  await adminPage.waitForSelector("text=Channel Configuration", {
    timeout: 15000,
  });
}
