"use client";
import PageHeader from "@/refresh-components/headers/PageHeader";
import SvgActions from "@/icons/actions";
import Separator from "@/refresh-components/Separator";
import Actionbar from "@/sections/actions/Actionbar";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import AddOpenAPIActionModal from "@/sections/actions/modals/AddOpenAPIActionModal";
import OpenAPIAuthenticationModal from "@/sections/actions/modals/OpenAPIAuthenticationModal";
import { usePopup } from "@/components/admin/connectors/Popup";

export default function MCPActionsPageContent() {
  const addOpenAPIActionModal = useCreateModal();
  const openAPIAuthModal = useCreateModal();
  const { popup, setPopup } = usePopup();
  return (
    <div className="mx-auto container">
      {popup}
      <PageHeader
        icon={SvgActions}
        title="MCP Actions"
        description="Connect MCP (Model Context Protocol) server to add custom actions for chats and agents to retrieve specific data or perform predefined tasks."
      />
      <Separator className="mb-6" />
      <Actionbar
        hasActions={false}
        onAddAction={() => {
          addOpenAPIActionModal.toggle(true);
        }}
        buttonText="Add OpenAPI Action"
      />
      <addOpenAPIActionModal.Provider>
        <AddOpenAPIActionModal
          skipOverlay
          setPopup={setPopup}
          onSuccess={() => openAPIAuthModal.toggle(true)}
        />
      </addOpenAPIActionModal.Provider>
      <openAPIAuthModal.Provider>
        <OpenAPIAuthenticationModal
          isOpen={openAPIAuthModal.isOpen}
          onClose={() => openAPIAuthModal.toggle(false)}
          title="Authenticate OpenAPI Action"
          defaultMethod="oauth"
          onConnect={() => {}}
          onSkip={() => openAPIAuthModal.toggle(false)}
        />
      </openAPIAuthModal.Provider>
    </div>
  );
}
