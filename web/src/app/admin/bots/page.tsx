"use client";

import { useTranslations } from "next-intl";
import { ErrorCallout } from "@/components/ErrorCallout";
import { PageLoader } from "@opal/layouts";
import { InstantSSRAutoRefresh } from "@/components/SSRAutoRefresh";
import { SlackBotTable } from "./SlackBotTable";
import { useSlackBots } from "./[bot-id]/hooks";
import { SettingsLayouts } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { Button } from "@opal/components";
import { SvgPlusCircle } from "@opal/icons";
import { DOCS_ADMINS_PATH } from "@/lib/constants";

const route = ADMIN_ROUTES.SLACK_BOTS;

function Main() {
  const t = useTranslations("admin.slackBots");
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
      t("error.unknownOccurred.message");

    return (
      <ErrorCallout
        errorTitle={t("list.error.title")}
        errorMsg={`${errorMsg}`}
      />
    );
  }

  return (
    <div className="mb-8">
      <p className="mb-2 text-sm text-muted-foreground">
        {t("intro.description")}
      </p>

      <div className="mb-2">
        <ul className="list-disc mt-2 ml-4 text-sm text-muted-foreground">
          <li>{t("intro.autoAnswer.item")}</li>
          <li>{t("intro.documentSets.item")}</li>
          <li>{t("intro.directMessage.item")}</li>
        </ul>
      </div>

      <p className="mb-6 text-sm text-muted-foreground">
        {t.rich("intro.docsPrompt.text", {
          link: (chunks) => (
            <a
              className="text-blue-500 hover:underline"
              href={`${DOCS_ADMINS_PATH}/getting_started/slack_bot_setup`}
              target="_blank"
              rel="noopener noreferrer"
            >
              {chunks}
            </a>
          ),
        })}
      </p>

      <Button
        icon={SvgPlusCircle}
        prominence="secondary"
        href="/admin/bots/new"
      >
        {t("newBotButton.label")}
      </Button>

      <SlackBotTable slackBots={slackBots} />
    </div>
  );
}

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} divider />
      <SettingsLayouts.Body>
        <InstantSSRAutoRefresh />
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
