"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { LLMConfiguration } from "./LLMConfiguration";
import { SvgCpu } from "@opal/icons";
import * as SettingsLayouts from "@/layouts/settings-layouts";

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={SvgCpu} title="LLM Models" separator />
      <SettingsLayouts.Body>
        <LLMConfiguration />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
