"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Badge,
  Button,
  InputTypeIn,
  Table,
  Text,
  type TableColumn,
} from "@opal/components";
import { IllustrationContent, Section, SettingsLayouts } from "@opal/layouts";
import { SvgPlus } from "@opal/icons";
import { SvgUnPlugged } from "@opal/illustrations";
import { useNavigation } from "@opal/navigation";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { useAdminIntegrations } from "@/lib/integrations/hooks";
import type {
  AdminIntegration,
  IntegrationKind,
} from "@/lib/integrations/types";
import {
  integrationDetailHref,
  sortIntegrations,
} from "@/lib/integrations/utils";
import { useIntegrationLabels } from "@/sections/integrations/integrationLabels";
import AddIntegrationModal from "@/sections/integrations/AddIntegrationModal";

type KindFilter = "all" | IntegrationKind;
const KIND_FILTERS: readonly KindFilter[] = ["all", "mcp_server", "api"];

export default function IntegrationsPage() {
  const t = useTranslations("admin.integrations");
  const locale = useLocale();
  const navigation = useNavigation();
  const labels = useIntegrationLabels();
  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_ACTIONS
  );
  const canCreate = isGlobalHolder || isScopedManager;
  const { data, error, isLoading, mutate } = useAdminIntegrations();
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");
  const [adding, setAdding] = useState(false);

  const search = query.trim().toLocaleLowerCase();
  const integrations = sortIntegrations(data ?? [], locale).filter(
    (integration) =>
      (kind === "all" || integration.kind === kind) &&
      `${integration.name} ${integration.description ?? ""}`
        .toLocaleLowerCase()
        .includes(search)
  );

  const columns: TableColumn<AdminIntegration>[] = [
    {
      kind: "data",
      field: "name",
      title: t("columns.name"),
      weight: 28,
      truncate: true,
      cell: (name, row) => (
        <Section alignItems="stretch" gap={0} height="auto">
          <Text
            font="main-ui-action"
            color="text-04"
            maxLines={1}
            overflowTooltip
          >
            {name}
          </Text>
          {row.description && (
            <Text
              font="secondary-body"
              color="text-03"
              maxLines={1}
              overflowTooltip
            >
              {row.description}
            </Text>
          )}
        </Section>
      ),
    },
    {
      kind: "display",
      id: "type",
      title: t("columns.type"),
      width: { weight: 14 },
      cell: (row) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
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
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {labels.signIn(row)}
        </Text>
      ),
    },
    {
      kind: "display",
      id: "access",
      title: t("columns.access"),
      width: { weight: 22 },
      cell: (row) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {labels.access(row)}
        </Text>
      ),
    },
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
        title={t("title")}
        description={t("description")}
        stackActionsOnMobile
        actions={
          canCreate
            ? [
                <Button
                  key="add"
                  icon={SvgPlus}
                  onClick={() => setAdding(true)}
                >
                  {t("add.label")}
                </Button>,
              ]
            : []
        }
      >
        <Section
          flexDirection="row"
          justifyContent="between"
          gap={2}
          wrap
          height="auto"
        >
          <Section width="auto" height="auto">
            <InputTypeIn
              icon="search"
              aria-label={t("search")}
              placeholder={t("search")}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </Section>
          <Section
            flexDirection="row"
            width="auto"
            height="auto"
            gap={1}
            role="group"
            aria-label={t("filters.label")}
          >
            {KIND_FILTERS.map((value) => (
              <Button
                key={value}
                size="sm"
                prominence={kind === value ? "primary" : "tertiary"}
                aria-pressed={kind === value}
                onClick={() => setKind(value)}
              >
                {t(`filters.${value}`)}
              </Button>
            ))}
          </Section>
        </Section>
      </SettingsLayouts.Header>
      <SettingsLayouts.Body>
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
      </SettingsLayouts.Body>
      {adding && (
        <AddIntegrationModal
          canChooseOrganization={isGlobalHolder}
          onClose={() => setAdding(false)}
          onCreated={(created) => {
            setAdding(false);
            void mutate();
            navigation.go(
              integrationDetailHref(
                created.id,
                created.needs_setup ? "configuration" : "actions"
              )
            );
          }}
        />
      )}
    </SettingsLayouts.Root>
  );
}
