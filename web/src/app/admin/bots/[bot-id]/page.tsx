"use client";

import { use } from "react";
import { BackButton } from "@/components/BackButton";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { usePopup } from "@/components/admin/connectors/Popup";
import SlackChannelConfigsTable from "./SlackChannelConfigsTable";
import { useSlackBot, useSlackChannelConfigsByBot } from "./hooks";
import { ExistingSlackBotForm } from "../SlackBotUpdateForm";
import { Separator } from "@/components/ui/separator";

function SlackBotEditPage({
  params,
}: {
  params: Promise<{ "bot-id": string }>;
}) {
  // Unwrap the params promise
  const unwrappedParams = use(params);
  const { popup, setPopup } = usePopup();

  const {
    data: slackBot,
    isLoading: isSlackBotLoading,
    error: slackBotError,
    refreshSlackBot,
  } = useSlackBot(Number(unwrappedParams["bot-id"]));

  const {
    data: slackChannelConfigs,
    isLoading: isSlackChannelConfigsLoading,
    error: slackChannelConfigsError,
    refreshSlackChannelConfigs,
  } = useSlackChannelConfigsByBot(Number(unwrappedParams["bot-id"]));

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
        errorMsg={`Failed to fetch Slack Bot ${unwrappedParams["bot-id"]}: ${errorMsg}`}
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
        errorMsg={`Failed to fetch Slack Bot ${unwrappedParams["bot-id"]}: ${errorMsg}`}
      />
    );
  }

  return (
    <>
      <InstantSSRAutoRefresh />

      <BackButton routerOverride="/admin/bots" />

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
          setPopup={setPopup}
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
  return (
    <div className="container mx-auto">
      <SlackBotEditPage params={params} />
    </div>
  );
}
