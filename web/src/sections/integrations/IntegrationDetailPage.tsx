"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  Badge,
  Button,
  Dropdown,
  InputSwitch,
  Tooltip,
  type DropdownMenuItem,
} from "@opal/components";
import { ConfirmationModalLayout, Section, toast } from "@opal/layouts";
import { SvgEdit, SvgMoreHorizontal, SvgPlug, SvgTrash } from "@opal/icons";
import { useNavigation, useSearchParams } from "@opal/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { isNotFoundError } from "@/lib/fetcher";
import { deleteIntegration, updateIntegration } from "@/lib/integrations/svc";
import { SWR_KEYS } from "@/lib/swr-keys";
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
import EditIntegrationDetailsModal from "@/sections/integrations/EditIntegrationDetailsModal";
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
  const overviewCopy = useTranslations("admin.integrations.detail.overview");
  const { data, error, isLoading, mutate } = useAdminIntegration(integrationId);
  const { mutate: mutateKey } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  async function refresh() {
    await Promise.all([mutate(), mutateKey(SWR_KEYS.adminIntegrations)]);
  }

  async function setEnabled(enabled: boolean) {
    setBusy(true);
    try {
      await updateIntegration(integrationId, { enabled });
      await refresh();
    } catch (failure) {
      toast.error(
        failure instanceof Error ? failure.message : overviewCopy("saveFailed")
      );
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!data) return;
    setBusy(true);
    try {
      await deleteIntegration(integrationId);
      await mutateKey(SWR_KEYS.adminIntegrations);
      toast.success(overviewCopy("deleted", { name: data.name }));
      navigation.go(ADMIN_ROUTES.INTEGRATIONS.path, { replace: true });
    } catch (failure) {
      toast.error(
        failure instanceof Error
          ? failure.message
          : overviewCopy("deleteFailed")
      );
      setBusy(false);
    }
  }

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
          content: <IntegrationOverviewTab integration={data} />,
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
      actions={data && status ? actions(data, status) : undefined}
    >
      {editing && data && (
        <EditIntegrationDetailsModal
          integration={data}
          onClose={() => setEditing(false)}
          onSaved={refresh}
        />
      )}
      {confirmDelete && data && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          color="error"
          title={overviewCopy("delete.confirmTitle", { name: data.name })}
          description={overviewCopy("delete.confirmDescription")}
          onClose={busy ? undefined : () => setConfirmDelete(false)}
          submit={
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => void remove()}
            >
              {overviewCopy("delete.confirm")}
            </Button>
          }
        />
      )}
    </CustomizeDetailLayout>
  );

  function actions(
    integration: NonNullable<typeof data>,
    badge: NonNullable<typeof status>
  ) {
    const menu: DropdownMenuItem[] = [
      ...(integration.can_manage
        ? [
            {
              kind: "action" as const,
              id: "edit",
              icon: SvgEdit,
              title: overviewCopy("details.edit"),
              onSelect: () => setEditing(true),
            },
          ]
        : []),
      ...(integration.can_delete
        ? [
            {
              kind: "action" as const,
              id: "delete",
              icon: SvgTrash,
              title: overviewCopy("delete.label"),
              danger: true,
              onSelect: () => setConfirmDelete(true),
            },
          ]
        : []),
    ];
    return [
      <Badge key="status" size={6} {...badge} />,
      ...(menu.length > 0
        ? [
            <Dropdown key="menu" align="end">
              <Dropdown.Trigger asChild>
                <Button
                  prominence="tertiary"
                  icon={SvgMoreHorizontal}
                  aria-label={overviewCopy("menu")}
                  tooltip={overviewCopy("menu")}
                />
              </Dropdown.Trigger>
              <Dropdown.Data label={overviewCopy("menu")} items={menu} />
            </Dropdown>,
          ]
        : []),
      <Tooltip
        key="enabled"
        tooltip={overviewCopy("enabled.description")}
        side="bottom"
      >
        <Section width="auto" height="auto" padding={1}>
          <InputSwitch
            aria-label={overviewCopy("enabled.title")}
            checked={integration.enabled}
            disabled={busy || !integration.can_manage}
            onCheckedChange={(checked) => void setEnabled(checked)}
          />
        </Section>
      </Tooltip>,
    ];
  }
}
