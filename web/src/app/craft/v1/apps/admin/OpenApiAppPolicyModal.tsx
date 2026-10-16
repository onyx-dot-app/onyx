"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import ActionPolicyEditorModal from "@/app/craft/v1/apps/admin/ActionPolicyEditorModal";
import { updateExternalApp } from "@/app/craft/services/externalAppsService";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";

interface OpenApiAppPolicyModalProps {
  app: ExternalAppAdminResponse;
  onClose: () => void;
  onChanged: () => Promise<void>;
}

export default function OpenApiAppPolicyModal({
  app: currentApp,
  onClose,
  onChanged,
}: OpenApiAppPolicyModalProps) {
  const t = useTranslations("craft.apps.openApiPolicy");
  // Keep the draft baseline stable during background refresh.
  const [app] = useState(currentApp);
  const initialPolicies = Object.fromEntries(
    app.actions.map((action) => [action.action_id, action.state])
  );

  return (
    <ActionPolicyEditorModal
      onClose={onClose}
      title={t("title", { name: app.name })}
      description={t("description")}
      fields={[]}
      initialFieldValues={{}}
      policyItems={app.actions.map((action) => ({
        id: action.action_id,
        name: action.normalised_name,
        description: [
          action.method && action.path ? `${action.method} ${action.path}` : "",
          action.description,
        ]
          .filter(Boolean)
          .join("\n"),
        defaultPolicy: "ASK",
      }))}
      initialPolicies={initialPolicies}
      emptyPoliciesMessage={t("emptyPolicies")}
      saveLabel={t("saveButton")}
      onSave={async (_values, policies) => {
        await updateExternalApp(app.id, {
          action_policies: Object.fromEntries(
            Object.entries(policies).filter(
              ([id, value]) => initialPolicies[id] !== value
            )
          ),
        });
        await onChanged();
      }}
    />
  );
}
