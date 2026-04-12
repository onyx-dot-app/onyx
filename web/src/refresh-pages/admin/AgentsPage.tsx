"use client";

import { SvgOnyxOctagon, SvgPlus } from "@opal/icons";
import { Button } from "@opal/components";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import Link from "next/link";
import { useTranslations } from "next-intl";

import AgentsTable from "./AgentsPage/AgentsTable";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AgentsPage() {
  const t = useTranslations("admin.agents");

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        title={t("title")}
        description={t("description")}
        icon={SvgOnyxOctagon}
        rightChildren={
          <Button href="/app/agents/create?admin=true" icon={SvgPlus}>
            {t("newAgent")}
          </Button>
        }
      />
      <SettingsLayouts.Body>
        <AgentsTable />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
