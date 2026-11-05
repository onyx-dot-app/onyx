"use client";

import { useNavigation } from "@opal/navigation";
import { SvgOnyxOctagon, SvgPlus } from "@opal/icons";
import { Button } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import { useTranslations } from "next-intl";

import AgentsTable from "./AgentsPage/AgentsTable";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AgentsPage() {
  const t = useTranslations("admin.agents");
  const navigation = useNavigation();

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        title={t("header.title")}
        description={t("header.description")}
        icon={SvgOnyxOctagon}
        actions={[
          <Button
            key="primary"
            {...navigation.linkTo("/app/agents/create?admin=true")}
            icon={SvgPlus}
          >
            {t("newAgentButton.label")}
          </Button>,
        ]}
      />
      <SettingsLayouts.Body>
        <AgentsTable />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
