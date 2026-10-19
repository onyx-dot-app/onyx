"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useCreateModal } from "@opal/components";
import PluginAvailabilitySwitch from "@/sections/plugins/PluginAvailabilitySwitch";
import { useSWRConfig } from "swr";
import { useDefaultAssistantConfiguration } from "@/lib/agents/hooks";
import { refreshMemberPluginCaches } from "@/lib/plugins/member";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import AddOpenAPIActionModal from "@/sections/actions/modals/AddOpenAPIActionModal";
import OpenAPIAuthenticationModal, {
  type OpenAPIAuthFormValues,
} from "@/sections/actions/modals/OpenAPIAuthenticationModal";
import {
  createCustomTool,
  updateCustomTool,
  updateToolStatus,
} from "@/lib/tools/svc";
import { can } from "@/lib/permissions/resource-actions";
import { saveOpenApiAuthentication } from "@/sections/plugins/openApiWorkflow";

type SchemaDraft = Parameters<typeof createCustomTool>[0];
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
  const [enabled, setEnabled] = useState(true);
  const [busy, setBusy] = useState(false);
  const { mutate } = useSWRConfig();
  const modal = useCreateModal();
  const { toggle } = modal;
  const [step, setStep] = useState<CreationStep>({ kind: "schema" });
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

  useEffect(() => {
    toggle(step.kind === "schema");
  }, [step.kind, toggle]);

  async function create(values: OpenAPIAuthFormValues) {
    if (step.kind !== "authentication") return;
    if (
      enabled &&
      defaultChat.canEdit &&
      (!defaultChat.data || defaultChat.error)
    )
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
      : await createCustomTool({ ...step.draft, enabled });
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
    if (existing && existing.enabled !== enabled)
      await updateToolStatus(existing.id, enabled);
    if (defaultChat.canEdit && enabled) {
      await defaultChat.updateTools([tool.id], true);
      await refreshOpenApiTools();
    }
    await refreshMemberPluginCaches(mutate);
    if (!active.current) return;
    completed.current = true;
    onCreated(response.data.id);
  }

  function close() {
    if (!completed.current) onClose();
  }

  return (
    <>
      <modal.Provider>
        <AddOpenAPIActionModal
          title={t("createTitle")}
          onClose={onClose}
          initialDefinition={step.draft?.definition}
          onConfigureAuthentication={(draft) =>
            setStep({ kind: "authentication", draft, auth: step.auth })
          }
        />
      </modal.Provider>
      {step.kind === "authentication" && (
        <OpenAPIAuthenticationModal
          isOpen
          title={actions("mcpSetup.connectTo", { name: step.draft.name })}
          description=""
          entityName={step.draft.name}
          onBusyChange={setBusy}
          beforeFields={
            <PluginAvailabilitySwitch
              surface="workspace"
              enabled={enabled}
              onChange={setEnabled}
              disabled={busy}
            />
          }
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
    </>
  );
}
