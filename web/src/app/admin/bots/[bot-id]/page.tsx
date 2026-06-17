"use client";

import { use } from "react";
import { ErrorCallout } from "@/components/ErrorCallout";
import { SvgSimpleLoader } from "@opal/icons";
import SlackChannelConfigsTable from "./SlackChannelConfigsTable";
import { useSlackBot, useSlackChannelConfigsByBot } from "./hooks";
import { ExistingSlackBotForm } from "../SlackBotUpdateForm";
import { SettingsLayouts } from "@opal/layouts";
import { SvgSlack } from "@opal/logos";
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
    return <SvgSimpleLoader />;
  }

  if (slackBotError || !slackBot) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch Slack Bot ${botId}: ${getErrorMsg(
          slackBotError
        )}`}
      />
    );
  }

  if (slackChannelConfigsError || !slackChannelConfigs) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch Slack Bot ${botId}: ${getErrorMsg(
          slackChannelConfigsError
        )}`}
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
        divider
      />
      <SettingsLayouts.Body>
        <SlackBotEditContent botId={unwrappedParams["bot-id"]} />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
