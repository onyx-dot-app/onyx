"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  Table,
  Text,
  type TableColumn,
} from "@opal/components";
import { IllustrationContent, Section } from "@opal/layouts";
import { SvgCheck, SvgPlug, SvgPlus, SvgSettings } from "@opal/icons";
import { SvgUnPlugged } from "@opal/illustrations";
import { useScreenSize } from "@opal/hooks";
import { useNavigation } from "@opal/navigation";
import { customizeTabHref, integrationHref } from "@/lib/customize/paths";
import { useMemberIntegrations } from "@/lib/integrations/hooks";
import type { MemberIntegration } from "@/lib/integrations/types";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import CustomizeLayout from "@/sections/customize/CustomizeLayout";
import { CustomizeEmpty } from "@/sections/customize/CustomizeList";
import AddIntegrationModal from "@/sections/integrations/AddIntegrationModal";
import { useIntegrationLabels } from "@/sections/integrations/integrationLabels";
import IntegrationConnectButton from "@/sections/plugins/IntegrationConnectButton";

const RETURN_PATH = customizeTabHref("integrations");

interface IntegrationStatusCellProps {
  integration: MemberIntegration;
}

function IntegrationStatusCell({ integration }: IntegrationStatusCellProps) {
  const t = useTranslations("customize.integrations");
  if (integration.status.state === "connected")
    return (
      <Section
        flexDirection="row"
        justifyContent="start"
        width="auto"
        height="auto"
        aria-label={t("status.connected")}
      >
        <SvgCheck size={16} className="stroke-text-03" />
      </Section>
    );
  return (
    <IntegrationConnectButton
      integration={integration}
      returnPath={RETURN_PATH}
    />
  );
}

export default function CustomizeIntegrationsPage() {
  const t = useTranslations("customize.integrations");
  const locale = useLocale();
  const navigation = useNavigation();
  const labels = useIntegrationLabels();
  const { isMobile } = useScreenSize();
  const { data, error, isLoading, mutate } = useMemberIntegrations();
  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_ACTIONS
  );
  const canAdd = isGlobalHolder || isScopedManager;
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);

  const integrations = [...(data ?? [])].sort((a, b) =>
    a.name.localeCompare(b.name, locale, { sensitivity: "base" })
  );
  const search = query.trim().toLocaleLowerCase(locale);
  const shown = integrations.filter((integration) =>
    `${integration.name} ${integration.description ?? ""}`
      .toLocaleLowerCase(locale)
      .includes(search)
  );

  function open(integration: MemberIntegration): void {
    navigation.go(integrationHref(integration.id));
  }

  const detailColumns: TableColumn<MemberIntegration>[] = [
    {
      kind: "display",
      id: "type",
      title: t("columns.type"),
      width: { weight: 16 },
      cell: (row) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {labels.shape(row)}
        </Text>
      ),
    },
    {
      kind: "display",
      id: "authorization",
      title: t("columns.authorization"),
      width: { weight: 22 },
      cell: (row) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {labels.signIn(row)}
        </Text>
      ),
    },
  ];
  const columns: TableColumn<MemberIntegration>[] = [
    { kind: "qualifier", content: "icon", icon: () => SvgPlug },
    {
      kind: "data",
      field: "name",
      title: t("columns.name"),
      weight: 34,
      truncate: true,
      cell: (name) => (
        <Text font="main-ui-action" color="text-04" maxLines={1}>
          {name}
        </Text>
      ),
    },
    ...(isMobile ? [] : detailColumns),
    {
      kind: "display",
      id: "status",
      title: t("columns.status"),
      width: { weight: 18 },
      cell: (row) => <IntegrationStatusCell integration={row} />,
    },
  ];

  const controls = canAdd && (
    <Dropdown align="end" width={60}>
      <Dropdown.Trigger asChild>
        <Button icon={SvgPlus}>{t("add.label")}</Button>
      </Dropdown.Trigger>
      <Dropdown.Data
        label={t("add.label")}
        items={[
          {
            kind: "action",
            id: "add",
            icon: SvgPlug,
            title: t("add.integration"),
            onSelect: () => setAdding(true),
          },
          {
            kind: "action",
            id: "manage",
            icon: SvgSettings,
            title: t("add.manage"),
            onSelect: () => navigation.go("/admin/integrations"),
          },
        ]}
      />
    </Dropdown>
  );

  return (
    <CustomizeLayout
      tab="integrations"
      query={query}
      onQueryChange={setQuery}
      controls={controls}
      loading={isLoading}
      error={error ? t("loadFailed") : false}
    >
      {integrations.length === 0 ? (
        <CustomizeEmpty
          illustration={SvgUnPlugged}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <Table
          label={t("title")}
          items={shown}
          columns={columns}
          getRowId={(row) => String(row.id)}
          pageSize={false}
          onRowClick={open}
          getRowLabel={(row) => t("open", { name: row.name })}
          emptyState={
            <IllustrationContent
              illustration={SvgUnPlugged}
              title={t("noMatches.title")}
              description={t("noMatches.description")}
            />
          }
        />
      )}
      {adding && (
        <AddIntegrationModal
          canChooseOrganization={false}
          onClose={() => setAdding(false)}
          onCreated={(created) => {
            setAdding(false);
            // The integration page reads the new integration from the list.
            void mutate().finally(() =>
              navigation.go(integrationHref(created.id, "configuration"))
            );
          }}
        />
      )}
    </CustomizeLayout>
  );
}
