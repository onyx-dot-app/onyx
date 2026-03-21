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

const route = ADMIN_ROUTES.SLACK_BOTS;

function Main() {
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
        Configura bots de Slack conectados a la aplicación. Una vez listos,
        podrás hacer preguntas directamente desde Slack. Además, podrás:
      </p>

      <div className="mb-2">
        <ul className="list-disc mt-2 ml-4 text-sm text-muted-foreground">
          <li>
            Configurar el bot para responder automáticamente en ciertos
            canales.
          </li>
          <li>
            Elegir desde qué conjuntos de documentos debe responder el bot,
            según el canal donde se haga la pregunta.
          </li>
          <li>
            Escribirle directamente al bot para buscar igual que en la web.
          </li>
        </ul>
      </div>

      <p className="mb-6 text-sm text-muted-foreground">
        Follow the{" "}
        <a
          className="text-blue-500 hover:underline"
          href={`${DOCS_ADMINS_PATH}/getting_started/slack_bot_setup`}
          target="_blank"
          rel="noopener noreferrer"
        >
          guide{" "}
        </a>
        found in the documentation to get started!
      </p>

      <CreateButton href="/admin/bots/new">New Slack Bot</CreateButton>

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
