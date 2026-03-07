"use client";

import { use } from "react";
import BackButton from "@/refresh-components/buttons/BackButton";
import { ErrorCallout } from "@/components/ErrorCallout";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import SlackChannelConfigsTable from "@/app/admin/bots/[bot-id]/SlackChannelConfigsTable";
import {
  useSlackBot,
  useSlackChannelConfigsByBot,
} from "@/app/admin/bots/[bot-id]/hooks";
import { ExistingSlackBotForm } from "@/app/admin/bots/SlackBotUpdateForm";
import Separator from "@/refresh-components/Separator";

function SlackBotEditContent({ botId }: { botId: string }) {
  const {
    data: slackBot,
    isLoading: isSlackBotLoading,
    error: slackBotError,
    refreshSlackBot,
  } = useSlackBot(Number(botId));

  const {
    data: slackChannelConfigs,
    isLoading: isSlackChannelConfigsLoading,
    error: slackChannelConfigsError,
    refreshSlackChannelConfigs,
  } = useSlackChannelConfigsByBot(Number(botId));

  if (isSlackBotLoading || isSlackChannelConfigsLoading) {
    return <SimpleLoader />;
  }

  if (slackBotError || !slackBot) {
    const errorMsg =
      slackBotError?.info?.message ||
      slackBotError?.info?.detail ||
      "An unknown error occurred";
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch Slack Bot ${botId}: ${errorMsg}`}
      />
    );
  }

  if (slackChannelConfigsError || !slackChannelConfigs) {
    const errorMsg =
      slackChannelConfigsError?.info?.message ||
      slackChannelConfigsError?.info?.detail ||
      "An unknown error occurred";
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch Slack Bot ${botId}: ${errorMsg}`}
      />
    );
  }

  return (
    <>
      <ExistingSlackBotForm
        existingSlackBot={slackBot}
        refreshSlackBot={refreshSlackBot}
      />
      <Separator />

      <div className="mt-8">
        <SlackChannelConfigsTable
          slackBotId={slackBot.id}
          slackChannelConfigs={slackChannelConfigs}
          refresh={refreshSlackChannelConfigs}
        />
      </div>
    </>
  );
}

export default function Page({
  params,
}: {
  params: Promise<{ "bot-id": string }>;
}) {
  const unwrappedParams = use(params);

  return (
    <>
      <BackButton routerOverride="/admin/bots" />
      <SlackBotEditContent botId={unwrappedParams["bot-id"]} />
    </>
  );
}
