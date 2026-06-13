"use client";

import { SvgPlus, SvgSparkle } from "@opal/icons";
import { Button } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";

import AgentsTable from "./AgentsPage/AgentsTable";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AgentsPage() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        title="智能体"
        description="用智能体定制 AI 行为与知识，并管理组织内的智能体。"
        icon={SvgSparkle}
        rightChildren={
          <Button href="/app/agents/create?admin=true" icon={SvgPlus}>
            新建智能体
          </Button>
        }
      />
      <SettingsLayouts.Body>
        <AgentsTable />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
