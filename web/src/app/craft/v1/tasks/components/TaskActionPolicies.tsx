"use client";

import { useId, useState } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Text, useCreateModal } from "@opal/components";
import { Section } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  TaskActionSettings,
  TaskPluginLink,
  TaskPluginView,
} from "@/app/craft/v1/tasks/types";
import styles from "@/sections/plugins/PluginsPage.module.css";
import TaskPluginCard from "@/app/craft/v1/tasks/components/TaskPluginCard";
import TaskAppActionsModal from "@/app/craft/v1/tasks/components/TaskAppActionsModal";
import ActionPoliciesLoadError from "@/app/craft/v1/tasks/components/ActionPoliciesLoadError";

const INHERIT_ALL: TaskActionSettings = { default: "inherit", actions: {} };

interface TaskActionPoliciesProps {
  taskId: string | null;
  value: TaskPluginLink[] | null;
  onChange: (value: TaskPluginLink[]) => void;
}

export default function TaskActionPolicies({
  taskId,
  value,
  onChange,
}: TaskActionPoliciesProps) {
  const t = useTranslations("craft.actionPolicies");
  const openingId = useId();
  const [catalog, setCatalog] = useState<TaskPluginView[] | null>(null);
  const { error, mutate } = useSWR<TaskPluginView[], Error>(
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
          data
            .filter((plugin) => plugin.enabled)
            .map((plugin) => ({
              plugin_id: plugin.plugin_id,
              action_settings: plugin.action_settings ?? INHERIT_ALL,
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
        {t(taskId ? "taskDescription" : "newTaskPluginsDescription")}
      </Text>
      <PluginGroups plugins={catalog} value={value ?? []} onChange={onChange} />
    </Section>
  );
}

interface PluginGroupsProps {
  plugins: TaskPluginView[] | null;
  value: TaskPluginLink[];
  onChange: (value: TaskPluginLink[]) => void;
}
function PluginGroups({ plugins, value, onChange }: PluginGroupsProps) {
  const t = useTranslations("craft.actionPolicies");
  const [editingId, setEditingId] = useState<string | null>(null);
  // The settings of a plugin the user turned off, so turning it on again
  // restores them.
  const [turnedOff, setTurnedOff] = useState<
    Record<string, TaskActionSettings>
  >({});
  const actionsModal = useCreateModal();
  if (!plugins) return <Text font="secondary-body">{t("loading")}</Text>;
  if (plugins.length === 0)
    return <Text font="secondary-body">{t("emptyPlugins")}</Text>;
  const linkFor = (pluginId: string) =>
    value.find((link) => link.plugin_id === pluginId);
  const editing = plugins.find((plugin) => plugin.plugin_id === editingId);
  function save(pluginId: string, settings: TaskActionSettings) {
    onChange([
      ...value.filter((link) => link.plugin_id !== pluginId),
      { plugin_id: pluginId, action_settings: settings },
    ]);
  }
  return (
    <>
      <div className={styles.grid}>
        {plugins.map((plugin) => {
          const link = linkFor(plugin.plugin_id);
          return (
            <TaskPluginCard
              key={plugin.plugin_id}
              plugin={plugin}
              enabled={link !== undefined}
              settings={link?.action_settings ?? INHERIT_ALL}
              onEdit={() => {
                setEditingId(plugin.plugin_id);
                actionsModal.toggle(true);
              }}
              onToggle={(enabled) => {
                if (enabled) {
                  save(
                    plugin.plugin_id,
                    link?.action_settings ??
                      turnedOff[plugin.plugin_id] ??
                      INHERIT_ALL
                  );
                  return;
                }
                if (link)
                  setTurnedOff((prev) => ({
                    ...prev,
                    [plugin.plugin_id]: link.action_settings,
                  }));
                onChange(
                  value.filter((item) => item.plugin_id !== plugin.plugin_id)
                );
              }}
            />
          );
        })}
      </div>
      <actionsModal.Provider>
        {editing && (
          <TaskAppActionsModal
            key={editing.plugin_id}
            plugin={editing}
            settings={
              linkFor(editing.plugin_id)?.action_settings ??
              turnedOff[editing.plugin_id] ??
              INHERIT_ALL
            }
            onClose={() => actionsModal.toggle(false)}
            onSave={(settings) => {
              // Setting actions turns the plugin on for the task.
              save(editing.plugin_id, settings);
              actionsModal.toggle(false);
            }}
          />
        )}
      </actionsModal.Provider>
    </>
  );
}
