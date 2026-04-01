import { errorHandlingFetcher } from "@/lib/fetcher";
import { SlackBot, SlackChannelConfig } from "@/lib/types";
import useSWR, { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";

export const useSlackChannelConfigs = () => {
  const swrResponse = useSWR<SlackChannelConfig[]>(
    SWR_KEYS.slackChannels,
    errorHandlingFetcher
  );

  return {
    ...swrResponse,
    refreshSlackChannelConfigs: () => mutate(SWR_KEYS.slackChannels),
  };
};

export const useSlackBots = () => {
  const swrResponse = useSWR<SlackBot[]>(
    SWR_KEYS.slackBots,
    errorHandlingFetcher
  );

  return {
    ...swrResponse,
    refreshSlackBots: () => mutate(SWR_KEYS.slackBots),
  };
};

export const useSlackBot = (botId: number) => {
  const swrResponse = useSWR<SlackBot>(
    SWR_KEYS.slackBot(botId),
    errorHandlingFetcher
  );

  return {
    ...swrResponse,
    refreshSlackBot: () => mutate(SWR_KEYS.slackBot(botId)),
  };
};

export const useSlackChannelConfigsByBot = (botId: number) => {
  const swrResponse = useSWR<SlackChannelConfig[]>(
    SWR_KEYS.slackBotConfig(botId),
    errorHandlingFetcher
  );

  return {
    ...swrResponse,
    refreshSlackChannelConfigs: () => mutate(SWR_KEYS.slackBotConfig(botId)),
  };
};
