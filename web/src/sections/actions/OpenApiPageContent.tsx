"use client";

import { ToolSnapshot } from "@/lib/tools/interfaces";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import OpenAPIAuthenticationModal, {
  AuthMethod,
  OpenAPIAuthFormValues,
} from "./modals/OpenAPIAuthenticationModal";
import AddOpenAPIActionModal from "./modals/AddOpenAPIActionModal";
import Actionbar from "./Actionbar";
import { usePopup } from "@/components/admin/connectors/Popup";
import OpenApiActionCard from "./OpenApiActionCard";
import { createOAuthConfig, updateOAuthConfig } from "@/lib/oauth/api";
import { updateCustomTool, deleteCustomTool } from "@/lib/tools/openApiService";
import { updateToolStatus } from "@/lib/tools/mcpService";
import DisconnectEntityModal from "./modals/DisconnectEntityModal";
import ActionCardSkeleton from "./skeleton/ActionCardSkeleton";
import useOpenApiTools from "@/hooks/useOpenApiTools";

export default function OpenApiPageContent() {
  const {
    openApiTools,
    mutateOpenApiTools,
    isLoading: isOpenApiLoading,
  } = useOpenApiTools();
  const addOpenAPIActionModal = useCreateModal();
  const openAPIAuthModal = useCreateModal();
  const disconnectModal = useCreateModal();
  const { popup, setPopup } = usePopup();
  const [selectedTool, setSelectedTool] = useState<ToolSnapshot | null>(null);
  const [toolBeingEdited, setToolBeingEdited] = useState<ToolSnapshot | null>(
    null
  );
  const [toolPendingDisconnect, setToolPendingDisconnect] =
    useState<ToolSnapshot | null>(null);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [showSharedOverlay, setShowSharedOverlay] = useState(false);

  useEffect(() => {
    const anyModalOpen =
      addOpenAPIActionModal.isOpen ||
      openAPIAuthModal.isOpen ||
      disconnectModal.isOpen;
    setShowSharedOverlay(anyModalOpen);
  }, [
    addOpenAPIActionModal.isOpen,
    openAPIAuthModal.isOpen,
    disconnectModal.isOpen,
  ]);

  const handleOpenAuthModal = useCallback(
    (tool: ToolSnapshot) => {
      setSelectedTool(tool);
      openAPIAuthModal.toggle(true);
    },
    [openAPIAuthModal]
  );

  const resetAuthModal = useCallback(() => {
    setSelectedTool(null);
    openAPIAuthModal.toggle(false);
  }, [openAPIAuthModal]);

  const handleConnect = useCallback(
    async (values: OpenAPIAuthFormValues) => {
      if (!selectedTool) {
        throw new Error("No OpenAPI action selected for authentication.");
      }

      try {
        if (values.authMethod === "oauth") {
          const parsedScopes = values.scopes
            .split(",")
            .map((scope) => scope.trim())
            .filter(Boolean);
          const trimmedClientId = values.clientId.trim();
          const trimmedClientSecret = values.clientSecret.trim();

          let oauthConfigId = selectedTool.oauth_config_id ?? null;

          if (oauthConfigId) {
            await updateOAuthConfig(oauthConfigId, {
              authorization_url: values.authorizationUrl,
              token_url: values.tokenUrl,
              scopes: parsedScopes,
              ...(trimmedClientId ? { client_id: trimmedClientId } : {}),
              ...(trimmedClientSecret
                ? { client_secret: trimmedClientSecret }
                : {}),
            });
          } else {
            const oauthConfig = await createOAuthConfig({
              name: `${selectedTool.name} OAuth`,
              authorization_url: values.authorizationUrl,
              token_url: values.tokenUrl,
              client_id: trimmedClientId,
              client_secret: trimmedClientSecret,
              scopes: parsedScopes.length ? parsedScopes : undefined,
            });
            oauthConfigId = oauthConfig.id;
          }

          const response = await updateCustomTool(selectedTool.id, {
            custom_headers: [],
            passthrough_auth: false,
            oauth_config_id: oauthConfigId,
          });

          if (response.error) {
            throw new Error(response.error);
          }

          setPopup({
            message: `${selectedTool.name} authentication ${
              selectedTool.oauth_config_id ? "updated" : "saved"
            } successfully.`,
            type: "success",
          });
        } else if (values.authMethod === "custom-header") {
          const customHeaders = values.headers
            .map(({ key, value }) => ({
              key: key.trim(),
              value: value.trim(),
            }))
            .filter(({ key, value }) => key && value);

          const response = await updateCustomTool(selectedTool.id, {
            custom_headers: customHeaders,
            passthrough_auth: false,
            oauth_config_id: null,
          });

          if (response.error) {
            throw new Error(response.error);
          }

          setPopup({
            message: `${selectedTool.name} authentication headers saved successfully.`,
            type: "success",
          });
        } else if (values.authMethod === "pt-oauth") {
          const response = await updateCustomTool(selectedTool.id, {
            passthrough_auth: true,
            oauth_config_id: null,
            custom_headers: [],
          });
          if (response.error) {
            throw new Error(response.error);
          }
          setPopup({
            message: `${selectedTool.name} authentication passthrough saved successfully.`,
            type: "success",
          });
        }

        await mutateOpenApiTools();
        setSelectedTool(null);
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Failed to save authentication settings.";
        setPopup({
          message,
          type: "error",
        });
        throw error;
      }
    },
    [selectedTool, mutateOpenApiTools, setPopup]
  );

  const handleManageTool = useCallback(
    (tool: ToolSnapshot) => {
      setToolBeingEdited(tool);
      addOpenAPIActionModal.toggle(true);
    },
    [addOpenAPIActionModal]
  );

  const handleEditAuthenticationFromModal = useCallback(
    (tool: ToolSnapshot) => {
      setSelectedTool(tool);
      openAPIAuthModal.toggle(true);
    },
    [openAPIAuthModal]
  );

  const handleDisableTool = useCallback(
    async (tool: ToolSnapshot) => {
      try {
        await updateToolStatus(tool.id, false);

        setPopup({
          message: `${tool.name} has been disconnected.`,
          type: "success",
        });

        await mutateOpenApiTools();
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : "Failed to disconnect OpenAPI action.";
        setPopup({
          message,
          type: "error",
        });
        throw error instanceof Error
          ? error
          : new Error("Failed to disconnect OpenAPI action.");
      }
    },
    [mutateOpenApiTools, setPopup]
  );

  const handleOpenDisconnectModal = useCallback(
    (tool: ToolSnapshot) => {
      setToolPendingDisconnect(tool);
      addOpenAPIActionModal.toggle(false);
      disconnectModal.toggle(true);
    },
    [disconnectModal, addOpenAPIActionModal]
  );

  const handleConfirmDisconnectFromModal = useCallback(async () => {
    if (!toolPendingDisconnect) {
      return;
    }

    try {
      setIsDisconnecting(true);
      await handleDisableTool(toolPendingDisconnect);
    } finally {
      setIsDisconnecting(false);
      disconnectModal.toggle(false);
      setToolPendingDisconnect(null);
    }
  }, [disconnectModal, handleDisableTool, toolPendingDisconnect]);

  const executeDeleteTool = useCallback(
    async (tool: ToolSnapshot) => {
      try {
        setIsDeleting(true);
        const response = await deleteCustomTool(tool.id);
        if (response.data) {
          setPopup({
            message: `${tool.name} deleted successfully.`,
            type: "success",
          });
          await mutateOpenApiTools();
        } else {
          throw new Error(response.error || "Failed to delete tool.");
        }
      } catch (error) {
        console.error("Failed to delete OpenAPI tool", error);
        setPopup({
          message:
            error instanceof Error
              ? error.message
              : "An unexpected error occurred while deleting the tool.",
          type: "error",
        });
        throw error;
      } finally {
        setIsDeleting(false);
      }
    },
    [mutateOpenApiTools, setPopup]
  );

  const handleDeleteToolFromModal = useCallback(async () => {
    if (!toolPendingDisconnect || isDeleting) {
      return;
    }

    try {
      await executeDeleteTool(toolPendingDisconnect);
    } finally {
      disconnectModal.toggle(false);
      setToolPendingDisconnect(null);
    }
  }, [disconnectModal, executeDeleteTool, isDeleting, toolPendingDisconnect]);

  const handleDeleteTool = useCallback(
    async (tool: ToolSnapshot) => {
      if (isDeleting) return;
      await executeDeleteTool(tool);
    },
    [executeDeleteTool, isDeleting]
  );

  const handleAddAction = useCallback(() => {
    setToolBeingEdited(null);
    addOpenAPIActionModal.toggle(true);
  }, [addOpenAPIActionModal]);

  const handleAddModalClose = useCallback(() => {
    setToolBeingEdited(null);
  }, []);

  const handleRenameTool = useCallback(
    async (toolId: number, newName: string) => {
      try {
        const response = await updateCustomTool(toolId, { name: newName });
        if (response.error) {
          throw new Error(response.error);
        }
        setPopup({
          message: "OpenAPI action renamed successfully",
          type: "success",
        });
        await mutateOpenApiTools();
      } catch (error) {
        console.error("Error renaming tool:", error);
        setPopup({
          message:
            error instanceof Error
              ? error.message
              : "Failed to rename OpenAPI action",
          type: "error",
        });
        throw error; // Re-throw so ButtonRenaming can handle it
      }
    },
    [setPopup, mutateOpenApiTools]
  );

  const authenticationModalTitle = useMemo(() => {
    if (!selectedTool) {
      return "Authenticate OpenAPI Action";
    }
    const hasExistingAuth =
      Boolean(selectedTool.oauth_config_id) ||
      Boolean(selectedTool.custom_headers?.length);
    const prefix = hasExistingAuth
      ? "Update authentication for"
      : "Authenticate";
    return `${prefix} ${selectedTool.name}`;
  }, [selectedTool]);

  const authenticationDefaultMethod = useMemo<AuthMethod>(() => {
    if (!selectedTool) {
      return "oauth";
    }
    return selectedTool.custom_headers?.length ? "custom-header" : "oauth";
  }, [selectedTool]);

  // Filter tools based on search query
  const filteredTools = useMemo(() => {
    if (!openApiTools) return [];
    if (!searchQuery.trim()) return openApiTools;

    const query = searchQuery.toLowerCase();
    return openApiTools.filter(
      (tool) =>
        tool.name.toLowerCase().includes(query) ||
        tool.description?.toLowerCase().includes(query)
    );
  }, [openApiTools, searchQuery]);

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {popup}
      {showSharedOverlay && (
        <div
          className="fixed inset-0 z-modal-overlay bg-mask-03 backdrop-blur-03 pointer-events-none data-[state=open]:animate-in data-[state=open]:fade-in-0"
          data-state="open"
          aria-hidden="true"
        />
      )}

      <div className="flex-shrink-0 mb-4">
        <Actionbar
          hasActions={isOpenApiLoading || (openApiTools?.length ?? 0) > 0}
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          onAddAction={handleAddAction}
          buttonText="Add OpenAPI Action"
        />
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="flex flex-col gap-4 w-full pb-4">
          {isOpenApiLoading ? (
            <>
              <ActionCardSkeleton />
              <ActionCardSkeleton />
            </>
          ) : (
            filteredTools.map((tool) => (
              <OpenApiActionCard
                key={tool.id}
                tool={tool}
                onAuthenticate={handleOpenAuthModal}
                onManage={handleManageTool}
                onDelete={handleDeleteTool}
                onRename={handleRenameTool}
                mutateOpenApiTools={mutateOpenApiTools}
                setPopup={setPopup}
                onOpenDisconnectModal={handleOpenDisconnectModal}
              />
            ))
          )}
        </div>
      </div>

      <addOpenAPIActionModal.Provider>
        <AddOpenAPIActionModal
          skipOverlay
          setPopup={setPopup}
          existingTool={toolBeingEdited}
          onEditAuthentication={handleEditAuthenticationFromModal}
          onDisconnectTool={(tool: ToolSnapshot) => {
            handleOpenDisconnectModal(tool);
            resetAuthModal();
          }}
          onSuccess={(tool) => {
            setSelectedTool(tool);
            openAPIAuthModal.toggle(true);
            mutateOpenApiTools();
          }}
          onUpdate={() => {
            mutateOpenApiTools();
          }}
          onClose={handleAddModalClose}
        />
      </addOpenAPIActionModal.Provider>
      <openAPIAuthModal.Provider>
        <OpenAPIAuthenticationModal
          isOpen={openAPIAuthModal.isOpen}
          skipOverlay
          onClose={resetAuthModal}
          title={authenticationModalTitle}
          entityName={selectedTool?.name ?? null}
          defaultMethod={authenticationDefaultMethod}
          oauthConfigId={selectedTool?.oauth_config_id ?? null}
          initialHeaders={selectedTool?.custom_headers ?? null}
          passthroughOAuthEnabled={selectedTool?.passthrough_auth ?? false}
          onConnect={handleConnect}
          onSkip={resetAuthModal}
        />
      </openAPIAuthModal.Provider>

      <DisconnectEntityModal
        isOpen={disconnectModal.isOpen}
        onClose={() => {
          disconnectModal.toggle(false);
          setToolPendingDisconnect(null);
        }}
        name={toolPendingDisconnect?.name ?? null}
        onConfirmDisconnect={handleConfirmDisconnectFromModal}
        onConfirmDisconnectAndDelete={handleDeleteToolFromModal}
        isDisconnecting={isDisconnecting || isDeleting}
        skipOverlay
      />
    </div>
  );
}
