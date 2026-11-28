"use client";

import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { Section, TagList } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { TaskIntegrationView } from "@/app/craft/v1/tasks/types";
import ActionPoliciesLoadError from "@/app/craft/v1/tasks/components/ActionPoliciesLoadError";

interface TaskActionPoliciesSummaryProps {
  taskId: string;
  /** Reads the integrations from this URL instead of the Craft one. */
  url?: string;
}

export default function TaskActionPoliciesSummary({
  taskId,
  url,
}: TaskActionPoliciesSummaryProps) {
  const t = useTranslations("craft.actionPolicies");
  const { data, error, mutate } = useSWR<TaskIntegrationView[], Error>(
    url ?? SWR_KEYS.taskActionPolicies(taskId),
    errorHandlingFetcher
  );
  const enabledIntegrations = data?.filter(
    (integration) => integration.enabled
  );
  return (
    <Section height="auto" alignItems="stretch" gap={2}>
      <Text font="secondary-action" color="text-03">
        {t("taskAccessTitle")}
      </Text>
      {error && !data ? (
        <ActionPoliciesLoadError retry={() => void mutate()} />
      ) : !enabledIntegrations ? (
        <Text font="secondary-body" color="text-03">
          {t("loading")}
        </Text>
      ) : enabledIntegrations.length === 0 ? (
        <Text font="secondary-body" color="text-03">
          {t("noEnabledApps")}
        </Text>
      ) : (
        <TagList
          items={enabledIntegrations.map((integration) => ({
            id: String(integration.id),
            label: integration.name,
          }))}
        />
      )}
    </Section>
  );
}
