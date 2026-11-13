"use client";

import { Divider } from "@opal/components";
import { useTranslations } from "next-intl";

/** Marks the hidden question of an automatic follow-up to subagent results. */
export default function AgentResultsDivider() {
  const t = useTranslations("chat.messages");
  return <Divider title={t("agentResults.received")} />;
}
