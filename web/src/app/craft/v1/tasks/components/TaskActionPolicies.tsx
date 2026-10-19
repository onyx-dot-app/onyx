"use client";

import isEqual from "lodash/isEqual";
import { useId, useState } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Button, InputSwitch, Modal, Text } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgPlug } from "@opal/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  AppActionPoliciesView,
  TaskAppActionPolicies,
} from "@/lib/plugins/types";
import {
  getAppTypeLogo,
  type ActionPolicy,
} from "@/app/craft/v1/apps/registry";
import useUserExternalApps from "@/hooks/useUserExternalApps";
import { useCraftMcpServers } from "@/lib/mcp/hooks";
import PluginRowLayout from "@/sections/plugins/PluginRowLayout";
import PluginModalContent from "@/views/admin/PluginsPage/PluginModalContent";
import PolicyEditor from "@/sections/actions/PolicyEditor";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import { UnsavedChangesModalContent } from "@/sections/modals/UnsavedChangesModal";

interface TaskActionPoliciesProps {
  taskId: string | null;
  value: TaskAppActionPolicies[] | null;
  onChange: (value: TaskAppActionPolicies[]) => void;
}

export default function TaskActionPolicies({
  taskId,
  value,
  onChange,
}: TaskActionPoliciesProps) {
  const t = useTranslations("craft.actionPolicies");
  const openingId = useId();
  const [catalog, setCatalog] = useState<AppActionPoliciesView[] | null>(null);
  const { error, mutate } = useSWR<AppActionPoliciesView[], Error>(
    [
      taskId
        ? SWR_KEYS.taskActionPolicies(taskId)
        : SWR_KEYS.personalActionPolicies,
      openingId,
    ],
    ([url]: [string, string]) => errorHandlingFetcher(url),
    {
      revalidateOnFocus: false,
      revalidateOnMount: true,
      onSuccess: (data) => {
        if (catalog !== null) return;
        setCatalog(data);
        onChange(
          data.map((app) => ({
            gated_app_id: app.gated_app_id,
            enabled: taskId !== null && app.enabled === true,
            action_policies: taskId
              ? Object.fromEntries(
                  app.actions
                    .filter((action) => action.stored_policy !== null)
                    .map((action) => [
                      action.action_id,
                      action.stored_policy ?? action.effective_policy,
                    ])
                )
              : {},
          }))
        );
      },
    }
  );
  if (!catalog && error)
    return <ActionPoliciesLoadError retry={() => void mutate()} />;
  return (
    <section className="flex flex-col gap-3">
      <Text font="main-content-emphasis">{t("taskAppsTitle")}</Text>
      <Text font="secondary-body" color="text-03">
        {t(taskId ? "taskDescription" : "newTaskDescription")}
      </Text>
      <AppActionPolicyGroups
        apps={catalog}
        value={value ?? undefined}
        onChange={onChange}
      />
    </section>
  );
}

export function TaskActionPoliciesSummary({ taskId }: { taskId: string }) {
  const t = useTranslations("craft.actionPolicies");
  const { data, error, mutate } = useSWR<AppActionPoliciesView[], Error>(
    SWR_KEYS.taskActionPolicies(taskId),
    errorHandlingFetcher
  );
  return (
    <section className="flex flex-col gap-3">
      <Text font="main-content-emphasis">{t("taskAppsTitle")}</Text>
      {error && !data ? (
        <ActionPoliciesLoadError retry={() => void mutate()} />
      ) : (
        <AppActionPolicyGroups apps={data ?? null} />
      )}
    </section>
  );
}

function ActionPoliciesLoadError({ retry }: { retry: () => void }) {
  const t = useTranslations("craft.actionPolicies");
  return (
    <div>
      <Text font="secondary-body" color="status-error-05">
        {t("loadError")}
      </Text>
      <Button onClick={retry}>{t("retry")}</Button>
    </div>
  );
}

interface AppActionPolicyGroupsProps {
  apps: AppActionPoliciesView[] | null;
  value?: TaskAppActionPolicies[];
  onChange?: (value: TaskAppActionPolicies[]) => void;
}
function AppActionPolicyGroups({
  apps,
  value,
  onChange,
}: AppActionPolicyGroupsProps) {
  const t = useTranslations("craft.actionPolicies");
  const tConnection = useTranslations("craft.inputBar.entryInfo");
  const [editingAppId, setEditingAppId] = useState<number | null>(null);
  const { data: externalApps } = useUserExternalApps();
  const { data: mcpServers } = useCraftMcpServers();
  if (!apps) return <Text font="secondary-body">{t("loading")}</Text>;
  if (apps.length === 0)
    return <Text font="secondary-body">{t("emptyApps")}</Text>;
  const editingApp = apps.find((app) => app.gated_app_id === editingAppId);
  const editingDraft = value?.find((app) => app.gated_app_id === editingAppId);
  return (
    <>
      <div className="divide-y divide-border-01 rounded-16 border border-border-01">
        {apps.map((app) => {
          const connected =
            app.kind === "external_app"
              ? externalApps?.find((item) => item.id === app.target_id)
                  ?.authenticated
              : mcpServers?.mcp_servers.find(
                  (item) => item.id === app.target_id
                )?.craft_connected;
          const draft = value?.find(
            (item) => item.gated_app_id === app.gated_app_id
          );
          const enabled = onChange
            ? draft?.enabled === true
            : app.enabled === true;
          const counts = { auto: 0, ask: 0, disabled: 0 };
          for (const action of app.actions) {
            const policy = action.editable
              ? (draft?.action_policies[action.action_id] ??
                action.effective_policy)
              : action.effective_policy;
            if (policy === "ALWAYS") counts.auto++;
            else if (policy === "ASK") counts.ask++;
            else counts.disabled++;
          }
          return (
            <div key={app.gated_app_id} role="group" aria-label={app.name}>
              <PluginRowLayout
                icon={app.app_type ? getAppTypeLogo(app.app_type) : SvgPlug}
                title={app.name}
                description={t(
                  app.kind === "external_app" ? "externalApp" : "mcpServer"
                )}
                status={
                  <div className="flex flex-col gap-1">
                    <div
                      aria-hidden={!enabled}
                      className={cn(!enabled && "invisible")}
                    >
                      <Text font="secondary-body" color="text-03">
                        {t("policyCounts", counts)}
                      </Text>
                    </div>
                    {connected === false && (
                      <Text font="secondary-body" color="text-03">
                        {tConnection("connectionRequired")}
                      </Text>
                    )}
                  </div>
                }
                action={
                  <>
                    <div
                      aria-hidden={!enabled}
                      className={cn(!enabled && "invisible")}
                    >
                      <Button
                        size="sm"
                        prominence="secondary"
                        disabled={!enabled}
                        onClick={() => setEditingAppId(app.gated_app_id)}
                      >
                        {t(onChange ? "manageActions" : "viewActions")}
                      </Button>
                    </div>
                    <InputSwitch
                      checked={enabled}
                      disabled={!onChange}
                      aria-label={t("enableAppForTask", { app: app.name })}
                      onCheckedChange={(next) =>
                        onChange?.(
                          (value ?? []).map((item) =>
                            item.gated_app_id === app.gated_app_id
                              ? {
                                  ...item,
                                  enabled: next,
                                  action_policies:
                                    next &&
                                    app.enabled === null &&
                                    Object.keys(item.action_policies).length ===
                                      0
                                      ? Object.fromEntries(
                                          app.actions.map((action) => [
                                            action.action_id,
                                            action.effective_policy,
                                          ])
                                        )
                                      : item.action_policies,
                                }
                              : item
                          )
                        )
                      }
                    />
                  </>
                }
              />
            </div>
          );
        })}
      </div>
      {editingApp && (
        <TaskAppActionsModal
          key={editingApp.gated_app_id}
          app={editingApp}
          policies={editingDraft?.action_policies ?? {}}
          onClose={() => setEditingAppId(null)}
          onSave={
            onChange
              ? (policies) => {
                  onChange(
                    (value ?? []).map((app) =>
                      app.gated_app_id === editingApp.gated_app_id
                        ? { ...app, action_policies: policies }
                        : app
                    )
                  );
                  setEditingAppId(null);
                }
              : undefined
          }
        />
      )}
    </>
  );
}

interface TaskAppActionsModalProps {
  app: AppActionPoliciesView;
  policies: Record<string, ActionPolicy>;
  onClose: () => void;
  onSave?: (policies: Record<string, ActionPolicy>) => void;
}

function TaskAppActionsModal({
  app,
  policies: initialPolicies,
  onClose,
  onSave,
}: TaskAppActionsModalProps) {
  const t = useTranslations("craft.actionPolicies");
  const [policies, setPolicies] = useState(initialPolicies);
  const isDirty = !isEqual(policies, initialPolicies);
  const unsavedChanges = useUnsavedChangesGuard({ isDirty });
  function requestClose() {
    if (unsavedChanges.confirmationOpen) unsavedChanges.cancelLeave();
    else unsavedChanges.requestLeave(onClose);
  }
  function handleDismiss(event: Event) {
    const alreadyPrevented = event.defaultPrevented;
    event.preventDefault();
    if (!alreadyPrevented) requestClose();
  }
  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) requestClose();
      }}
    >
      <PluginModalContent
        onInteractOutside={handleDismiss}
        onEscapeKeyDown={handleDismiss}
      >
        {unsavedChanges.confirmationOpen ? (
          <UnsavedChangesModalContent
            onCancel={unsavedChanges.cancelLeave}
            onDiscard={unsavedChanges.discardAndLeave}
          />
        ) : null}
        <div
          hidden={unsavedChanges.confirmationOpen}
          className={cn(
            unsavedChanges.confirmationOpen ? "hidden" : "contents"
          )}
        >
          <Modal.Header
            title={t("appTitle", { name: app.name })}
            description={onSave ? t("taskModalDescription") : undefined}
            onClose={requestClose}
          />
          <Modal.Body>
            <PolicyEditor
              showTitle={false}
              items={app.actions.map((action) => ({
                id: action.action_id,
                name: action.normalised_name,
                description: action.description,
                defaultPolicy: action.effective_policy,
                editable: action.editable,
                lockReason: action.lock_reason,
              }))}
              policies={policies}
              onChange={onSave ? setPolicies : undefined}
              onReset={
                onSave
                  ? () =>
                      setPolicies((current) => ({
                        ...current,
                        ...Object.fromEntries(
                          app.actions
                            .filter((action) => action.editable)
                            .map((action) => [
                              action.action_id,
                              action.workspace_policy,
                            ])
                        ),
                      }))
                  : undefined
              }
              resetLabel={t("resetAll")}
            />
          </Modal.Body>
          <Modal.Footer>
            <Button prominence="secondary" onClick={requestClose}>
              {t(onSave ? "cancel" : "close")}
            </Button>
            {onSave && (
              <Button disabled={!isDirty} onClick={() => onSave(policies)}>
                {t("saveChanges")}
              </Button>
            )}
          </Modal.Footer>
        </div>
      </PluginModalContent>
    </Modal>
  );
}
