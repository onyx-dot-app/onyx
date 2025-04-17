"use client";
import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";

import { ErrorCallout } from "@/components/ErrorCallout";
import { FiPlusSquare } from "react-icons/fi";
import { ThreeDotsLoader } from "@/components/Loading";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { AdminPageTitle } from "@/components/admin/Title";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { SourceIcon } from "@/components/SourceIcon";
import { SlackBotTable } from "./SlackBotTable";
import { useSlackBots } from "./[bot-id]/hooks";
import { ValidSources } from "@/lib/types";
import CreateButton from "@/components/ui/createButton";

const Main = () => {
  const {
    data: slackBots,
    isLoading: isSlackBotsLoading,
    error: slackBotsError,
  } = useSlackBots();

  if (isSlackBotsLoading) {
    return <ThreeDotsLoader />;
  }

  if (slackBotsError || !slackBots) {
    const errorMsg =
      slackBotsError?.info?.message ||
      slackBotsError?.info?.detail ||
      "Произошла неизвестная ошибка";

    return (
      <ErrorCallout errorTitle="Error loading apps" errorMsg={`${errorMsg}`} />
    );
  }

  return (
    <div className="mb-8">
      {/* {popup} */}

      <p className="mb-2 text-sm text-muted-foreground">
        {i18n.t(k.SETUP_SLACK_BOTS_THAT_CONNECT)}
      </p>

      <div className="mb-2">
        <ul className="list-disc mt-2 ml-4 text-sm text-muted-foreground">
          <li>{i18n.t(k.SETUP_ONYXBOT_TO_AUTOMATICALLY)}</li>
          <li>{i18n.t(k.CHOOSE_WHICH_DOCUMENT_SETS_ONY)}</li>
          <li>{i18n.t(k.DIRECTLY_MESSAGE_ONYXBOT_TO_SE)}</li>
        </ul>
      </div>

      <p className="mb-6 text-sm text-muted-foreground">
        {i18n.t(k.FOLLOW_THE)}{" "}
        <a
          className="text-blue-500 hover:underline"
          href="https://docs.onyx.app/slack_bot_setup"
          target="_blank"
          rel="noopener noreferrer"
        >
          {i18n.t(k.GUIDE)}{" "}
        </a>
        {i18n.t(k.FOUND_IN_THE_ONYX_DOCUMENTATIO)}
      </p>

      <CreateButton href="/admin/bots/new" text="New Slack Bot" />

      <SlackBotTable slackBots={slackBots} />
    </div>
  );
};

const Page = () => {
  return (
    <div className="container mx-auto">
      <AdminPageTitle
        icon={<SourceIcon iconSize={36} sourceType={ValidSources.Slack} />}
        title="Slack Bots"
      />

      <InstantSSRAutoRefresh />

      <Main />
    </div>
  );
};

export default Page;
