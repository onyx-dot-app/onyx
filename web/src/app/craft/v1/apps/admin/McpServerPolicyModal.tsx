"use client";

import isEqual from "lodash/isEqual";
import { useId, useState } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Button, Modal, Text } from "@opal/components";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { MCPServer } from "@/lib/mcp/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { saveAppActionPolicies } from "@/app/craft/services/apiServices";
import { ActionPoliciesModal } from "@/app/craft/v1/apps/action-policies/ActionPolicyRows";
import UserManagementSwitch from "@/app/craft/v1/apps/action-policies/UserManagementSwitch";
import type { AppActionPoliciesView } from "@/app/craft/v1/apps/action-policies/types";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";

interface McpServerPolicyModalProps {
  onClose: () => void;
  onSaved: () => void;
  server: MCPServer;
}
/** Edit Craft approval policies for an MCP server. Server URL, authentication,
 * and tool refresh remain on the MCP actions page. */
export default function McpServerPolicyModal(props: McpServerPolicyModalProps) {
  const t = useTranslations("craft.actionPolicies");
  // Each opening owns its request, including when an earlier opening is still loading.
  const openingId = useId();
  const [initialApp, setInitialApp] = useState<AppActionPoliciesView | null>(
    null
  );
  const { error, mutate } = useSWR<AppActionPoliciesView, Error>(
    [
      SWR_KEYS.appActionPolicies("mcp_server", props.server.id, true),
      openingId,
    ],
    ([url]: [string, string]) => errorHandlingFetcher(url),
    {
      revalidateOnMount: true,
      revalidateOnFocus: false,
      onSuccess: (app) => setInitialApp((current) => current ?? app),
    }
  );
  if (initialApp)
    return (
      <McpPolicyForm
        key={initialApp.gated_app_id}
        {...props}
        app={initialApp}
        onSaved={async () => {
          await mutate();
          props.onSaved();
        }}
      />
    );
  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) props.onClose();
      }}
    >
      <Modal.Content>
        <Modal.Header title={t("title")} />
        <Modal.Body>
          <Text font="main-content-body">
            {error ? t("loadError") : t("loading")}
          </Text>
          {error && <Button onClick={() => void mutate()}>{t("retry")}</Button>}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
function McpPolicyForm({
  onClose,
  onSaved,
  server,
  app,
}: Omit<McpServerPolicyModalProps, "onSaved"> & {
  app: AppActionPoliciesView;
  onSaved: () => Promise<void>;
}) {
  const t = useTranslations("craft.apps.mcpPolicy");
  const tActionPolicies = useTranslations("craft.actionPolicies");
  const [usersCanManagePolicies, setUsersCanManagePolicies] = useState(
    app.users_can_manage_policies
  );
  const [initialPolicies] = useState<Record<string, ActionPolicy>>(() =>
    Object.fromEntries(
      app.actions.map((action) => [action.action_id, action.effective_policy])
    )
  );
  const [policies, setPolicies] = useState(initialPolicies);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save() {
    setSaving(true);
    setError(null);
    try {
      await saveAppActionPolicies(
        "workspace",
        app.gated_app_id,
        policies,
        tActionPolicies("saveError"),
        usersCanManagePolicies
      );
      await onSaved();
      onClose();
    } catch (error) {
      setError(
        error instanceof Error ? error.message : tActionPolicies("saveError")
      );
    } finally {
      setSaving(false);
    }
  }
  return (
    <ActionPoliciesModal
      onClose={onClose}
      title={t("title", { name: server.name })}
      description={t("description")}
      items={app.actions.map((action) => ({
        id: action.action_id,
        name: action.normalised_name,
        description: action.description,
        fallbackPolicy: "ASK",
      }))}
      policies={policies}
      onChange={setPolicies}
      onReset={() => setPolicies({})}
      resetLabel={tActionPolicies("resetDefaults")}
      isDirty={
        !isEqual(policies, initialPolicies) ||
        usersCanManagePolicies !== app.users_can_manage_policies
      }
      saving={saving}
      saveLabel={t("saveButton")}
      onSave={() => void save()}
    >
      <UserManagementSwitch
        disabled={saving}
        value={usersCanManagePolicies}
        onChange={setUsersCanManagePolicies}
      />
      {error && (
        <Text font="secondary-body" color="status-error-05">
          {error}
        </Text>
      )}
    </ActionPoliciesModal>
  );
}
