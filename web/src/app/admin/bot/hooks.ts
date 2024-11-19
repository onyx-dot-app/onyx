import { errorHandlingFetcher } from "@/lib/fetcher";
import { SlackBot, SlackChannelConfig } from "@/lib/types";
import useSWR, { mutate } from "swr";

export const useSlackChannelConfigs = () => {
  const url = "/api/manage/admin/slack-bot/config";
  const swrResponse = useSWR<SlackChannelConfig[]>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshSlackChannelConfigs: () => mutate(url),
  };
};

export const useSlackBots = () => {
  const url = "/api/manage/admin/slack-bot/apps";
  const swrResponse = useSWR<SlackBot[]>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshSlackBots: () => mutate(url),
  };
};

export const useSlackBot = (appId: number) => {
  const url = `/api/manage/admin/slack-bot/bots/${appId}`;
  const swrResponse = useSWR<SlackBot>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshSlackBot: () => mutate(url),
  };
};

export const useSlackChannelConfigsByBot = (botId: number) => {
  const url = `/api/manage/admin/slack-bot/bots/${botId}/config`;
  const swrResponse = useSWR<SlackChannelConfig[]>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshSlackChannelConfigs: () => mutate(url),
  };
};
