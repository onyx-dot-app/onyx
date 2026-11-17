"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Button,
  InputTypeIn,
  Table,
  Text,
  type TableColumn,
} from "@opal/components";
import { IllustrationContent, Section, SettingsLayouts } from "@opal/layouts";
import { SvgUnPlugged } from "@opal/illustrations";
import { useNavigation } from "@opal/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useAdminIntegrations } from "@/lib/integrations/hooks";
import type { AdminPluginEntry } from "@/lib/integrations/types";
import {
  integrationDetailHref,
  pluginsFromIntegrations,
} from "@/lib/integrations/utils";

export default function AdminPluginsPage() {
  const t = useTranslations("admin.plugins");
  const locale = useLocale();
  const navigation = useNavigation();
  const { data, error, isLoading } = useAdminIntegrations();
  const [query, setQuery] = useState("");
  const search = query.trim().toLocaleLowerCase();
  const entries = pluginsFromIntegrations(data ?? [], locale).filter((entry) =>
    [entry.plugin.plugin_name, ...entry.integrations.map((i) => i.name)]
      .join(" ")
      .toLocaleLowerCase()
      .includes(search)
  );

  const columns: TableColumn<AdminPluginEntry>[] = [
    {
      kind: "display",
      id: "name",
      title: t("columns.name"),
      width: { weight: 26 },
      cell: (row) => (
        <Text font="main-ui-action" color="text-04" maxLines={1}>
          {row.plugin.plugin_name}
        </Text>
      ),
    },
    {
      kind: "display",
      id: "library",
      title: t("columns.library"),
      width: { weight: 24 },
      cell: (row) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {row.plugin.scope === "organization"
            ? t("library.organization")
            : t("library.personal", { owner: row.plugin.owner_email ?? "" })}
        </Text>
      ),
    },
    {
      kind: "display",
      id: "installation",
      title: t("columns.installation"),
      width: { weight: 16 },
      cell: (row) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {t("installation", {
            policy: row.plugin.installation_policy ?? "none",
          })}
        </Text>
      ),
    },
    {
      kind: "display",
      id: "integrations",
      title: t("columns.integrations"),
      width: { weight: 34 },
      cell: (row) => (
        <Section
          flexDirection="row"
          justifyContent="start"
          gap={1}
          wrap
          height="auto"
        >
          {row.integrations.map((integration) => (
            <Button
              key={integration.id}
              size="sm"
              prominence="tertiary"
              aria-label={t("openIntegration", { name: integration.name })}
              onClick={() =>
                navigation.go(integrationDetailHref(integration.id))
              }
            >
              {integration.name}
            </Button>
          ))}
        </Section>
      ),
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
        actions={[
          <Button
            key="integrations"
            prominence="secondary"
            onClick={() => navigation.go(ADMIN_ROUTES.INTEGRATIONS.path)}
          >
            {t("manageIntegrations")}
          </Button>,
        ]}
      >
        <Section width="auto" height="auto" alignItems="start">
          <InputTypeIn
            icon="search"
            aria-label={t("search")}
            placeholder={t("search")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </Section>
      </SettingsLayouts.Header>
      <SettingsLayouts.Body>
        <Table
          label={t("title")}
          items={entries}
          columns={columns}
          getRowId={(row) => row.plugin.plugin_id}
          pageSize={false}
          emptyState={
            <IllustrationContent
              illustration={SvgUnPlugged}
              title={t("empty.title")}
              description={t("empty.description")}
            />
          }
        />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
