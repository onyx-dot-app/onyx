"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Badge,
  InputTypeIn,
  Table,
  Text,
  type TableColumn,
} from "@opal/components";
import {
  Content,
  IllustrationContent,
  Section,
  SettingsLayouts,
  Toolbar,
} from "@opal/layouts";
import { SvgLink } from "@opal/icons";
import { SvgUnPlugged } from "@opal/illustrations";
import { useNavigation } from "@opal/navigation";
import { useScreenSize } from "@opal/hooks";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { useAdminIntegrations } from "@/lib/integrations/hooks";
import type { AdminIntegration } from "@/lib/integrations/types";
import {
  integrationDetailHref,
  sortIntegrations,
} from "@/lib/integrations/utils";
import {
  INTEGRATION_SHAPE_ICONS,
  useIntegrationLabels,
} from "@/sections/integrations/integrationLabels";
import AddIntegrationMenu from "@/sections/integrations/AddIntegrationMenu";
import IntegrationCatalogSection from "@/sections/integrations/IntegrationCatalogSection";
import IntegrationInstallSetting from "@/sections/integrations/IntegrationInstallSetting";
import IntegrationKindFilter, {
  type IntegrationKindFilterValue,
} from "@/sections/integrations/IntegrationKindFilter";
import { useIntegrationStateCopy } from "@/sections/customize/IntegrationAccessControls";

interface IntegrationsPageProps {
  /** The `/new` route: the add modal opens at once. */
  openAdd?: boolean;
}

export default function IntegrationsPage({
  openAdd = false,
}: IntegrationsPageProps) {
  const t = useTranslations("admin.integrations");
  const locale = useLocale();
  const navigation = useNavigation();
  const labels = useIntegrationLabels();
  const accessCopy = useIntegrationStateCopy();
  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_ACTIONS
  );
  const canCreate = isGlobalHolder || isScopedManager;
  const { data, error, isLoading } = useAdminIntegrations();
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<IntegrationKindFilterValue>("all");
  const { isMobile } = useScreenSize();

  const search = query.trim().toLocaleLowerCase();
  const integrations = sortIntegrations(data ?? [], locale).filter(
    (integration) =>
      (kind === "all" || integration.kind === kind) &&
      `${integration.name} ${integration.description ?? ""}`
        .toLocaleLowerCase()
        .includes(search)
  );

  const detailColumns: TableColumn<AdminIntegration>[] = [
    {
      kind: "display",
      id: "type",
      title: t("columns.type"),
      width: { weight: 14 },
      cell: (row) => (
        <Text as="p" font="main-ui-body" color="text-03" maxLines={1}>
          {labels.shape(row)}
        </Text>
      ),
    },
    {
      kind: "display",
      id: "signIn",
      title: t("columns.signIn"),
      width: { weight: 18 },
      cell: (row) => (
        <Text as="p" font="main-ui-body" color="text-03" maxLines={1}>
          {labels.signIn(row)}
        </Text>
      ),
    },
    {
      kind: "display",
      id: "installation",
      title: t("columns.installation"),
      width: { weight: 22 },
      cell: (row) => (
        <Section
          height="auto"
          alignItems="stretch"
          onClick={(event) => event.stopPropagation()}
        >
          <IntegrationInstallSetting integration={row} />
        </Section>
      ),
    },
  ];

  const columns: TableColumn<AdminIntegration>[] = [
    {
      kind: "data",
      field: "name",
      title: t("columns.name"),
      weight: 28,
      truncate: true,
      cell: (name, row) => (
        <Content
          icon={INTEGRATION_SHAPE_ICONS[row.shape]}
          title={name}
          description={
            accessCopy.reason(row) ??
            (row.description ||
              (row.access.owner_email
                ? t("ownedBy", { owner: row.access.owner_email })
                : undefined))
          }
          titleMaxLines={1}
          descriptionMaxLines={1}
        />
      ),
    },
    ...(isMobile ? [] : detailColumns),
    {
      kind: "display",
      id: "status",
      title: t("columns.status"),
      width: { weight: 14 },
      cell: (row) => <Badge size={5} {...labels.status(row)} />,
    },
  ];

  return (
    <SettingsLayouts.Root
      width="lg"
      loading={isLoading}
      error={error ? t("loadFailed") : false}
    >
      <SettingsLayouts.Header
        icon={SvgLink}
        title={t("title")}
        description={t("description")}
        stackActionsOnMobile
        actions={
          canCreate
            ? [
                <AddIntegrationMenu
                  key="add"
                  from="admin"
                  openOnLoad={openAdd}
                />,
              ]
            : []
        }
      />
      <SettingsLayouts.Body>
        <Toolbar
          search={
            <InputTypeIn
              icon="search"
              aria-label={t("search")}
              placeholder={t("search")}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          }
          actions={<IntegrationKindFilter value={kind} onChange={setKind} />}
        />
        <Table
          label={t("title")}
          items={integrations}
          columns={columns}
          getRowId={(row) => String(row.id)}
          getRowLabel={(row) => t("open", { name: row.name })}
          onRowClick={(row) => navigation.go(integrationDetailHref(row.id))}
          pageSize={false}
          emptyState={
            <IllustrationContent
              illustration={SvgUnPlugged}
              title={
                data && data.length > 0
                  ? t("empty.noResults")
                  : t("empty.title")
              }
              description={
                data && data.length > 0
                  ? t("empty.noResultsDescription")
                  : t("empty.description")
              }
            />
          }
        />
        {canCreate && <IntegrationCatalogSection from="admin" />}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
