"use client";

import { Fragment, useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Button, Card, Collapsible, Divider } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgEditBig } from "@opal/icons";
import { markdown } from "@opal/utils";
import type { RichStr } from "@opal/types";
import { useConnectorConfiguration } from "@/lib/connectors/connectors";
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
import HierarchyBreakdown, {
  breakdownGroups,
  useHierarchyBreakdown,
} from "@/views/admin/connectors/ConnectorDetailPage/HierarchyBreakdown";
import InlineFileManagement from "@/views/admin/connectors/ConnectorDetailPage/InlineFileManagement";

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
}

/** The settings bound to the account, then the breakdown, then the other settings, with a divider between the parts. */
function ConfigGroups({
  rows,
  ccPair,
  showBreakdown,
  showEmptyBreakdown,
}: ConfigGroupsProps) {
  const bound = new Set(credentialBoundFieldNames(ccPair.connector.source));
  const { data } = useHierarchyBreakdown(ccPair.id);
  // The breakdown lists these settings' values, so their rows go.
  const covered = new Set(data?.config_fields ?? []);
  const boundRows = rows.filter((row) => bound.has(row.key));
  const restRows = rows.filter(
    (row) => !bound.has(row.key) && !covered.has(row.key)
  );
  const parts: React.ReactNode[] = [];
  if (boundRows.length > 0) {
    parts.push(<ConfigDisplay key="bound" rows={boundRows} />);
  }
  if (showBreakdown) {
    parts.push(
      <HierarchyBreakdown
        key="breakdown"
        ccPairId={ccPair.id}
        showEmpty={showEmptyBreakdown}
      />
    );
  }
  if (restRows.length > 0) {
    parts.push(<ConfigDisplay key="rest" rows={restRows} />);
  }
  return (
    <Section gap={4} alignItems="stretch" height="fit">
      {parts.map((part, index) => (
        <Fragment key={index}>
          {index > 0 && (
            <Divider paddingParallel={0} paddingPerpendicular={0} />
          )}
          {part}
        </Fragment>
      ))}
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
    const labels = new Map(
      configFields([
        ...configuration.values,
        ...configuration.advanced_values,
      ]).map((field) => [
        field.name,
        typeof field.label === "function" ? field.label(null) : field.label,
      ])
    );
    return Object.entries(buildConfigEntries(labeled, source)).map(
      ([key, value]): ConfigRow => ({
        key,
        label: labels.get(key) ?? key,
        value,
      })
    );
  }, [configuration, config, credentialId, connectorId, reportFor, source]);
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
  const realmText =
    typeof realm === "string"
      ? realmMarkdown(realm)
      : escapeMarkdown(getSourceDisplayName(source) ?? "");
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
  const groupProps = {
    ccPair,
    showBreakdown,
    showEmptyBreakdown: breakdownOnly,
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
          <Button prominence="secondary" icon={SvgEditBig} onClick={onEdit}>
            {t("editButton.label")}
          </Button>
        )
      }
    >
      <Card border="solid" rounding={4} padding={4}>
        <Section gap={4} alignItems="stretch" height="fit">
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
