"use client";

import { useId, useState } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  AppActionPoliciesView,
  TaskAppActionPolicies,
} from "@/lib/plugins/types";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";
import { useMemberPlugins, type MemberPlugin } from "@/lib/plugins/member";
import MemberPluginConnectionDialog from "@/sections/plugins/MemberPluginConnectionDialog";
import styles from "@/sections/plugins/PluginsPage.module.css";
import TaskPluginCard from "@/app/craft/v1/tasks/components/TaskPluginCard";
import TaskAppActionsModal from "@/app/craft/v1/tasks/components/TaskAppActionsModal";
import ActionPoliciesLoadError from "@/app/craft/v1/tasks/components/ActionPoliciesLoadError";

function findTaskPlugin(app: AppActionPoliciesView, plugins: MemberPlugin[]) {
  return plugins.find((plugin) =>
    plugin.kind === "external-app"
      ? app.kind === "external_app" && plugin.app.id === app.target_id
      : plugin.kind === "mcp" &&
        app.kind === "mcp_server" &&
        plugin.server.id === app.target_id
  );
}

// Snapshot personal defaults before the first task-specific edit or enable.
function initialActionPolicies(
  app: AppActionPoliciesView,
  policies: Record<string, ActionPolicy>
): Record<string, ActionPolicy> {
  return app.enabled === null && Object.keys(policies).length === 0
    ? Object.fromEntries(
        app.actions.map((action) => [action.action_id, action.effective_policy])
      )
    : policies;
}

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
    <Section height="auto" alignItems="stretch" gap={3}>
      <Text font="main-content-emphasis">{t("taskAppsTitle")}</Text>
      <Text font="secondary-body" color="text-03">
        {t(taskId ? "taskDescription" : "newTaskDescription")}
      </Text>
      <AppActionPolicyGroups
        apps={catalog}
        value={value ?? []}
        onChange={onChange}
      />
    </Section>
  );
}

interface AppActionPolicyGroupsProps {
  apps: AppActionPoliciesView[] | null;
  value: TaskAppActionPolicies[];
  onChange: (value: TaskAppActionPolicies[]) => void;
}
function AppActionPolicyGroups({
  apps,
  value,
  onChange,
}: AppActionPolicyGroupsProps) {
  const t = useTranslations("craft.actionPolicies");
  const tPlugins = useTranslations("actions.memberPlugins.state");
  const { plugins, refresh, errors } = useMemberPlugins({ surface: "craft" });
  const [dialog, setDialog] = useState<{
    kind: "actions" | "connection";
    appId: number;
  } | null>(null);
  if (!apps) return <Text font="secondary-body">{t("loading")}</Text>;
  if (apps.length === 0)
    return <Text font="secondary-body">{t("emptyApps")}</Text>;
  const activeApp = apps.find((app) => app.gated_app_id === dialog?.appId);
  const activeDraft = value.find((app) => app.gated_app_id === dialog?.appId);
  const connectingPlugin =
    activeApp && dialog?.kind === "connection"
      ? findTaskPlugin(activeApp, plugins)
      : undefined;
  const editingApp = dialog?.kind === "actions" ? activeApp : undefined;
  return (
    <>
      {(errors.apps || errors.servers) && (
        <Section height="auto" alignItems="start" gap={2}>
          <Text font="secondary-body" color="status-error-05">
            {tPlugins(errors.apps ? "appsError" : "serversError")}
          </Text>
          <Button prominence="secondary" onClick={() => void refresh()}>
            {t("retry")}
          </Button>
        </Section>
      )}
      <div className={styles.grid}>
        {apps.map((app) => {
          const plugin = findTaskPlugin(app, plugins);
          const draft = value.find(
            (item) => item.gated_app_id === app.gated_app_id
          );
          return (
            <TaskPluginCard
              key={app.gated_app_id}
              app={app}
              enabled={draft?.enabled === true}
              policies={draft?.action_policies ?? {}}
              connection={plugin?.connection}
              onEdit={() =>
                setDialog({ kind: "actions", appId: app.gated_app_id })
              }
              onConnect={() =>
                setDialog({ kind: "connection", appId: app.gated_app_id })
              }
              onToggle={(enabled) =>
                onChange(
                  value.map((item) =>
                    item.gated_app_id === app.gated_app_id
                      ? {
                          ...item,
                          enabled,
                          action_policies: enabled
                            ? initialActionPolicies(app, item.action_policies)
                            : item.action_policies,
                        }
                      : item
                  )
                )
              }
            />
          );
        })}
      </div>
      {connectingPlugin && (
        <MemberPluginConnectionDialog
          plugin={connectingPlugin}
          surface="craft"
          open
          onClose={() => setDialog(null)}
          onConnected={() => {
            setDialog(null);
            void refresh();
          }}
        />
      )}
      {editingApp && (
        <TaskAppActionsModal
          key={editingApp.gated_app_id}
          app={editingApp}
          policies={initialActionPolicies(
            editingApp,
            activeDraft?.action_policies ?? {}
          )}
          onClose={() => setDialog(null)}
          onSave={(policies) => {
            onChange(
              value.map((app) =>
                app.gated_app_id === editingApp.gated_app_id
                  ? { ...app, action_policies: policies }
                  : app
              )
            );
            setDialog(null);
          }}
        />
      )}
    </>
  );
}
