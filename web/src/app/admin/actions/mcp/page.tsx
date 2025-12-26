"use client";

import MCPPageContent from "@/sections/actions/MCPPageContent";
import { AdminPageTitle } from "@/components/admin/Title";
import Text from "@/refresh-components/texts/Text";
import { SvgMcp } from "@opal/icons";

export default function Main() {
  return (
    <div className="container">
      <AdminPageTitle icon={SvgMcp} title="MCP Actions" />
      <Text secondaryBody text03 className="pt-4 pb-6">
        Connect MCP (Model Context Protocol) servers to add custom actions and
        tools for your assistants.
      </Text>
      <MCPPageContent />
    </div>
  );
}
