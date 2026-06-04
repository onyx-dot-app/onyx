"use client";

import { Tag, Text } from "@opal/components";
import useUserExternalApps from "@/hooks/useUserExternalApps";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";

interface PreApprovedAppsSummaryProps {
  appIds: number[];
}

export default function PreApprovedAppsSummary({
  appIds,
}: PreApprovedAppsSummaryProps) {
  const { data, isLoading } = useUserExternalApps();
  if (appIds.length === 0) return null;
  // Wait for names so the tags never flash raw "App #id" fallbacks.
  if (isLoading) return null;

  const byId = new Map((data ?? []).map((app) => [app.id, app]));
  return (
    <div className="flex flex-col gap-2">
      <Text font="main-ui-action" color="text-03">
        Pre-approved apps
      </Text>
      <div className="flex flex-wrap gap-2">
        {appIds.map((id) => {
          const app = byId.get(id);
          return (
            <Tag
              key={id}
              icon={app ? getAppTypeLogo(app.app_type) : undefined}
              title={app?.name ?? `App #${id}`}
            />
          );
        })}
      </div>
    </div>
  );
}
