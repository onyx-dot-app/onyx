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
import { updateCustomTool } from "@/lib/tools/openApiService";
import { updateToolStatus } from "@/lib/tools/mcpService";

export default function OpenApiActionsList() {
  const { data: openApiTools, mutate: mutateOpenApiTools } = useSWR<
    ToolSnapshot[]
  >("/api/tool/openapi", errorHandlingFetcher, {
    refreshInterval: 10000,
  });
  const addOpenAPIActionModal = useCreateModal();
  const openAPIAuthModal = useCreateModal();
  const { popup, setPopup } = usePopup();
  const [selectedTool, setSelectedTool] = useState<ToolSnapshot | null>(null);
  const [toolBeingEdited, setToolBeingEdited] = useState<ToolSnapshot | null>(
    null
  );

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

        setToolBeingEdited((current) =>
          current && current.id === tool.id
            ? { ...current, enabled: false }
            : current
        );
        setSelectedTool((current) =>
          current && current.id === tool.id
            ? { ...current, enabled: false }
            : current
        );
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
        />
      ))}

      <addOpenAPIActionModal.Provider>
        <AddOpenAPIActionModal
          skipOverlay
          setPopup={setPopup}
          existingTool={toolBeingEdited}
          onEditAuthentication={handleEditAuthenticationFromModal}
          onDisconnectTool={handleDisableTool}
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
          defaultMethod={authenticationDefaultMethod}
          oauthConfigId={selectedTool?.oauth_config_id ?? null}
          initialHeaders={selectedTool?.custom_headers ?? null}
          onConnect={handleConnect}
          onSkip={resetAuthModal}
        />
      </openAPIAuthModal.Provider>
    </>
  );
}
