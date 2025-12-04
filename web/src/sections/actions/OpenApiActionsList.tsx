import { ToolSnapshot } from "@/lib/tools/types";
import React, { useCallback, useMemo, useState } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
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

export default function OpenApiActionsList() {
  const { data: openApiTools, mutate: mutateOpenApiTools } = useSWR<
    ToolSnapshot[]
  >("/api/tool/openapi", errorHandlingFetcher, {
    refreshInterval: 10000,
  });
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
        } else {
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

  const handleDeleteToolFromModal = useCallback(async () => {
    if (!toolPendingDisconnect || isDeleting) {
      return;
    }

    try {
      setIsDeleting(true);
      const response = await deleteCustomTool(toolPendingDisconnect.id);
      if (response.data) {
        setPopup({
          message: `${toolPendingDisconnect.name} deleted successfully.`,
          type: "success",
        });
        await mutateOpenApiTools();
      } else {
        setPopup({
          message: response.error || "Failed to delete tool.",
          type: "error",
        });
      }
    } catch (error) {
      console.error("Failed to delete OpenAPI tool", error);
      setPopup({
        message: "An unexpected error occurred while deleting the tool.",
        type: "error",
      });
    } finally {
      setIsDeleting(false);
      disconnectModal.toggle(false);
      setToolPendingDisconnect(null);
    }
  }, [
    disconnectModal,
    isDeleting,
    mutateOpenApiTools,
    setPopup,
    toolPendingDisconnect,
  ]);

  const handleAddAction = useCallback(() => {
    setToolBeingEdited(null);
    addOpenAPIActionModal.toggle(true);
  }, [addOpenAPIActionModal]);

  const handleAddModalClose = useCallback(() => {
    setToolBeingEdited(null);
  }, []);

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

  return (
    <>
      {popup}
      <Actionbar
        hasActions={false}
        onAddAction={handleAddAction}
        buttonText="Add OpenAPI Action"
      />
      {openApiTools?.map((tool) => (
        <OpenApiActionCard
          key={tool.id}
          tool={tool}
          onAuthenticate={handleOpenAuthModal}
          onManage={handleManageTool}
          mutateOpenApiTools={mutateOpenApiTools}
          setPopup={setPopup}
          onOpenDisconnectModal={handleOpenDisconnectModal}
        />
      ))}

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
          onClose={resetAuthModal}
          title={authenticationModalTitle}
          entityName={selectedTool?.name ?? null}
          defaultMethod={authenticationDefaultMethod}
          oauthConfigId={selectedTool?.oauth_config_id ?? null}
          initialHeaders={selectedTool?.custom_headers ?? null}
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
    </>
  );
}
