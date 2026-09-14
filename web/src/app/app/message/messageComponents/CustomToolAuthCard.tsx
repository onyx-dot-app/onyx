"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { ToolSnapshot } from "@/lib/tools/types";
import { initiateOAuthFlow } from "@/lib/oauth/api";
import { useToolOAuthStatus } from "@/lib/hooks/useToolOAuthStatus";
import { SvgArrowExchange } from "@opal/icons";
import { Button, MessageCard } from "@opal/components";

interface CustomToolAuthCardProps {
  toolName: string;
  toolId: number | null;
  tools: ToolSnapshot[];
  agentId: number;
}

function CustomToolAuthCard({
  toolName,
  toolId,
  tools,
  agentId,
}: CustomToolAuthCardProps) {
  const t = useTranslations("chat.messages");
  const { getToolAuthStatus } = useToolOAuthStatus(agentId);
  const matchedTool = useMemo(() => {
    if (toolId == null) return null;
    return tools.find((t) => t.id === toolId) ?? null;
  }, [toolId, tools]);

  // Hide the card if the user already has a valid token
  const authStatus = matchedTool ? getToolAuthStatus(matchedTool) : undefined;
  if (authStatus?.hasToken && !authStatus.isTokenExpired) {
    return null;
  }

  const oauthConfigId = matchedTool?.oauth_config_id ?? null;

  // No OAuth config — nothing actionable to show
  if (!oauthConfigId) {
    return null;
  }

  const handleAuthenticate = () => {
    initiateOAuthFlow(
      oauthConfigId,
      window.location.pathname + window.location.search
    );
  };

  return (
    <MessageCard
      title={t("customToolAuth.card.title", { toolName })}
      description={t("customToolAuth.card.description", { toolName })}
      rightChildren={
        <Button
          prominence="primary"
          icon={SvgArrowExchange}
          onClick={handleAuthenticate}
        >
          {t("customToolAuth.connectButton.label")}
        </Button>
      }
    />
  );
}

export default CustomToolAuthCard;
