"use client";

import { use } from "react";
import { BackButton } from "@/components/BackButton";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { usePopup } from "@/components/admin/connectors/Popup";
import Link from "next/link";
import { SlackChannelConfigsTable } from "../../SlackChannelConfigsTable";
import { useSlackBot, useSlackChannelConfigsByBot } from "../../hooks";
import { ExistingSlackBotForm } from "../SlackBotCreationForm";
import { FiPlusSquare } from "react-icons/fi";
import { Separator } from "@/components/ui/separator";

function SlackBotEditPage({ params }: { params: Promise<{ id: string }> }) {
  // Unwrap the params promise
  const unwrappedParams = use(params);
  const { popup, setPopup } = usePopup();

  const {
    data: slackBot,
    isLoading: isSlackBotLoading,
    error: slackBotError,
    refreshSlackBot,
  } = useSlackBot(Number(unwrappedParams.id));

  const {
    data: slackChannelConfigs,
    isLoading: isSlackChannelConfigsLoading,
    error: slackChannelConfigsError,
    refreshSlackChannelConfigs,
  } = useSlackChannelConfigsByBot(Number(unwrappedParams.id));

  if (isSlackBotLoading || isSlackChannelConfigsLoading) {
    return <ThreeDotsLoader />;
  }

  if (slackBotError || !slackBot) {
    const errorMsg =
      slackBotError?.info?.message ||
      slackBotError?.info?.detail ||
      "An unknown error occurred";
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch slack app ${unwrappedParams.id}: ${errorMsg}`}
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
        errorMsg={`Failed to fetch slack app ${unwrappedParams.id}: ${errorMsg}`}
      />
    );
  }

  return (
    <div className="container mx-auto">
      <InstantSSRAutoRefresh />

      <BackButton routerOverride="/admin/bot" />

      <ExistingSlackBotForm
        existingSlackBot={slackBot}
        refreshSlackBot={refreshSlackBot}
      />
      <Separator />

      <div className="my-8" />

      <Link
        className="
          flex
          py-2
          px-4
          mt-2
          border
          border-border
          h-fit
          cursor-pointer
          hover:bg-hover
          text-sm
          w-80
        "
        href={`/admin/bot/new?slack_bot_id=${unwrappedParams.id}`}
      >
        <div className="mx-auto flex">
          <FiPlusSquare className="my-auto mr-2" />
          New Slack Channel Configuration
        </div>
      </Link>

      <div className="mt-8">
        <SlackChannelConfigsTable
          slackChannelConfigs={slackChannelConfigs}
          refresh={refreshSlackChannelConfigs}
          setPopup={setPopup}
        />
      </div>
    </div>
  );
}

export default SlackBotEditPage;
