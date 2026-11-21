"use client";

import { useId, useRef, useState } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Text, useCreateModal } from "@opal/components";
import { Section } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  TaskActionSettings,
  TaskIntegrationLink,
  TaskIntegrationView,
} from "@/app/craft/v1/tasks/types";
import styles from "@/sections/plugins/PluginsPage.module.css";
import TaskIntegrationCard from "@/app/craft/v1/tasks/components/TaskIntegrationCard";
import TaskAppActionsModal from "@/app/craft/v1/tasks/components/TaskAppActionsModal";
import ActionPoliciesLoadError from "@/app/craft/v1/tasks/components/ActionPoliciesLoadError";

const INHERIT_ALL: TaskActionSettings = { default: "inherit", actions: {} };

interface TaskActionPoliciesProps {
  taskId: string | null;
  value: TaskIntegrationLink[] | null;
  onChange: (value: TaskIntegrationLink[]) => void;
  /** Reads the integrations from this URL instead of the Craft one. */
  url?: string;
}

export default function TaskActionPolicies({
  taskId,
  value,
  onChange,
  url,
}: TaskActionPoliciesProps) {
  const t = useTranslations("craft.actionPolicies");
  const openingId = useId();
  const [catalog, setCatalog] = useState<TaskIntegrationView[] | null>(null);
  const { error, mutate } = useSWR<TaskIntegrationView[], Error>(
    [
      url ??
        (taskId
          ? SWR_KEYS.taskActionPolicies(taskId)
          : SWR_KEYS.personalActionPolicies),
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
          data
            .filter((integration) => integration.enabled)
            .map((integration) => ({
              integration_id: integration.id,
              action_settings: integration.action_settings ?? INHERIT_ALL,
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
        {t(taskId ? "taskDescription" : "newTaskIntegrationsDescription")}
      </Text>
      <IntegrationGrid
        integrations={catalog}
        value={value ?? []}
        onChange={onChange}
      />
    </Section>
  );
}

interface IntegrationGridProps {
  integrations: TaskIntegrationView[] | null;
  value: TaskIntegrationLink[];
  onChange: (value: TaskIntegrationLink[]) => void;
}
function IntegrationGrid({
  integrations,
  value,
  onChange,
}: IntegrationGridProps) {
  const t = useTranslations("craft.actionPolicies");
  const [editingId, setEditingId] = useState<number | null>(null);
  // The settings of an integration the user turned off, so turning it on
  // again restores them.
  const turnedOff = useRef<Record<number, TaskActionSettings>>({});
  const actionsModal = useCreateModal();
  if (!integrations) return <Text font="secondary-body">{t("loading")}</Text>;
  if (integrations.length === 0)
    return <Text font="secondary-body">{t("emptyIntegrations")}</Text>;
  const linkFor = (integrationId: number) =>
    value.find((link) => link.integration_id === integrationId);
  const editing = integrations.find(
    (integration) => integration.id === editingId
  );
  function save(integrationId: number, settings: TaskActionSettings) {
    onChange([
      ...value.filter((link) => link.integration_id !== integrationId),
      { integration_id: integrationId, action_settings: settings },
    ]);
  }
  return (
    <>
      <div className={styles.grid}>
        {integrations.map((integration) => {
          const link = linkFor(integration.id);
          return (
            <TaskIntegrationCard
              key={integration.id}
              integration={integration}
              enabled={link !== undefined}
              settings={link?.action_settings ?? INHERIT_ALL}
              onEdit={() => {
                setEditingId(integration.id);
                actionsModal.toggle(true);
              }}
              onToggle={(enabled) => {
                if (enabled) {
                  save(
                    integration.id,
                    link?.action_settings ??
                      turnedOff.current[integration.id] ??
                      INHERIT_ALL
                  );
                  return;
                }
                if (link)
                  turnedOff.current[integration.id] = link.action_settings;
                onChange(
                  value.filter((item) => item.integration_id !== integration.id)
                );
              }}
            />
          );
        })}
      </div>
      <actionsModal.Provider>
        {editing && (
          <TaskAppActionsModal
            key={editing.id}
            integration={editing}
            settings={
              linkFor(editing.id)?.action_settings ??
              turnedOff.current[editing.id] ??
              INHERIT_ALL
            }
            onClose={() => actionsModal.toggle(false)}
            onSave={(settings) => {
              // Setting actions turns the integration on for the task.
              save(editing.id, settings);
              actionsModal.toggle(false);
            }}
          />
        )}
      </actionsModal.Provider>
    </>
  );
}
