"use client";
import isEqual from "lodash/isEqual";
import { useId, useState } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Button, Modal, Text } from "@opal/components";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { saveAppActionPolicies } from "@/app/craft/services/apiServices";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";
import type { AppActionPoliciesView } from "@/app/craft/v1/apps/action-policies/types";
import { ActionPoliciesModal } from "@/app/craft/v1/apps/action-policies/ActionPolicyRows";

interface PersonalActionPoliciesModalProps {
  kind: AppActionPoliciesView["kind"];
  targetId: number;
  onClose: () => void;
}
export default function PersonalActionPoliciesModal({
  kind,
  targetId,
  onClose,
}: PersonalActionPoliciesModalProps) {
  const t = useTranslations("craft.actionPolicies");
  // Each opening owns its request, including when an earlier opening is still loading.
  const openingId = useId();
  const [initialApp, setInitialApp] = useState<AppActionPoliciesView | null>(
    null
  );
  const { error, mutate } = useSWR<AppActionPoliciesView, Error>(
    [SWR_KEYS.appActionPolicies(kind, targetId), openingId],
    ([url]: [string, string]) => errorHandlingFetcher(url),
    {
      revalidateOnMount: true,
      revalidateOnFocus: false,
      onSuccess: (app) => setInitialApp((current) => current ?? app),
    }
  );
  if (initialApp)
    return (
      <PersonalActionPoliciesForm
        key={initialApp.gated_app_id}
        app={initialApp}
        onClose={onClose}
        onSaved={async () => {
          await mutate();
        }}
      />
    );
  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Modal.Content width="lg" height="lg">
        <Modal.Header
          title={t("title")}
          description={t("personalDescription")}
        />
        <Modal.Body>
          <Text font="main-content-body">
            {error ? t("loadError") : t("loading")}
          </Text>
          {error && (
            <Button prominence="secondary" onClick={() => void mutate()}>
              {t("retry")}
            </Button>
          )}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
interface PersonalActionPoliciesFormProps {
  app: AppActionPoliciesView;
  onClose: () => void;
  onSaved: () => Promise<void>;
}
function PersonalActionPoliciesForm({
  app,
  onClose,
  onSaved,
}: PersonalActionPoliciesFormProps) {
  const t = useTranslations("craft.actionPolicies");
  const [initialPolicies] = useState<Record<string, ActionPolicy>>(() =>
    Object.fromEntries(
      app.actions
        .filter((a) => a.editable || a.stored_policy !== null)
        .map((a) => [a.action_id, a.stored_policy ?? a.effective_policy])
    )
  );
  const [policies, setPolicies] = useState(initialPolicies);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save(nextPolicies: Record<string, ActionPolicy>) {
    setSaving(true);
    setError(null);
    try {
      await saveAppActionPolicies(
        "personal",
        app.gated_app_id,
        nextPolicies,
        t("saveError")
      );
      await onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("saveError"));
    } finally {
      setSaving(false);
    }
  }
  return (
    <ActionPoliciesModal
      title={t("appTitle", { name: app.name })}
      description={t("personalDescription")}
      items={app.actions.map((action) => ({
        id: action.action_id,
        name: action.normalised_name,
        description: action.description,
        fallbackPolicy: action.editable
          ? action.workspace_policy
          : action.effective_policy,
        editable: action.editable,
        lockReason: action.lock_reason,
      }))}
      policies={policies}
      onChange={app.users_can_manage_policies ? setPolicies : undefined}
      onReset={
        app.users_can_manage_policies ? () => setPolicies({}) : undefined
      }
      isDirty={!isEqual(policies, initialPolicies)}
      saving={saving}
      onClose={onClose}
      onSave={
        app.users_can_manage_policies ? () => void save(policies) : undefined
      }
      saveLabel={t("save")}
    >
      {error && (
        <Text font="secondary-body" color="status-error-05">
          {error}
        </Text>
      )}
    </ActionPoliciesModal>
  );
}
