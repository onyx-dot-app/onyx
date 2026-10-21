"use client";

import useSWR from "swr";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { Section, TagList } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { AppActionPoliciesView } from "@/lib/plugins/types";
import ActionPoliciesLoadError from "@/app/craft/v1/tasks/components/ActionPoliciesLoadError";

export default function TaskActionPoliciesSummary({
  taskId,
}: {
  taskId: string;
}) {
  const t = useTranslations("craft.actionPolicies");
  const { data, error, mutate } = useSWR<AppActionPoliciesView[], Error>(
    SWR_KEYS.taskActionPolicies(taskId),
    errorHandlingFetcher
  );
  const enabledApps = data?.filter((app) => app.enabled === true);
  return (
    <Section height="auto" alignItems="stretch" gap={2}>
      <Text font="secondary-action" color="text-03">
        {t("taskAccessTitle")}
      </Text>
      {error && !data ? (
        <ActionPoliciesLoadError retry={() => void mutate()} />
      ) : !enabledApps ? (
        <Text font="secondary-body" color="text-03">
          {t("loading")}
        </Text>
      ) : enabledApps.length === 0 ? (
        <Text font="secondary-body" color="text-03">
          {t("noEnabledApps")}
        </Text>
      ) : (
        <TagList
          size="md"
          items={enabledApps.map((app) => ({
            id: String(app.gated_app_id),
            label: app.name,
          }))}
        />
      )}
    </Section>
  );
}
