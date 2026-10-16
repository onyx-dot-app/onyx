"use client";

import { ToolSnapshot } from "@/lib/tools/types";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslations } from "next-intl";
import { useCreateModal } from "@opal/components";
import OpenAPIAuthenticationModal, {
  OpenAPIAuthFormValues,
} from "@/sections/actions/modals/OpenAPIAuthenticationModal";
import AddOpenAPIActionModal from "@/sections/actions/modals/AddOpenAPIActionModal";
import { toast } from "@opal/layouts";
import { oauthConfigRequest } from "@/lib/oauth/config";
import { createOAuthConfig, updateOAuthConfig } from "@/lib/oauth/api";
import {
  updateCustomTool,
  deleteCustomTool,
  type ToolUpdatePayload,
} from "@/lib/tools/svc";
import { updateToolStatus } from "@/lib/tools/svc";
import DisconnectEntityModal from "@/sections/actions/modals/DisconnectEntityModal";

export interface OpenApiActionDialogActions {
  add: () => void;
  manage: (tool: ToolSnapshot) => void;
  authenticate: (tool: ToolSnapshot) => void;
  disconnect: (tool: ToolSnapshot) => void;
  delete: (tool: ToolSnapshot) => Promise<void>;
  rename: (toolId: number, newName: string) => Promise<void>;
}

interface OpenApiActionDialogsProps {
  initialTool?: ToolSnapshot;
  onChanged: () => Promise<void>;
  onClosed?: () => void;
  children?: (actions: OpenApiActionDialogActions) => ReactNode;
}

/** Owns the OpenAPI configuration workflow shared by Actions and Craft Apps. */
export default function OpenApiActionDialogs({
  initialTool,
  onChanged,
  onClosed,
  children,
}: OpenApiActionDialogsProps) {
  const t = useTranslations("actions");
  const addOpenAPIActionModal = useCreateModal();
  const openedToolId = useRef<number | null>(null);
  const openAPIAuthModal = useCreateModal();
  const disconnectModal = useCreateModal();
  const [selectedTool, setSelectedTool] = useState<ToolSnapshot | null>(null);
  const [toolBeingEdited, setToolBeingEdited] = useState<ToolSnapshot | null>(
    null
  );
  const [toolPendingDisconnect, setToolPendingDisconnect] =
    useState<ToolSnapshot | null>(null);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const wasOpen = useRef(false);
  const showSharedOverlay =
    addOpenAPIActionModal.isOpen ||
    openAPIAuthModal.isOpen ||
    disconnectModal.isOpen;

  useEffect(() => {
    if (wasOpen.current && !showSharedOverlay) onClosed?.();
    wasOpen.current = showSharedOverlay;
  }, [showSharedOverlay, onClosed]);

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
        let payload: ToolUpdatePayload;
        let successMessage: string;
        if (values.authMethod === "oauth") {
          let oauthConfigId = selectedTool.oauth_config_id ?? null;
          const config = oauthConfigRequest(values, Boolean(oauthConfigId));

          if (oauthConfigId) {
            await updateOAuthConfig(oauthConfigId, {
              ...config,
              client_id: config.client_id || undefined,
              client_secret: config.client_secret || undefined,
            });
          } else {
            const oauthConfig = await createOAuthConfig({
              ...config,
              name: `${selectedTool.name} OAuth`,
            });
            oauthConfigId = oauthConfig.id;
          }

          payload = {
            custom_headers: [],
            passthrough_auth: false,
            oauth_config_id: oauthConfigId,
          };
          successMessage = selectedTool.oauth_config_id
            ? t("openApiPage.toasts.authUpdated", { name: selectedTool.name })
            : t("openApiPage.toasts.authSaved", { name: selectedTool.name });
        } else if (values.authMethod === "custom-header") {
          const customHeaders = values.headers
            .map(({ key, value }) => ({
              key: key.trim(),
              value: value.trim(),
            }))
            .filter(({ key, value }) => key && value);

          payload = {
            custom_headers: customHeaders,
            passthrough_auth: false,
            oauth_config_id: null,
          };
          successMessage = t("openApiPage.toasts.authHeadersSaved", {
            name: selectedTool.name,
          });
        } else if (values.authMethod === "pt-oauth") {
          payload = {
            passthrough_auth: true,
            oauth_config_id: null,
            custom_headers: [],
          };
          successMessage = t("openApiPage.toasts.authPassthroughSaved", {
            name: selectedTool.name,
          });
        } else {
          throw new Error("Unsupported OpenAPI authentication method.");
        }

        const response = await updateCustomTool(selectedTool.id, payload);
        if (response.error) throw new Error(response.error);
        toast.success(successMessage);

        await onChanged();
        setSelectedTool(null);
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : t("openApiPage.toasts.authSaveFailed");
        toast.error(message);
        throw error;
      }
    },
    [selectedTool, onChanged, t]
  );

  const handleManageTool = useCallback(
    (tool: ToolSnapshot) => {
      setToolBeingEdited(tool);
      addOpenAPIActionModal.toggle(true);
    },
    [addOpenAPIActionModal]
  );

  useEffect(() => {
    if (!initialTool) {
      openedToolId.current = null;
      return;
    }
    if (openedToolId.current === initialTool.id) return;
    openedToolId.current = initialTool.id;
    handleManageTool(initialTool);
  }, [initialTool, handleManageTool]);

  const handleDisableTool = useCallback(
    async (tool: ToolSnapshot) => {
      try {
        await updateToolStatus(tool.id, false);

        toast.success(
          t("openApiPage.toasts.toolDisconnected", { name: tool.name })
        );

        await onChanged();
      } catch (error) {
        const message =
          error instanceof Error
            ? error.message
            : t("openApiPage.toasts.disconnectFailed");
        toast.error(message);
        throw error instanceof Error ? error : new Error(message);
      }
    },
    [onChanged, t]
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
      disconnectModal.toggle(false);
      setToolPendingDisconnect(null);
    } catch {
      // The mutation reports the error; retain the dialog for retry.
    } finally {
      setIsDisconnecting(false);
    }
  }, [disconnectModal, handleDisableTool, toolPendingDisconnect]);

  const executeDeleteTool = useCallback(
    async (tool: ToolSnapshot) => {
      if (isDeleting) return;
      try {
        setIsDeleting(true);
        const response = await deleteCustomTool(tool.id);
        if (response.data) {
          toast.success(
            t("openApiPage.toasts.toolDeleted", { name: tool.name })
          );
          await onChanged();
        } else {
          throw new Error(
            response.error || t("openApiPage.toasts.deleteFailed")
          );
        }
      } catch (error) {
        console.error("Failed to delete OpenAPI tool", error);
        toast.error(
          error instanceof Error
            ? error.message
            : t("openApiPage.toasts.deleteUnexpectedError")
        );
        throw error;
      } finally {
        setIsDeleting(false);
      }
    },
    [isDeleting, onChanged, t]
  );

  const handleDeleteToolFromModal = useCallback(async () => {
    if (!toolPendingDisconnect || isDeleting) {
      return;
    }

    try {
      await executeDeleteTool(toolPendingDisconnect);
      disconnectModal.toggle(false);
      setToolPendingDisconnect(null);
    } catch {
      // The mutation reports the error; retain the dialog for retry.
    }
  }, [disconnectModal, executeDeleteTool, isDeleting, toolPendingDisconnect]);

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
        toast.success(t("openApiPage.toasts.actionRenamed"));
        await onChanged();
      } catch (error) {
        console.error("Error renaming tool:", error);
        toast.error(
          error instanceof Error
            ? error.message
            : t("openApiPage.toasts.renameFailed")
        );
        throw error; // Re-throw so ButtonRenaming can handle it
      }
    },
    [onChanged, t]
  );

  const authenticationModalTitle = useMemo(() => {
    if (!selectedTool) {
      return t("openApiPage.authModal.defaultTitle");
    }
    const hasExistingAuth =
      Boolean(selectedTool.oauth_config_id) ||
      Boolean(selectedTool.custom_headers?.length) ||
      selectedTool.passthrough_auth;
    return hasExistingAuth
      ? t("openApiPage.authModal.updateTitle", { name: selectedTool.name })
      : t("openApiPage.authModal.authenticateTitle", {
          name: selectedTool.name,
        });
  }, [selectedTool, t]);

  return (
    <>
      {children?.({
        add: handleAddAction,
        manage: handleManageTool,
        authenticate: handleOpenAuthModal,
        disconnect: handleOpenDisconnectModal,
        delete: executeDeleteTool,
        rename: handleRenameTool,
      })}
      {showSharedOverlay && (
        <div
          className="fixed inset-0 z-modal-overlay bg-mask-03 backdrop-blur-03 pointer-events-none data-[state=open]:animate-in data-[state=open]:fade-in-0"
          data-state="open"
          aria-hidden="true"
        />
      )}

      <addOpenAPIActionModal.Provider>
        <AddOpenAPIActionModal
          skipOverlay
          existingTool={toolBeingEdited}
          onEditAuthentication={handleOpenAuthModal}
          onDisconnectTool={(tool: ToolSnapshot) => {
            handleOpenDisconnectModal(tool);
            resetAuthModal();
          }}
          onSuccess={async (tool) => {
            setSelectedTool(tool);
            openAPIAuthModal.toggle(true);
            await onChanged();
          }}
          onUpdate={async () => {
            await onChanged();
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
    </>
  );
}
