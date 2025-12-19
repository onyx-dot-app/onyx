"use client";
import { SvgMcp } from "@opal/icons";
import MCPPageContent from "@/sections/actions/MCPPageContent";
import { AdminPageLayout } from "@/layouts/admin-pages";
export default function Main() {
  return (
    <AdminPageLayout
      icon={SvgMcp}
      title="MCP Actions"
      description="Connect MCP (Model Context Protocol) servers to add custom actions and tools for your assistants."
    >
      <MCPPageContent />
    </AdminPageLayout>
  );
}
