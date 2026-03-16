"use client";

import { SvgOnyxOctagon, SvgPlus } from "@opal/icons";
import { Button } from "@opal/components";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import Link from "next/link";

import AgentsTable from "./AgentsPage/AgentsTable";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AgentsPage() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        title="Agents"
        icon={SvgOnyxOctagon}
        rightChildren={
          <Link href="/app/agents/create?admin=true">
            <Button icon={SvgPlus}>New Agent</Button>
          </Link>
        }
      />
      <SettingsLayouts.Body>
        <AgentsTable />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
