import useSWR from "swr";
import { TeamsBot, TeamsChannelConfig } from "@/lib/types";
import { errorHandlingFetcher } from "@/lib/fetcher";

const TEAMS_BOTS_URL = "/api/manage/admin/teams-app/bots";

export function useTeamsBots() {
  const { data, error, isLoading, mutate } = useSWR<TeamsBot[]>(
    TEAMS_BOTS_URL,
    errorHandlingFetcher
  );

  return {
    data,
    error,
    isLoading,
    refresh: mutate,
  };
}

export function useTeamsBot(botId: string) {
  const { data, error, isLoading, mutate } = useSWR<TeamsBot>(
    `${TEAMS_BOTS_URL}/${botId}`,
    errorHandlingFetcher
  );

  return {
    data,
    error,
    isLoading,
    refresh: mutate,
  };
}

export function useTeamsChannelConfigsByBot(teamsBotId: string) {
  const { data, error, isLoading, mutate } = useSWR<TeamsChannelConfig[]>(
    `${TEAMS_BOTS_URL}/${teamsBotId}/channels`,
    errorHandlingFetcher
  );

  return {
    data,
    error,
    isLoading,
    refresh: mutate,
  };
} 