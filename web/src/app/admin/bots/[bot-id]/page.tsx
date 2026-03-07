"use client";

import { use } from "react";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import SlackChannelConfigsTable from "./SlackChannelConfigsTable";
import { useSlackBot, useSlackChannelConfigsByBot } from "./hooks";
import { ExistingSlackBotForm } from "../SlackBotUpdateForm";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgSlack } from "@opal/icons";

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
    return (
      <div className="flex justify-center items-center h-screen">
        <ThreeDotsLoader />
      </div>
    );
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
      <InstantSSRAutoRefresh />

      <ExistingSlackBotForm
        existingSlackBot={slackBot}
        refreshSlackBot={refreshSlackBot}
      />

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
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgSlack}
        title="Edit Slack Bot"
        backButton
        separator
      />
      <SettingsLayouts.Body>
        <SlackBotEditContent botId={unwrappedParams["bot-id"]} />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
