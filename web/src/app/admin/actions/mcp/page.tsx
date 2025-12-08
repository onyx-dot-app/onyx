"use client";
import SvgServer from "@/icons/server";
import PageHeader from "@/refresh-components/headers/PageHeader";
import MCPPageContent from "@/sections/actions/MCPPageContent";
import OpenApiPageContent from "@/sections/actions/OpenApiPageContent";
export default function Main() {
  return (
    <div className="mx-auto container">
      <PageHeader
        icon={SvgServer}
        title="MCP Actions"
        description="Connect MCP (Model Context Protocol) servers to add custom actions and tools for your assistants."
      />

      <MCPPageContent />
    </div>
  );
}
