"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@opal/components";
import { SvgPlug } from "@opal/icons";
import { useNavigation, useSearchParams } from "@opal/navigation";
import { isNotFoundError } from "@/lib/fetcher";
import { useAdminIntegration } from "@/lib/integrations/hooks";
import {
  integrationDetailHref,
  parseIntegrationTab,
  type IntegrationDetailTab,
} from "@/lib/integrations/utils";
import CustomizeDetailLayout, {
  BackLink,
  type DetailTab,
} from "@/sections/customize/CustomizeDetailLayout";
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
  const { data, error, isLoading, mutate } = useAdminIntegration(integrationId);

  function selectTab(next: IntegrationDetailTab) {
    navigation.go(integrationDetailHref(integrationId, next), {
      replace: true,
      scroll: false,
    });
  }

  const status = data ? labels.status(data) : null;

  const tabs: DetailTab<IntegrationDetailTab>[] | null = data
    ? [
        {
          value: "overview",
          label: t("tabs.overview"),
          keepMounted: true,
          content: (
            <IntegrationOverviewTab
              integration={data}
              onChanged={() => void mutate()}
            />
          ),
        },
        {
          value: "configuration",
          label: t("tabs.configuration"),
          keepMounted: true,
          content: (
            <IntegrationConfigurationTab
              key={`${data.id}:${data.auth_mode}:${data.auth_method ?? ""}`}
              integration={data}
              onChanged={() => void mutate()}
            />
          ),
        },
        {
          value: "actions",
          label: t("tabs.actions"),
          keepMounted: true,
          content: (
            <IntegrationActionsTab
              integration={data}
              onOpenConfiguration={() => selectTab("configuration")}
            />
          ),
        },
      ]
    : null;

  return (
    <CustomizeDetailLayout
      back={<BackLink to="/admin/integrations" label={t("back")} />}
      icon={SvgPlug}
      title={data?.name ?? t("title")}
      description={data ? labels.shape(data) : undefined}
      loading={isLoading}
      error={
        error
          ? isNotFoundError(error)
            ? t("notFound")
            : t("loadFailed")
          : false
      }
      tabs={tabs}
      tab={parseIntegrationTab(searchParams.get("tab"))}
      onTabChange={selectTab}
      actions={
        status ? [<Badge key="status" size={6} {...status} />] : undefined
      }
    />
  );
}
