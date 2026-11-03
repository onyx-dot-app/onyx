"use client";

import { useTranslations } from "next-intl";
import { SettingsLayouts } from "@opal/layouts";
import { SvgOnyxOctagon } from "@opal/icons";
import { useAppPosition } from "@/lib/position/hooks";

/** The agent editor while it loads, titled for a new agent or an edit. */
export default function AgentEditorLoading() {
  const t = useTranslations("agents");
  const position = useAppPosition();
  return (
    <SettingsLayouts.Loading
      icon={SvgOnyxOctagon}
      title={
        position.isAgentCreate()
          ? t("editor.header.createTitle")
          : t("editor.header.editTitle")
      }
    />
  );
}
