"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Button,
  InputSingleSelect,
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
  toast,
} from "@opal/layouts";
import { SvgUnPlugged } from "@opal/illustrations";
import { SvgPlug } from "@opal/icons";
import { useNavigation } from "@opal/navigation";
import { useAdminIntegrations } from "@/lib/integrations/hooks";
import { setPluginInstallationPolicy } from "@/lib/integrations/svc";
import type {
  AdminPluginEntry,
  InstallationPolicy,
  IntegrationPluginRef,
} from "@/lib/integrations/types";
import {
  integrationDetailHref,
  pluginsFromIntegrations,
} from "@/lib/integrations/utils";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import {
  useInstallationPolicyCopy,
  usePolicyOptions,
} from "@/lib/skills/hooks";
import { INSTALLATION_POLICIES } from "@/lib/skills/installationPolicy";
import { Permission } from "@/lib/types";

type LibraryFilter = "all" | IntegrationPluginRef["scope"];
const LIBRARY_FILTERS: readonly LibraryFilter[] = [
  "all",
  "organization",
  "personal",
];

export default function AdminPluginsPage() {
  const t = useTranslations("admin.plugins");
  const locale = useLocale();
  const navigation = useNavigation();
  const { data, error, isLoading, mutate } = useAdminIntegrations();
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_ACTIONS);
  const policyCopy = useInstallationPolicyCopy();
  const policyOptions = usePolicyOptions();
  const [query, setQuery] = useState("");
  const [library, setLibrary] = useState<LibraryFilter>("all");
  const [savingPluginIds, setSavingPluginIds] = useState<ReadonlySet<string>>(
    new Set()
  );
  const search = query.trim().toLocaleLowerCase();
  const entries = pluginsFromIntegrations(data ?? [], locale).filter(
    (entry) =>
      (library === "all" || entry.plugin.scope === library) &&
      [entry.plugin.plugin_name, ...entry.integrations.map((i) => i.name)]
        .join(" ")
        .toLocaleLowerCase()
        .includes(search)
  );

  async function saveInstallationPolicy(
    row: AdminPluginEntry,
    policy: InstallationPolicy
  ) {
    const pluginId = row.plugin.plugin_id;
    setSavingPluginIds((ids) => new Set(ids).add(pluginId));
    try {
      await setPluginInstallationPolicy(row.plugin.plugin_id, policy);
      toast.success(
        t("installationSaved", {
          name: row.plugin.plugin_name,
          policy: policyCopy.label(policy),
        })
      );
    } catch (saveError) {
      toast.error(
        saveError instanceof Error
          ? saveError.message
          : t("installationSaveFailed")
      );
    }
    try {
      await mutate();
    } finally {
      setSavingPluginIds((ids) => {
        const next = new Set(ids);
        next.delete(pluginId);
        return next;
      });
    }
  }

  const columns: TableColumn<AdminPluginEntry>[] = [
    {
      kind: "display",
      id: "name",
      title: t("columns.name"),
      width: { weight: 26 },
      cell: (row) => (
        <Content
          icon={SvgPlug}
          title={row.plugin.plugin_name}
          description={t("contents", { count: row.integrations.length })}
          titleMaxLines={1}
          descriptionMaxLines={1}
        />
      ),
    },
    {
      kind: "display",
      id: "library",
      title: t("columns.library"),
      width: { weight: 20 },
      cell: (row) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {row.plugin.scope === "organization"
            ? t("library.organization")
            : (row.plugin.owner_email ?? t("library.personal"))}
        </Text>
      ),
    },
    {
      kind: "display",
      id: "installation",
      title: t("columns.installation"),
      width: { weight: 16 },
      cell: (row) => {
        const policy = row.plugin.installation_policy;
        // Only an Organization library plugin has an install setting.
        if (row.plugin.scope !== "organization" || policy === null)
          return (
            <Text font="main-ui-body" color="text-03" maxLines={1}>
              {"\u2014"}
            </Text>
          );
        return (
          <InputSingleSelect
            placeholder={t("installationSelect", {
              name: row.plugin.plugin_name,
            })}
            value={policy}
            disabled={
              !isGlobalHolder || savingPluginIds.has(row.plugin.plugin_id)
            }
            options={policyOptions}
            onValueChange={(value) => {
              const next = INSTALLATION_POLICIES.find(
                (option) => option === value
              );
              if (next && next !== policy)
                void saveInstallationPolicy(row, next);
            }}
          />
        );
      },
    },
    {
      kind: "display",
      id: "integrations",
      title: t("columns.integrations"),
      width: { weight: 32 },
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
        icon={SvgPlug}
        title={t("title")}
        description={t("description")}
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
          filters={[
            <InputSingleSelect
              key="filter"
              placeholder={t("filters.label")}
              value={library}
              defaultOption="all"
              options={LIBRARY_FILTERS.map((value) => ({
                value,
                title: t(`filters.${value}`),
              }))}
              onValueChange={(value) =>
                setLibrary(
                  LIBRARY_FILTERS.find((option) => option === value) ?? "all"
                )
              }
            />,
          ]}
        />
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
