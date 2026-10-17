"use client";

import { useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Button, Card, Collapsible } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgEditBig } from "@opal/icons";
import { markdown } from "@opal/utils";
import type { RichStr } from "@opal/types";
import {
  connectorConfigs,
  useConnectorConfiguration,
} from "@/lib/connectors/connectors";
import { isEditableSource } from "@/lib/connectors/edit/editable";
import type { CCPairFullInfo, ConfigEntries } from "@/lib/connectors/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import { configFields } from "@/lib/connectors/checks/formState";
import {
  labelFindingValues,
  storedCheckResults,
} from "@/lib/connectors/checks/findings";
import { useCredentialCheckReports } from "@/lib/credentials/hooks";
import {
  credentialBoundFieldNames,
  getSourceDisplayName,
} from "@/lib/connectors/utils";
import {
  buildConfigEntries,
  ConfigDisplay,
  type ConfigRow,
} from "@/views/admin/connectors/ConnectorDetailPage/ConfigDisplay";
import { useHierarchyBreakdown } from "@/lib/connectors/hooks";
import HierarchyBreakdown, {
  breakdownGroups,
} from "@/views/admin/connectors/ConnectorDetailPage/HierarchyBreakdown";
import InlineFileManagement from "@/views/admin/connectors/ConnectorDetailPage/InlineFileManagement";
import { formatTimestamp } from "@opal/time";

/** Markdown-escapes a value so a URL with underscores stays literal. */
function escapeMarkdown(value: string): string {
  return value.replace(/([\\`*_[\]])/g, "\\$1");
}

/** The account's realm in bold: a URL shows its host in bold and keeps its path. */
function realmMarkdown(value: string): string {
  try {
    const url = new URL(value);
    const path = url.pathname.replace(/\/$/, "");
    return `**${escapeMarkdown(url.host)}**${escapeMarkdown(path)}`;
  } catch {
    return `**${escapeMarkdown(value)}**`;
  }
}

interface ConfigGroupsProps {
  rows: ConfigRow[];
  ccPair: CCPairFullInfo;
  /** The breakdown has rows, a note, or a loader to show. */
  showBreakdown: boolean;
  showEmptyBreakdown: boolean;
  /** Shown after the other settings: when indexing starts from. */
  lastRow: ConfigRow;
}

interface ConfigPanelProps {
  children: React.ReactNode;
}
/** A white panel on the section's tinted card. */
function ConfigPanel({ children }: ConfigPanelProps) {
  return (
    <Card color="background-tint-00" rounding={3} padding={3}>
      {children}
    </Card>
  );
}

/** The settings bound to the account and the breakdown, each on a panel, then the other settings. */
function ConfigGroups({
  rows,
  ccPair,
  showBreakdown,
  showEmptyBreakdown,
  lastRow,
}: ConfigGroupsProps) {
  const bound = new Set(credentialBoundFieldNames(ccPair.connector.source));
  const { data } = useHierarchyBreakdown(ccPair.id);
  // The breakdown lists these settings' values, so their rows go.
  const covered = new Set(data?.config_fields ?? []);
  const boundRows = rows.filter((row) => bound.has(row.key));
  const restRows = rows.filter(
    (row) => !bound.has(row.key) && !covered.has(row.key)
  );
  return (
    <Section gap={2} alignItems="stretch" height="fit">
      {boundRows.length > 0 && (
        <ConfigPanel>
          <ConfigDisplay rows={boundRows} />
        </ConfigPanel>
      )}
      {showBreakdown && (
        <ConfigPanel>
          <HierarchyBreakdown
            ccPairId={ccPair.id}
            showEmpty={showEmptyBreakdown}
          />
        </ConfigPanel>
      )}
      <Section alignItems="stretch" height="fit" padding={0.75}>
        <ConfigDisplay rows={[...restRows, lastRow]} />
      </Section>
    </Section>
  );
}

interface LabeledConfigGroupsProps extends Omit<ConfigGroupsProps, "rows"> {
  source: ConfigurableSources;
  config: ConfigEntries;
}

/** Rows by the form's translated labels, listing-backed values (channel ids) by their found names. */
function LabeledConfigGroups({
  source,
  config,
  ccPair,
  ...rest
}: LabeledConfigGroupsProps) {
  const configuration = useConnectorConfiguration(source);
  const tTabs = useTranslations("admin.connectorsList.checkboxTabs");
  const { reportFor } = useCredentialCheckReports(source);
  const credentialId = ccPair.credential.id;
  const connectorId = ccPair.connector.id;
  const rows = useMemo(() => {
    const checks = storedCheckResults(reportFor, { credentialId, connectorId });
    // SAFETY: labelling replaces string list entries with string labels, so
    // every value keeps the stored JSON shape.
    const labeled = labelFindingValues(
      configuration,
      config,
      checks
    ) as ConfigEntries;
    // A label that depends on the credential reads as the generic form.
    const fields = configFields([
      ...configuration.values,
      ...configuration.advanced_values,
    ]);
    const labels = new Map(
      fields.map((field) => [
        field.name,
        typeof field.label === "function" ? field.label(null) : field.label,
      ])
    );
    // A checkbox the form shows as tabs reads by its tab labels.
    const booleanLabels = new Map(
      fields.flatMap((field) =>
        field.type === "checkbox" && field.tabLabels !== undefined
          ? [
              [
                field.name,
                {
                  true: tTabs(field.tabLabels.true),
                  false: tTabs(field.tabLabels.false),
                },
              ] as const,
            ]
          : []
      )
    );
    return Object.entries(buildConfigEntries(labeled, source)).map(
      ([key, value]): ConfigRow => ({
        key,
        label: labels.get(key) ?? key,
        value,
        booleanLabels: booleanLabels.get(key),
      })
    );
  }, [
    configuration,
    config,
    credentialId,
    connectorId,
    reportFor,
    source,
    tTabs,
  ]);
  return <ConfigGroups rows={rows} ccPair={ccPair} {...rest} />;
}

export interface IndexConfigurationsSectionProps {
  ccPair: CCPairFullInfo;
  /** Shows the edit action, which opens the connector form. `null` hides it. */
  onEdit: (() => void) | null;
  /** The files of a file connector can be managed in place. */
  manageFiles: boolean;
  onRefresh: () => void;
}

/** What the connector indexes: its source-specific settings, read-only. */
export default function IndexConfigurationsSection({
  ccPair,
  onEdit,
  manageFiles,
  onRefresh,
}: IndexConfigurationsSectionProps) {
  const t = useTranslations("admin.connector.configuration");
  const tTabs = useTranslations("admin.connectorsList.checkboxTabs");
  const tScheduled = useTranslations("admin.connectorsList.scheduled");
  const format = useFormatter();
  const [open, setOpen] = useState(false);
  const source = ccPair.connector.source;
  const config: ConfigEntries =
    ccPair.connector.connector_specific_config ?? {};
  const entries = buildConfigEntries(config, source);
  const count = Object.keys(entries).length;
  // A connector saved with no settings (e.g. Notion indexing everything)
  // still has a breakdown, so the section stays.
  const breakdownOnly = count === 0 && !manageFiles;
  const { data: breakdown, error: breakdownError } = useHierarchyBreakdown(
    ccPair.id
  );
  const groups = breakdown ? breakdownGroups(breakdown) : [];
  const showBreakdown =
    breakdownOnly ||
    breakdownError !== undefined ||
    breakdown === undefined ||
    (breakdown !== null &&
      (groups.length > 0 || breakdown.other_doc_count > 0));

  // The account's realm (its site or host) names the connector. The source does when there is none.
  const realm = credentialBoundFieldNames(source)
    .map((name) => config[name])
    .find((value) => typeof value === "string" && value !== "");
  const realmName =
    typeof realm === "string"
      ? realmMarkdown(realm)
      : escapeMarkdown(getSourceDisplayName(source) ?? "");
  // A source with two hosting types (Confluence Cloud or Data Center) names its type first.
  const sourceConfiguration = isEditableSource(source)
    ? connectorConfigs[source]
    : undefined;
  const hostField = configFields(
    sourceConfiguration === undefined
      ? []
      : [...sourceConfiguration.values, ...sourceConfiguration.advanced_values]
  ).find((field) => field.type === "checkbox" && field.tabLabels);
  const hostLabels =
    hostField?.type === "checkbox" ? hostField.tabLabels : undefined;
  const hostValue =
    hostField === undefined
      ? undefined
      : (config[hostField.name] ?? hostField.default);
  const realmText =
    hostLabels === undefined
      ? realmName
      : t("hostPrefix", {
          host: escapeMarkdown(
            tTabs(hostValue === true ? hostLabels.true : hostLabels.false)
          ),
          realm: realmName,
        });
  const description: RichStr = markdown(
    groups.length > 0
      ? t("summary", {
          realm: realmText,
          counts: format.list(
            groups.map(([nodeType, groupEntries]) =>
              t(`breakdown.counts.${nodeType}`, { count: groupEntries.length })
            ),
            { type: "conjunction" }
          ),
        })
      : t("description", { source: realmText, count })
  );

  const rows: ConfigRow[] = Object.entries(entries).map(([key, value]) => ({
    key,
    label: key,
    value,
  }));
  const indexingStart = ccPair.connector.indexing_start;
  const groupProps = {
    ccPair,
    showBreakdown,
    showEmptyBreakdown: breakdownOnly,
    lastRow: {
      key: "indexing_start",
      label: tScheduled("indexingStart.title"),
      value:
        indexingStart === null
          ? tScheduled("indexingStart.placeholder")
          : formatTimestamp(indexingStart, { dateOnly: true }),
    },
  };

  return (
    <Collapsible
      title={t("title")}
      description={description}
      open={open}
      onOpenChange={setOpen}
      // The edit action shows with the content it edits.
      rightChildren={
        open &&
        onEdit !== null && (
          <Button prominence="tertiary" icon={SvgEditBig} onClick={onEdit}>
            {t("editButton.label")}
          </Button>
        )
      }
    >
      <Card color="background-tint-01" border="solid" rounding={4} padding={1}>
        <Section gap={2} alignItems="stretch" height="fit">
          {isEditableSource(source) ? (
            <LabeledConfigGroups
              source={source}
              config={config}
              {...groupProps}
            />
          ) : (
            <ConfigGroups rows={rows} {...groupProps} />
          )}
          {manageFiles && (
            <InlineFileManagement
              connectorId={ccPair.connector.id}
              onRefresh={onRefresh}
            />
          )}
        </Section>
      </Card>
    </Collapsible>
  );
}
