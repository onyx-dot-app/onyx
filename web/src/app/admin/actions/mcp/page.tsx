"use client";

import { SvgMcp } from "@opal/icons";
import MCPPageContent from "@/sections/actions/MCPPageContent";
import * as SettingsLayouts from "@/layouts/settings-layouts";

export default function Main() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgMcp}
        title="MCP Actions"
        description="Connect MCP (Model Context Protocol) servers to add custom actions and tools for your assistants."
        separator
      />
      <SettingsLayouts.Body>
        <MCPPageContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
