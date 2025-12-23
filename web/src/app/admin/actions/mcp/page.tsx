"use client";

import { SvgMcp } from "@opal/icons";
import MCPPageContent from "@/sections/actions/MCPPageContent";
import Settings from "@/layouts/settings-layouts";

export default function Main() {
  return (
    <Settings.Root>
      <Settings.Header
        icon={SvgMcp}
        title="MCP Actions"
        description="Connect MCP (Model Context Protocol) servers to add custom actions and tools for your assistants."
        separator
      />
      <Settings.Body>
        <MCPPageContent />
      </Settings.Body>
    </Settings.Root>
  );
}
