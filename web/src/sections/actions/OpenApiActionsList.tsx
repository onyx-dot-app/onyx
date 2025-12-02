import { ToolSnapshot } from "@/lib/tools/types";
import React, { useCallback, useMemo, useState } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import OpenAPIAuthenticationModal, {
  OpenAPIAuthFormValues,
} from "./modals/OpenAPIAuthenticationModal";
import AddOpenAPIActionModal from "./modals/AddOpenAPIActionModal";
import Actionbar from "./Actionbar";
import { usePopup } from "@/components/admin/connectors/Popup";
import OpenApiActionCard from "./OpenApiActionCard";
import { createOAuthConfig } from "@/lib/oauth/api";
import { updateCustomTool } from "@/lib/tools/openApiService";

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
          const scopes = values.scopes
            .split(",")
            .map((scope) => scope.trim())
            .filter(Boolean);

          const oauthConfig = await createOAuthConfig({
            name: `${selectedTool.name} OAuth`,
            authorization_url: values.authorizationUrl,
            token_url: values.tokenUrl,
            client_id: values.clientId,
            client_secret: values.clientSecret,
            scopes: scopes.length ? scopes : undefined,
          });

          const response = await updateCustomTool(selectedTool.id, {
            custom_headers: [],
            passthrough_auth: false,
            oauth_config_id: oauthConfig.id,
          });

          if (response.error) {
            throw new Error(response.error);
          }
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
        }

        setPopup({
          message: `${selectedTool.name} authentication saved successfully.`,
          type: "success",
        });

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

  const authenticationModalTitle = useMemo(() => {
    if (!selectedTool) {
      return "Authenticate OpenAPI Action";
    }
    return `Authenticate ${selectedTool.name}`;
  }, [selectedTool]);

  return (
    <>
      {popup}
      <Actionbar
        hasActions={false}
        onAddAction={() => {
          addOpenAPIActionModal.toggle(true);
        }}
        buttonText="Add OpenAPI Action"
      />
      {openApiTools?.map((tool) => (
        <OpenApiActionCard
          key={tool.id}
          tool={tool}
          onAuthenticate={handleOpenAuthModal}
          mutateOpenApiTools={mutateOpenApiTools}
          setPopup={setPopup}
        />
      ))}

      <addOpenAPIActionModal.Provider>
        <AddOpenAPIActionModal
          skipOverlay
          setPopup={setPopup}
          onSuccess={(tool) => {
            setSelectedTool(tool);
            openAPIAuthModal.toggle(true);
            mutateOpenApiTools();
          }}
        />
      </addOpenAPIActionModal.Provider>
      <openAPIAuthModal.Provider>
        <OpenAPIAuthenticationModal
          isOpen={openAPIAuthModal.isOpen}
          onClose={resetAuthModal}
          title={authenticationModalTitle}
          defaultMethod="oauth"
          onConnect={handleConnect}
          onSkip={resetAuthModal}
        />
      </openAPIAuthModal.Provider>
    </>
  );
}
