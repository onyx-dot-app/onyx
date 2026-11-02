"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Modal } from "@opal/components";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
import { useSWRConfig } from "swr";
import { useDefaultAssistantConfiguration } from "@/lib/agents/hooks";
import { refreshMemberPluginCaches } from "@/lib/plugins/member";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import AddOpenAPIActionModal, {
  type OpenAPICreationDraft,
} from "@/sections/actions/modals/AddOpenAPIActionModal";
import OpenAPIAuthenticationModal, {
  type OpenAPIAuthFormValues,
} from "@/sections/actions/modals/OpenAPIAuthenticationModal";
import { createCustomTool, updateCustomTool } from "@/lib/tools/svc";
import { can } from "@/lib/permissions/resource-actions";
import { saveOpenApiAuthentication } from "@/sections/plugins/openApiWorkflow";

type SchemaDraft = OpenAPICreationDraft;
type CreationStep =
  | { kind: "schema"; draft?: SchemaDraft; auth?: OpenAPIAuthFormValues }
  | {
      kind: "authentication";
      draft: SchemaDraft;
      auth?: OpenAPIAuthFormValues;
    };

interface OpenAPIPluginCreateModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: (toolId: number) => void;
}

export default function OpenAPIPluginCreateModal({
  open,
  ...props
}: OpenAPIPluginCreateModalProps) {
  return open ? <OpenAPIPluginCreateSession {...props} /> : null;
}

function OpenAPIPluginCreateSession({
  onClose,
  onCreated,
}: Omit<OpenAPIPluginCreateModalProps, "open">) {
  const t = useTranslations("actions.plugins.openapi");
  const actions = useTranslations("actions");
  const { refreshOpenApiTools } = useOpenApiTools();
  const defaultChat = useDefaultAssistantConfiguration();
  const [busy, setBusy] = useState(false);
  const { mutate } = useSWRConfig();
  const [step, setStep] = useState<CreationStep>({ kind: "schema" });
  const defaultChatEnabled =
    step.draft?.defaultChatEnabled ?? defaultChat.canEdit;
  const savedId = useRef<number | null>(null);
  const pendingOAuthConfigId = useRef<number | null>(null);
  const completed = useRef(false);
  const active = useRef(true);

  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);

  async function create(values: OpenAPIAuthFormValues) {
    if (step.kind !== "authentication") return;
    if (defaultChat.canEdit && (!defaultChat.data || defaultChat.error))
      throw new Error(
        actions("addOpenApiModal.editConfigsButton.disabledTooltip")
      );
    const existing =
      savedId.current === null
        ? null
        : (await refreshOpenApiTools())?.find(
            (candidate) => candidate.id === savedId.current
          );
    if (savedId.current !== null && !existing)
      throw new Error(
        actions("addOpenApiModal.editConfigsButton.disabledTooltip")
      );
    const response = existing
      ? await updateCustomTool(existing.id, {
          name: step.draft.name,
          description: step.draft.description,
          definition: step.draft.definition,
          oauth_config_id: existing.oauth_config_id ?? null,
        })
      : await createCustomTool({
          name: step.draft.name,
          description: step.draft.description,
          definition: step.draft.definition,
          custom_headers: [],
          passthrough_auth: false,
          enabled: true,
        });
    if (response.error || !response.data)
      throw new Error(
        response.error ?? actions("addOpenApiModal.toasts.createFailed")
      );
    savedId.current = response.data.id;
    const tools = await refreshOpenApiTools();
    const tool = tools?.find((candidate) => candidate.id === savedId.current);
    if (!tool)
      throw new Error(
        actions("addOpenApiModal.editConfigsButton.disabledTooltip")
      );
    if (
      values.authMethod !== "none" ||
      tool.oauth_config_id ||
      tool.passthrough_auth ||
      tool.custom_headers?.length
    ) {
      if (!can(tool, "authenticate"))
        throw new Error(
          actions("addOpenApiModal.editConfigsButton.disabledTooltip")
        );
      await saveOpenApiAuthentication({
        tool,
        values,
        pendingOAuthConfigId: pendingOAuthConfigId.current,
        onOAuthConfigCreated: (id) => {
          pendingOAuthConfigId.current = id;
        },
      });
      if (values.authMethod === "oauth") pendingOAuthConfigId.current = null;
      await refreshOpenApiTools();
    }
    if (defaultChat.canEdit) {
      await defaultChat.updateTools([tool.id], defaultChatEnabled);
      await refreshOpenApiTools();
    }
    await refreshMemberPluginCaches(mutate);
    if (!active.current) return;
    completed.current = true;
    onCreated(response.data.id);
  }

  function close() {
    if (!busy && !completed.current) onClose();
  }

  return (
    <Modal open onOpenChange={(next) => !next && close()}>
      <PluginModalContent>
        {step.kind === "schema" ? (
          <AddOpenAPIActionModal
            presentation="content"
            onBusyChange={setBusy}
            title={t("createTitle")}
            onClose={close}
            initialDefinition={step.draft?.definition}
            initialDescription={step.draft?.description}
            defaultChatEnabled={defaultChatEnabled}
            canManageDefaultChat={defaultChat.canEdit}
            defaultChatReady={Boolean(defaultChat.data) && !defaultChat.error}
            onConfigureAuthentication={(draft) =>
              setStep({ kind: "authentication", draft, auth: step.auth })
            }
          />
        ) : (
          <OpenAPIAuthenticationModal
            presentation="content"
            isOpen
            title={actions("mcpSetup.connectTo", { name: step.draft.name })}
            description=""
            entityName={step.draft.name}
            onBusyChange={setBusy}
            allowNoAuthentication
            defaultMethod="none"
            draftValues={step.auth}
            submitLabel={actions("addOpenApiModal.submitButton.addLabel")}
            onBack={(auth) =>
              setStep({ kind: "schema", draft: step.draft, auth })
            }
            onConnect={create}
            onClose={close}
          />
        )}
      </PluginModalContent>
    </Modal>
  );
}
