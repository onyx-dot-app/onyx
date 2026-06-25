"use client";

import { ErrorCallout } from "@/components/ErrorCallout";
import { PageLoader } from "@/refresh-components/PageLoader";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { SlackBotTable } from "./SlackBotTable";
import { useSlackBots } from "./[bot-id]/hooks";
import { SettingsLayouts } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Button } from "@opal/components";
import { SvgPlusCircle } from "@opal/icons";
import { DOCS_ADMINS_PATH } from "@/lib/constants";

import { useTranslation, Trans } from "react-i18next";

const route = ADMIN_ROUTES.SLACK_BOTS;

function Main() {
  const { t } = useTranslation();
  const {
    data: slackBots,
    isLoading: isSlackBotsLoading,
    error: slackBotsError,
  } = useSlackBots();

  if (isSlackBotsLoading) {
    return <PageLoader />;
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
        {t("admin.bots.slack_desc")}
      </p>

      <div className="mb-2">
        <ul className="list-disc mt-2 ml-4 text-sm text-muted-foreground">
          <li>
            {t("admin.bots.slack_bullet_1")}
          </li>
          <li>
            {t("admin.bots.slack_bullet_2")}
          </li>
          <li>
            {t("admin.bots.slack_bullet_3")}
          </li>
        </ul>
      </div>

      <p className="mb-6 text-sm text-muted-foreground">
        <Trans i18nKey="admin.bots.slack_follow_guide">
          Follow the{" "}
          <a
            className="text-blue-500 hover:underline"
            href={`${DOCS_ADMINS_PATH}/getting_started/slack_bot_setup`}
            target="_blank"
            rel="noopener noreferrer"
          >
            guide{" "}
          </a>
          found in the Onyx documentation to get started!
        </Trans>
      </p>

      <Button
        icon={SvgPlusCircle}
        prominence="secondary"
        href="/admin/bots/new"
      >
        {t("admin.bots.new_slack_bot")}
      </Button>

      <SlackBotTable slackBots={slackBots} />
    </div>
  );
}

export default function Page() {
  const { t } = useTranslation();
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={t("admin.bots.slack_title")} divider />
      <SettingsLayouts.Body>
        <InstantSSRAutoRefresh />
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
