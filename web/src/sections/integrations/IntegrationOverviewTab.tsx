"use client";

import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import type { AdminIntegrationDetail } from "@/lib/integrations/types";
import { DetailOverview } from "@/sections/customize/CustomizeDetailLayout";
import { useIntegrationLabels } from "@/sections/integrations/integrationLabels";

interface IntegrationOverviewTabProps {
  integration: AdminIntegrationDetail;
}

/** The description beside the facts of the integration and the plugins that
 * hold it. The page header edits, switches and deletes it. */
export default function IntegrationOverviewTab({
  integration,
}: IntegrationOverviewTabProps) {
  const t = useTranslations("admin.integrations.detail.overview");
  const access = useTranslations("admin.integrations.access");
  const libraryCopy = useTranslations("admin.plugins.library");
  const labels = useIntegrationLabels();

  return (
    <Section gap={4} alignItems="stretch" height="auto">
      {!integration.can_manage && (
        <Text as="p" font="secondary-body" color="text-03">
          {t("readOnly")}
        </Text>
      )}
      <DetailOverview
        descriptionLabel={t("description")}
        description={integration.description || t("noDescription")}
        facts={[
          { label: t("type"), value: labels.shape(integration) },
          { label: t("signIn"), value: labels.signIn(integration) },
          ...(integration.created_by_email
            ? [{ label: t("createdBy"), value: integration.created_by_email }]
            : []),
          ...(integration.needs_setup
            ? [
                {
                  label: t("needsSetup"),
                  value: integration.setup_reason ?? t("needsSetupDefault"),
                },
              ]
            : []),
        ]}
        footer={
          <Section gap={1} alignItems="stretch" height="auto">
            <Text as="p" font="secondary-body" color="text-03">
              {t("plugins.title")}
            </Text>
            {integration.plugins.length === 0 ? (
              <Text as="p" font="main-ui-body" color="text-04">
                {access("none")}
              </Text>
            ) : (
              integration.plugins.map((plugin) => (
                <Content
                  key={plugin.plugin_id}
                  title={plugin.plugin_name}
                  description={
                    plugin.scope === "organization"
                      ? t("plugins.organization", {
                          policy: plugin.installation_policy ?? "none",
                        })
                      : (plugin.owner_email ?? libraryCopy("personal"))
                  }
                />
              ))
            )}
          </Section>
        }
      />
    </Section>
  );
}
