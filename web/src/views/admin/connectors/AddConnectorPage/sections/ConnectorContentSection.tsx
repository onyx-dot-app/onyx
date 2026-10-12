import { useTranslations } from "next-intl";
import { Card, Collapsible } from "@opal/components";
import { Section } from "@opal/layouts";
import ConnectorConfigFields from "@/views/admin/connectors/AddConnectorPage/form/ConnectorConfigFields";
import type { ConnectionConfiguration } from "@/lib/connectors/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import type { Credential } from "@/lib/credentials/types";

interface ConnectorContentSectionProps {
  /** The connector's fields that are not bound to the credential. */
  config: ConnectionConfiguration;
  values: Record<string, unknown>;
  connector: ConfigurableSources;
  currentCredential: Credential<any> | null;
  /** Freezes the section while the page locks the configuration. */
  disabled?: boolean;
}

/** What the connector indexes: the source-specific configuration fields. */
export default function ConnectorContentSection({
  config,
  values,
  connector,
  currentCredential,
  disabled,
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
          />
        </Section>
      </Card>
    </Collapsible>
  );
}
