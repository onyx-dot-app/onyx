import {
  DiscordBotConfig,
  DiscordGuildConfig,
  DiscordGuildConfigCreateResponse,
  DiscordGuildConfigUpdate,
  DiscordChannelConfig,
  DiscordChannelConfigUpdate,
} from "@/app/admin/discord-bot/types";

const BASE_URL = "/api/manage/admin/discord-bot";

// === Bot Config (Self-hosted only) ===

export async function fetchBotConfig(): Promise<DiscordBotConfig> {
  const response = await fetch(`${BASE_URL}/config`);
  if (!response.ok) {
    throw new Error("Failed to fetch bot config");
  }
  return response.json();
}

export async function createBotConfig(
  botToken: string
): Promise<DiscordBotConfig> {
  const response = await fetch(`${BASE_URL}/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ bot_token: botToken }),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to create bot config");
  }
  return response.json();
}

export async function deleteBotConfig(): Promise<void> {
  const response = await fetch(`${BASE_URL}/config`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error("Failed to delete bot config");
  }
}

// === Guild Config ===

export async function fetchGuildConfigs(): Promise<DiscordGuildConfig[]> {
  const response = await fetch(`${BASE_URL}/guilds`);
  if (!response.ok) {
    throw new Error("Failed to fetch guild configs");
  }
  return response.json();
}

export async function createGuildConfig(): Promise<DiscordGuildConfigCreateResponse> {
  const response = await fetch(`${BASE_URL}/guilds`, { method: "POST" });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to create guild config");
  }
  return response.json();
}

export async function fetchGuildConfig(
  configId: number
): Promise<DiscordGuildConfig> {
  const response = await fetch(`${BASE_URL}/guilds/${configId}`);
  if (!response.ok) {
    throw new Error("Failed to fetch guild config");
  }
  return response.json();
}

export async function updateGuildConfig(
  configId: number,
  update: DiscordGuildConfigUpdate
): Promise<DiscordGuildConfig> {
  const response = await fetch(`${BASE_URL}/guilds/${configId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to update guild config");
  }
  return response.json();
}

export async function deleteGuildConfig(configId: number): Promise<void> {
  const response = await fetch(`${BASE_URL}/guilds/${configId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error("Failed to delete guild config");
  }
}

// === Channel Config ===

export async function fetchChannelConfigs(
  guildConfigId: number
): Promise<DiscordChannelConfig[]> {
  const response = await fetch(`${BASE_URL}/guilds/${guildConfigId}/channels`);
  if (!response.ok) {
    throw new Error("Failed to fetch channel configs");
  }
  return response.json();
}

export async function updateChannelConfig(
  guildConfigId: number,
  channelConfigId: number,
  update: DiscordChannelConfigUpdate
): Promise<DiscordChannelConfig> {
  const response = await fetch(
    `${BASE_URL}/guilds/${guildConfigId}/channels/${channelConfigId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    }
  );
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Failed to update channel config");
  }
  return response.json();
}

export async function bulkUpdateChannelConfigs(
  guildConfigId: number,
  updates: { channelConfigId: number; update: DiscordChannelConfigUpdate }[]
): Promise<{ succeeded: number; failed: number }> {
  let succeeded = 0;
  let failed = 0;

  for (const { channelConfigId, update } of updates) {
    try {
      await updateChannelConfig(guildConfigId, channelConfigId, update);
      succeeded++;
    } catch {
      failed++;
    }
  }

  return { succeeded, failed };
}
