"use client";

import { useTranslations } from "next-intl";
import { Badge, Button, Tabs } from "@opal/components";
import { SettingsLayouts } from "@opal/layouts";
import { SvgArrowLeft } from "@opal/icons";
import { useNavigation, useSearchParams } from "@opal/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { isNotFoundError } from "@/lib/fetcher";
import { useAdminIntegration } from "@/lib/integrations/hooks";
import {
  integrationDetailHref,
  parseIntegrationTab,
  type IntegrationDetailTab,
} from "@/lib/integrations/utils";
import { useIntegrationLabels } from "@/sections/integrations/integrationLabels";
import IntegrationOverviewTab from "@/sections/integrations/IntegrationOverviewTab";
import IntegrationConfigurationTab from "@/sections/integrations/IntegrationConfigurationTab";
import IntegrationActionsTab from "@/sections/integrations/IntegrationActionsTab";

interface IntegrationDetailPageProps {
  integrationId: number;
}

export default function IntegrationDetailPage({
  integrationId,
}: IntegrationDetailPageProps) {
  const t = useTranslations("admin.integrations.detail");
  const navigation = useNavigation();
  const searchParams = useSearchParams();
  const labels = useIntegrationLabels();
  const tab = parseIntegrationTab(searchParams.get("tab"));
  const { data, error, isLoading, mutate } = useAdminIntegration(integrationId);

  function selectTab(next: IntegrationDetailTab) {
    navigation.go(integrationDetailHref(integrationId, next), {
      replace: true,
      scroll: false,
    });
  }

  const status = data ? labels.status(data) : null;

  return (
    <SettingsLayouts.Root
      width="lg"
      loading={isLoading}
      error={
        error
          ? isNotFoundError(error)
            ? t("notFound")
            : t("loadFailed")
          : false
      }
    >
      <SettingsLayouts.Header
        title={data?.name ?? t("title")}
        description={data ? labels.shape(data) : undefined}
        actions={[
          <Button
            key="back"
            prominence="secondary"
            icon={SvgArrowLeft}
            onClick={() => navigation.go(ADMIN_ROUTES.INTEGRATIONS.path)}
          >
            {t("back")}
          </Button>,
          ...(status ? [<Badge key="status" size={6} {...status} />] : []),
        ]}
      />
      <SettingsLayouts.Body>
        {data && (
          <Tabs
            value={tab}
            onValueChange={(value) => selectTab(parseIntegrationTab(value))}
            variant="contained"
            gap={6}
          >
            <Tabs.List>
              <Tabs.Trigger value="overview">{t("tabs.overview")}</Tabs.Trigger>
              <Tabs.Trigger value="configuration">
                {t("tabs.configuration")}
              </Tabs.Trigger>
              <Tabs.Trigger value="actions">{t("tabs.actions")}</Tabs.Trigger>
            </Tabs.List>
            <Tabs.Content value="overview" keepMounted>
              <IntegrationOverviewTab
                integration={data}
                onChanged={() => void mutate()}
              />
            </Tabs.Content>
            <Tabs.Content value="configuration" keepMounted>
              <IntegrationConfigurationTab
                key={`${data.id}:${data.auth_mode}:${data.auth_method ?? ""}`}
                integration={data}
                onChanged={() => void mutate()}
              />
            </Tabs.Content>
            <Tabs.Content value="actions" keepMounted>
              <IntegrationActionsTab
                integration={data}
                onOpenConfiguration={() => selectTab("configuration")}
              />
            </Tabs.Content>
          </Tabs>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
