"use client";
import PageHeader from "@/refresh-components/headers/PageHeader";
import SvgActions from "@/icons/actions";
import Separator from "@/refresh-components/Separator";
import Actionbar from "@/sections/actions/Actionbar";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import AddOpenAPIActionModal from "@/sections/actions/modals/AddOpenAPIActionModal";
import OpenAPIAuthenticationModal from "@/sections/actions/modals/OpenAPIAuthenticationModal";
import { usePopup } from "@/components/admin/connectors/Popup";
import OpenApiActionsList from "@/sections/actions/OpenApiActionsList";

export default function MCPActionsPageContent() {
  return (
    <div className="mx-auto container">
      <PageHeader
        icon={SvgActions}
        title="MCP Actions"
        description="Connect MCP (Model Context Protocol) server to add custom actions for chats and agents to retrieve specific data or perform predefined tasks."
      />
      <Separator className="mb-6" />

      <OpenApiActionsList />
    </div>
  );
}
