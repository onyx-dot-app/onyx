"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { useNavigation } from "@opal/navigation";
import { useAvailableTools } from "@/lib/tools/hooks";
import { memberPluginHref } from "@/lib/plugins/directory";
import { SWR_KEYS } from "@/lib/swr-keys";
import { SvgArrowExchange } from "@opal/icons";
import { Button, MessageCard } from "@opal/components";

interface CustomToolAuthCardProps {
  toolName: string;
  toolId: number | null;
}

/** A tool call that needs the user's sign-in. Connect opens the tool's
 * plugin, from the tool list: only that list sets `plugin_ids`. The card
 * reads the integration statuses again, so the chat's connect prompt shows
 * the connection that failed. */
function CustomToolAuthCard({ toolName, toolId }: CustomToolAuthCardProps) {
  const t = useTranslations("chat.messages");
  const navigation = useNavigation();
  const { tools } = useAvailableTools();
  const { mutate } = useSWRConfig();
  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- revalidates the integrations SWR cache when the auth card mounts
  useEffect(() => {
    void mutate(SWR_KEYS.integrations);
  }, [mutate]);
  const pluginId = tools.find((tool) => tool.id === toolId)?.plugin_ids?.[0];
  if (!pluginId) return null;

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
          {...navigation.linkTo(memberPluginHref(pluginId, "integrations"))}
        >
          {t("customToolAuth.connectButton.label")}
        </Button>
      }
    />
  );
}

export default CustomToolAuthCard;
