"use client";

import { useState } from "react";
import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Card, Collapsible, TextButton } from "@opal/components";
import { Section } from "@opal/layouts";
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
import { getSourceDisplayName } from "@/lib/connectors/utils";
import {
  buildConfigEntries,
  ConfigDisplay,
} from "@/views/admin/connectors/ConnectorDetailPage/ConfigDisplay";
import InlineFileManagement from "@/views/admin/connectors/ConnectorDetailPage/InlineFileManagement";

interface LabeledConfigDisplayProps {
  source: ConfigurableSources;
  config: ConfigEntries;
  credentialId: number;
  connectorId: number;
}

/** Rows by the form's translated labels, listing-backed values (channel ids) by their found names. */
function LabeledConfigDisplay({
  source,
  config,
  credentialId,
  connectorId,
}: LabeledConfigDisplayProps) {
  const configuration = useConnectorConfiguration(source);
  const { reportFor } = useCredentialCheckReports(source);
  const entries = useMemo(() => {
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
    return Object.fromEntries(
      Object.entries(buildConfigEntries(labeled, source)).map(
        ([key, value]) => [labels.get(key) ?? key, value]
      )
    );
  }, [configuration, config, credentialId, connectorId, reportFor, source]);
  return <ConfigDisplay configEntries={entries} />;
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
  const [open, setOpen] = useState(false);
  const source = ccPair.connector.source;
  const config: ConfigEntries =
    ccPair.connector.connector_specific_config ?? {};
  const entries = buildConfigEntries(config, source);
  const count = Object.keys(entries).length;
  if (count === 0 && !manageFiles) return null;

  return (
    <Collapsible
      title={t("title")}
      description={t("description", {
        source: getSourceDisplayName(source) ?? "",
        count,
      })}
      open={open}
      onOpenChange={setOpen}
      // The edit action shows with the content it edits.
      rightChildren={
        open &&
        onEdit !== null && (
          <TextButton font="secondary-action" onClick={onEdit}>
            {t("editButton.label")}
          </TextButton>
        )
      }
    >
      <Card border="solid" rounding={4} padding={4}>
        <Section gap={4} alignItems="stretch" height="fit">
          {count > 0 &&
            (isEditableSource(source) ? (
              <LabeledConfigDisplay
                source={source}
                config={config}
                credentialId={ccPair.credential.id}
                connectorId={ccPair.connector.id}
              />
            ) : (
              <ConfigDisplay configEntries={entries} />
            ))}
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
