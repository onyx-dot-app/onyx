import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Card, Collapsible, Divider } from "@opal/components";
import { Section } from "@opal/layouts";
import ConnectorConfigFields from "@/views/admin/connectors/AddConnectorPage/form/ConnectorConfigFields";
import { IndexingStartField } from "@/views/admin/connectors/AddConnectorPage/sections/ScheduleSection";
import type { ConnectionConfiguration } from "@/lib/connectors/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import type { CredentialValues } from "@/lib/credentials/types";
import type { StoredReportScope } from "@/lib/connectors/checks/findings";

interface ConnectorContentSectionProps {
  /** The connector's fields that are not bound to the credential. */
  config: ConnectionConfiguration;
  values: Record<string, unknown>;
  connector: ConfigurableSources;
  currentCredential: CredentialValues | null;
  /** The stored check reports that can list a field's options. */
  reportScope: StoredReportScope | null;
  /** Freezes the section while the page locks the configuration. */
  disabled?: boolean;
  /** Extra content below the fields, such as an edit's file list. */
  children?: ReactNode;
  /** Whether fields or `children` come before the start date. */
  hasFields: boolean;
  /** Shows the start date at the bottom. */
  indexingStart: boolean;
}

/** What the connector indexes: the source-specific configuration fields,
 * then the date to index from. */
export default function ConnectorContentSection({
  config,
  values,
  connector,
  currentCredential,
  reportScope,
  disabled,
  children,
  hasFields,
  indexingStart,
}: ConnectorContentSectionProps) {
  const t = useTranslations("admin.connectorsList.content");

  return (
    <Collapsible
      title={t("title")}
      description={t("description")}
      disabled={disabled}
    >
      <Card border="solid" rounding={4} padding={4} disabled={disabled}>
        <Section gap={4} alignItems="start" width="full">
          <ConnectorConfigFields
            values={values}
            config={config}
            connector={connector}
            currentCredential={currentCredential}
            reportScope={reportScope}
          />
          {children}
          {indexingStart && (
            <Section alignItems="stretch" gap={4} width="full">
              {hasFields && (
                <Divider paddingParallel={0} paddingPerpendicular={0} />
              )}
              <IndexingStartField disabled={disabled} />
            </Section>
          )}
        </Section>
      </Card>
    </Collapsible>
  );
}
