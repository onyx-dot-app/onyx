"use client";

import { useTranslations } from "next-intl";
import { useNavigation } from "@opal/navigation";
import { useAvailableTools } from "@/lib/tools/hooks";
import { memberPluginHref } from "@/lib/plugins/directory";
import { SvgArrowExchange } from "@opal/icons";
import { Button, MessageCard } from "@opal/components";

interface CustomToolAuthCardProps {
  toolName: string;
  toolId: number | null;
}

/** A tool call that needs the user's sign-in. Connect opens the tool's
 * plugin, from the tool list: only that list sets `plugin_ids`. */
function CustomToolAuthCard({ toolName, toolId }: CustomToolAuthCardProps) {
  const t = useTranslations("chat.messages");
  const navigation = useNavigation();
  const { tools } = useAvailableTools();
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
