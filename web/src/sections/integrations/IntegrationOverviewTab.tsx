"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, InputSwitch, Text } from "@opal/components";
import {
  ConfirmationModalLayout,
  Content,
  InputHorizontal,
  Section,
  toast,
} from "@opal/layouts";
import { SvgTrash } from "@opal/icons";
import { useNavigation } from "@opal/navigation";
import { useSWRConfig } from "swr";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { SWR_KEYS } from "@/lib/swr-keys";
import { deleteIntegration, updateIntegration } from "@/lib/integrations/svc";
import type { AdminIntegrationDetail } from "@/lib/integrations/types";
import { useIntegrationLabels } from "@/sections/integrations/integrationLabels";

interface IntegrationOverviewTabProps {
  integration: AdminIntegrationDetail;
  onChanged: () => void;
}

export default function IntegrationOverviewTab({
  integration,
  onChanged,
}: IntegrationOverviewTabProps) {
  const t = useTranslations("admin.integrations.detail.overview");
  const access = useTranslations("admin.integrations.access");
  const labels = useIntegrationLabels();
  const navigation = useNavigation();
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const readOnly = !integration.can_manage;

  async function setEnabled(enabled: boolean) {
    setBusy(true);
    try {
      await updateIntegration(integration.id, { enabled });
      await mutate(SWR_KEYS.adminIntegrations);
      onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await deleteIntegration(integration.id);
      await mutate(SWR_KEYS.adminIntegrations);
      toast.success(t("deleted", { name: integration.name }));
      navigation.go(ADMIN_ROUTES.INTEGRATIONS.path, { replace: true });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("deleteFailed"));
      setBusy(false);
    }
  }

  return (
    <Section gap={4} alignItems="stretch" height="auto">
      {readOnly && (
        <Text font="secondary-body" color="text-03">
          {t("readOnly")}
        </Text>
      )}
      <Card padding={4}>
        <Section gap={4} alignItems="stretch" height="auto">
          <Content
            title={integration.name}
            description={integration.description ?? t("noDescription")}
          />
          <Content
            font="secondary-body"
            title={t("type")}
            description={labels.shape(integration)}
          />
          <Content
            font="secondary-body"
            title={t("signIn")}
            description={labels.signIn(integration)}
          />
          {integration.created_by_email && (
            <Content
              font="secondary-body"
              title={t("createdBy")}
              description={integration.created_by_email}
            />
          )}
          {integration.needs_setup && (
            <Content
              font="secondary-body"
              title={t("needsSetup")}
              description={integration.setup_reason ?? t("needsSetupDefault")}
            />
          )}
        </Section>
      </Card>
      <Card padding={4}>
        <Section gap={2} alignItems="stretch" height="auto">
          <Content
            font="main-ui-action"
            title={t("plugins.title")}
            description={t("plugins.description")}
          />
          {integration.plugins.length === 0 ? (
            <Text font="secondary-body" color="text-03">
              {access("none")}
            </Text>
          ) : (
            integration.plugins.map((plugin) => (
              <Section
                key={plugin.plugin_id}
                flexDirection="row"
                justifyContent="between"
                height="auto"
              >
                <Text font="main-ui-body" color="text-04">
                  {plugin.plugin_name}
                </Text>
                <Text font="secondary-body" color="text-03">
                  {plugin.scope === "organization"
                    ? t("plugins.organization", {
                        policy: plugin.installation_policy ?? "none",
                      })
                    : t("plugins.personal", {
                        owner: plugin.owner_email ?? "",
                      })}
                </Text>
              </Section>
            ))
          )}
          <Section flexDirection="row" justifyContent="start" height="auto">
            <Button
              prominence="tertiary"
              size="sm"
              onClick={() => navigation.go(ADMIN_ROUTES.PLUGINS.path)}
            >
              {t("plugins.manage")}
            </Button>
          </Section>
        </Section>
      </Card>
      <Card padding={4}>
        <Section gap={4} alignItems="stretch" height="auto">
          <InputHorizontal
            withLabel
            title={t("enabled.title")}
            description={t("enabled.description")}
            disabled={busy || readOnly}
          >
            <InputSwitch
              aria-label={t("enabled.title")}
              checked={integration.enabled}
              disabled={busy || readOnly}
              onCheckedChange={(checked) => void setEnabled(checked)}
            />
          </InputHorizontal>
          <InputHorizontal
            title={t("delete.title")}
            description={t("delete.description")}
          >
            <Button
              variant="danger"
              prominence="secondary"
              icon={SvgTrash}
              disabled={busy || readOnly}
              onClick={() => setConfirmDelete(true)}
            >
              {t("delete.label")}
            </Button>
          </InputHorizontal>
        </Section>
      </Card>
      {confirmDelete && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          color="error"
          title={t("delete.confirmTitle", { name: integration.name })}
          description={t("delete.confirmDescription")}
          onClose={busy ? undefined : () => setConfirmDelete(false)}
          submit={
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => void remove()}
            >
              {t("delete.confirm")}
            </Button>
          }
        />
      )}
    </Section>
  );
}
