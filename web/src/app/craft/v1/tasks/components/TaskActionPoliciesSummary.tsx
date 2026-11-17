"use client";

import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { Section, TagList } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { TaskPluginView } from "@/app/craft/v1/tasks/types";
import ActionPoliciesLoadError from "@/app/craft/v1/tasks/components/ActionPoliciesLoadError";

export default function TaskActionPoliciesSummary({
  taskId,
}: {
  taskId: string;
}) {
  const t = useTranslations("craft.actionPolicies");
  const { data, error, mutate } = useSWR<TaskPluginView[], Error>(
    SWR_KEYS.taskActionPolicies(taskId),
    errorHandlingFetcher
  );
  const enabledPlugins = data?.filter((plugin) => plugin.enabled);
  return (
    <Section height="auto" alignItems="stretch" gap={2}>
      <Text font="secondary-action" color="text-03">
        {t("taskAccessTitle")}
      </Text>
      {error && !data ? (
        <ActionPoliciesLoadError retry={() => void mutate()} />
      ) : !enabledPlugins ? (
        <Text font="secondary-body" color="text-03">
          {t("loading")}
        </Text>
      ) : enabledPlugins.length === 0 ? (
        <Text font="secondary-body" color="text-03">
          {t("noEnabledApps")}
        </Text>
      ) : (
        <TagList
          items={enabledPlugins.map((plugin) => ({
            id: plugin.plugin_id,
            label: plugin.plugin_name,
          }))}
        />
      )}
    </Section>
  );
}
