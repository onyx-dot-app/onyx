"use client";

import { use } from "react";
import ResourceErrorPage from "@/sections/error/ResourceErrorPage";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import SlackChannelConfigsTable from "./SlackChannelConfigsTable";
import { useSlackBot, useSlackChannelConfigsByBot } from "./hooks";
import { ExistingSlackBotForm } from "../SlackBotUpdateForm";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { SvgSlack } from "@opal/icons";
import { getErrorMsg } from "@/lib/error";

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
    return (
      <ResourceErrorPage
        errorType="fetch_error"
        title="Failed to load Slack bot"
        description={getErrorMsg(slackBotError)}
        backHref="/admin/bots"
        backLabel="Back to Slack bots"
      />
    );
  }

  if (slackChannelConfigsError || !slackChannelConfigs) {
    return (
      <ResourceErrorPage
        errorType="fetch_error"
        title="Failed to load channel configs"
        description={getErrorMsg(slackChannelConfigsError)}
        backHref="/admin/bots"
        backLabel="Back to Slack bots"
      />
    );
  }

  return (
    <>
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
