"use client";

import { useTranslations } from "next-intl";
import { Badge, Text } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { SvgPlug } from "@opal/icons";
import { useNavigation, useSearchParams } from "@opal/navigation";
import {
  customizeTabHref,
  integrationHref,
  type IntegrationPageTab,
} from "@/lib/customize/paths";
import { useMemberIntegrations } from "@/lib/integrations/hooks";
import CustomizeDetailLayout, {
  BackLink,
  DetailOverview,
  type DetailTab,
} from "@/sections/customize/CustomizeDetailLayout";
import { useIntegrationLabels } from "@/sections/integrations/integrationLabels";
import {
  IntegrationMenu,
  IntegrationSwitch,
  useIntegrationStateCopy,
} from "@/sections/customize/IntegrationAccessControls";
import AlwaysAllowList from "@/sections/plugins/AlwaysAllowList";
import IntegrationConnectButton from "@/sections/plugins/IntegrationConnectButton";

function parseTab(value: string | null): IntegrationPageTab {
  return value === "actions" ? value : "overview";
}

interface CustomizeIntegrationPageProps {
  integrationId: number;
}

/** One integration for a member: Overview and Actions (the admin settings
 * and the user's "Don't ask me"). The header holds the connection state and
 * Connect or Disconnect. The admin sets Allow, Ask and Blocked on the admin
 * page. */
export default function CustomizeIntegrationPage({
  integrationId,
}: CustomizeIntegrationPageProps) {
  const t = useTranslations("customize.integrationPage");
  const stateCopy = useTranslations("integrations");
  const navigation = useNavigation();
  const searchParams = useSearchParams();
  const labels = useIntegrationLabels();
  const accessCopy = useIntegrationStateCopy();
  const { data, error, isLoading } = useMemberIntegrations();
  const integration = data?.find((item) => item.id === integrationId);
  const returnPath = integrationHref(integrationId);
  const state = integration?.status.state;
  const reason = integration ? accessCopy.reason(integration) : null;
  const required = integration?.access.installation_policy === "REQUIRED";

  const tabs: DetailTab<IntegrationPageTab>[] | null = integration
    ? [
        {
          value: "overview",
          label: t("tabs.overview"),
          content: (
            <DetailOverview
              facts={[
                {
                  label: t("overview.type"),
                  value: labels.shape(integration),
                },
                {
                  label: t("overview.signIn"),
                  value: labels.signIn(integration),
                },
                ...(integration.server_url
                  ? [
                      {
                        label: t("overview.url"),
                        value: integration.server_url,
                        mono: true,
                      },
                    ]
                  : []),
                {
                  label: t("overview.owner"),
                  value:
                    integration.access.owner_email ??
                    t("overview.organization"),
                },
              ]}
              footer={
                reason !== null ? (
                  <Text as="p" font="secondary-body" color="text-03">
                    {reason}
                  </Text>
                ) : (
                  <ContentAction
                    font="main-ui-action"
                    title={t("overview.switch.title")}
                    description={
                      required
                        ? t("overview.switch.required")
                        : t("overview.switch.description")
                    }
                    padding={0}
                    rightChildren={
                      <IntegrationSwitch integration={integration} />
                    }
                  />
                )
              }
            />
          ),
        },
        ...(integration.access.state === "no_access"
          ? []
          : [
              {
                value: "actions" as const,
                label: t("tabs.actions"),
                content: <AlwaysAllowList integrationId={integration.id} />,
              },
            ]),
      ]
    : null;

  return (
    <CustomizeDetailLayout
      back={
        <BackLink to={customizeTabHref("integrations")} label={t("back")} />
      }
      icon={SvgPlug}
      title={integration?.name ?? t("title")}
      description={integration?.description ?? undefined}
      loading={isLoading}
      error={error || (data && !integration) ? t("loadFailed") : false}
      tabs={tabs}
      tab={
        integration?.access.state === "no_access"
          ? "overview"
          : parseTab(searchParams.get("tab"))
      }
      onTabChange={(next) =>
        navigation.go(integrationHref(integrationId, next), {
          replace: true,
          scroll: false,
        })
      }
      actions={
        integration
          ? [
              <Badge
                key="status"
                size={6}
                color={
                  state === "connected"
                    ? "success"
                    : state === "needs_reconnect"
                      ? "warning"
                      : "default"
                }
                title={stateCopy("connectionState", {
                  state: state ?? "not_set_up",
                })}
                tooltip={
                  state === "needs_reconnect"
                    ? (integration.status.reason ?? undefined)
                    : undefined
                }
              />,
              ...(reason === null
                ? [
                    <IntegrationConnectButton
                      key="connect"
                      integration={integration}
                      returnPath={returnPath}
                      allowDisconnect
                    />,
                  ]
                : []),
              <IntegrationMenu key="menu" integration={integration} />,
            ]
          : undefined
      }
    />
  );
}
