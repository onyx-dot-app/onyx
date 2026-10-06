import { useTranslations } from "next-intl";
import { Card } from "@opal/components";
import { Disabled } from "@opal/core";
import { Content, Section } from "@opal/layouts";
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
  disabled?: boolean;
  /** Why the section is disabled, shown as its description and tooltip. */
  disabledReason?: string;
}

/** What the connector indexes: the source-specific configuration fields. */
export default function ConnectorContentSection({
  config,
  values,
  connector,
  currentCredential,
  disabled,
  disabledReason,
}: ConnectorContentSectionProps) {
  const t = useTranslations("admin.connectorsList.sections.configuration");

  return (
    <Disabled disabled={disabled} tooltip={disabledReason}>
      <Card border="solid" rounding={4} padding={6} disabled={disabled}>
        {/* A disabled fieldset also takes the controls out of the tab order;
          the wrapper above only blocks the pointer. */}
        <fieldset
          disabled={disabled}
          className="contents"
          data-testid="connector-form"
        >
          <Section gap={4} alignItems="start" width="full">
            {/* Announces why the section is locked when the reason changes. */}
            <Section
              alignItems="start"
              width="full"
              height="fit"
              aria-live="polite"
            >
              <Content
                title={t("title")}
                description={disabledReason}
                sizePreset="main-content"
                variant="section"
              />
            </Section>
            <ConnectorConfigFields
              values={values}
              config={config}
              connector={connector}
              currentCredential={currentCredential}
            />
          </Section>
        </fieldset>
      </Card>
    </Disabled>
  );
}
