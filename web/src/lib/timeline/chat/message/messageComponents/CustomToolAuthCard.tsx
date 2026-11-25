"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { useNavigation } from "@opal/navigation";
import { useAvailableTools } from "@/lib/tools/hooks";
import { integrationHref } from "@/lib/customize/paths";
import { SWR_KEYS } from "@/lib/swr-keys";
import { SvgArrowExchange } from "@opal/icons";
import { Button, MessageCard } from "@opal/components";

interface CustomToolAuthCardProps {
  toolName: string;
  toolId: number | null;
  /** The integration of an app tool, which has no tool ID. */
  integrationId: number | null;
}

/** A tool call that needs the user's sign-in. Connect opens the tool's
 * integration: the one the call names (an app tool), else the one the tool
 * list gives for the tool ID. The card
 * reads the integration statuses again, so the chat's connect prompt shows
 * the connection that failed. */
function CustomToolAuthCard({
  toolName,
  toolId,
  integrationId: appIntegrationId,
}: CustomToolAuthCardProps) {
  const t = useTranslations("chat.messages");
  const navigation = useNavigation();
  const { tools } = useAvailableTools();
  const { mutate } = useSWRConfig();
  useEffect(() => {
    void mutate(SWR_KEYS.integrations);
  }, [mutate]);
  const integrationId =
    appIntegrationId ??
    tools.find((tool) => tool.id === toolId)?.integration_id;
  if (integrationId === undefined || integrationId === null) return null;

  return (
    <MessageCard
      outerPadding={1}
      innerPadding={1}
      title={t("customToolAuth.card.title", { toolName })}
      description={t("customToolAuth.card.description", { toolName })}
      rightChildren={
        <Button
          prominence="primary"
          icon={SvgArrowExchange}
          {...navigation.linkTo(
            integrationHref(integrationId, "configuration")
          )}
        >
          {t("customToolAuth.connectButton.label")}
        </Button>
      }
    />
  );
}

export default CustomToolAuthCard;
