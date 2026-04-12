"use client";

import { ErrorCallout } from "@/components/ErrorCallout";
import { ThreeDotsLoader } from "@/components/Loading";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { SlackBotTable } from "./SlackBotTable";
import { useSlackBots } from "./[bot-id]/hooks";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { useTranslations } from "next-intl";

const route = ADMIN_ROUTES.SLACK_BOTS;

function Main() {
  const t = useTranslations("admin.slackBots");
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
      "An unknown error occurred";

    return (
      <ErrorCallout errorTitle="Error loading apps" errorMsg={`${errorMsg}`} />
    );
  }

  return (
    <div className="mb-8">
      <p className="mb-2 text-sm text-muted-foreground">
        {t("description")}
      </p>

      <div className="mb-2">
        <ul className="list-disc mt-2 ml-4 text-sm text-muted-foreground">
          <li>{t("feature1")}</li>
          <li>{t("feature2")}</li>
          <li>{t("feature3")}</li>
        </ul>
      </div>

      <p className="mb-6 text-sm text-muted-foreground">
        {t("followGuide")}{" "}
        <a
          className="text-blue-500 hover:underline"
          href={`${DOCS_ADMINS_PATH}/getting_started/slack_bot_setup`}
          target="_blank"
          rel="noopener noreferrer"
        >
          guide{" "}
        </a>
        {t("followGuide")}
      </p>

      <CreateButton href="/admin/bots/new">{t("newSlackBot")}</CreateButton>

      <SlackBotTable slackBots={slackBots} />
    </div>
  );
}

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} separator />
      <SettingsLayouts.Body>
        <InstantSSRAutoRefresh />
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
