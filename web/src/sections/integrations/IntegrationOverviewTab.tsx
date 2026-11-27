"use client";

import { useTranslations } from "next-intl";
import { MessageCard, Text } from "@opal/components";
import { ContentAction, Section } from "@opal/layouts";
import type { AdminIntegrationDetail } from "@/lib/integrations/types";
import { DetailOverview } from "@/sections/customize/CustomizeDetailLayout";
import { useIntegrationLabels } from "@/sections/integrations/integrationLabels";
import IntegrationGroupAccess from "@/sections/integrations/IntegrationGroupAccess";
import IntegrationInstallSetting from "@/sections/integrations/IntegrationInstallSetting";

interface IntegrationOverviewTabProps {
  integration: AdminIntegrationDetail;
}

/** The description beside the facts of the integration, its company
 * install setting and its group settings. The page header edits, switches
 * and deletes it. */
export default function IntegrationOverviewTab({
  integration,
}: IntegrationOverviewTabProps) {
  const t = useTranslations("admin.integrations.detail.overview");
  const installation = useTranslations("admin.integrations.installation");
  const labels = useIntegrationLabels();

  return (
    <Section gap={4} alignItems="stretch" height="auto">
      {integration.config.shape === "custom" && (
        <MessageCard
          variant="warning"
          title={t("urlPatternApp.title")}
          description={t("urlPatternApp.description")}
          bottomChildren={
            <div className="px-2">
              {integration.config.upstream_url_patterns.map((pattern) => (
                <Text key={pattern} as="p" font="secondary-mono">
                  {pattern}
                </Text>
              ))}
            </div>
          }
        />
      )}
      {!integration.can_manage && (
        <Text as="p" font="secondary-body" color="text-03">
          {t("readOnly")}
        </Text>
      )}
      <DetailOverview
        description={{
          label: t("description"),
          text: integration.description || t("noDescription"),
        }}
        facts={[
          { label: t("signIn"), value: labels.signIn(integration) },
          ...(integration.created_by_email &&
          integration.created_by_email !== integration.access.owner_email
            ? [{ label: t("createdBy"), value: integration.created_by_email }]
            : []),
          ...(integration.access.owner_email
            ? [{ label: t("owner"), value: integration.access.owner_email }]
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
          <ContentAction
            font="main-ui-action"
            title={installation("title")}
            description={installation("description")}
            padding={0}
            fillRight
            rightChildren={
              <IntegrationInstallSetting integration={integration} />
            }
          />
        }
      />
      <IntegrationGroupAccess integration={integration} />
    </Section>
  );
}
