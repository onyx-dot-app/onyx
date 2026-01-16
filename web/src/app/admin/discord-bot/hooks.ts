import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import {
  DiscordGuildConfig,
  DiscordChannelConfig,
} from "@/app/admin/discord-bot/types";

const BASE_URL = "/api/manage/admin/discord-bot";

export function useDiscordGuilds() {
  const url = `${BASE_URL}/guilds`;
  const swrResponse = useSWR<DiscordGuildConfig[]>(url, errorHandlingFetcher);
  return {
    ...swrResponse,
    refreshGuilds: () => swrResponse.mutate(),
  };
}

export function useDiscordGuild(configId: number) {
  const url = `${BASE_URL}/guilds/${configId}`;
  const swrResponse = useSWR<DiscordGuildConfig>(url, errorHandlingFetcher);
  return {
    ...swrResponse,
    refreshGuild: () => swrResponse.mutate(),
  };
}

export function useDiscordChannels(guildConfigId: number) {
  const url = guildConfigId
    ? `${BASE_URL}/guilds/${guildConfigId}/channels`
    : null;
  const swrResponse = useSWR<DiscordChannelConfig[]>(url, errorHandlingFetcher);
  return {
    ...swrResponse,
    refreshChannels: () => swrResponse.mutate(),
  };
}
