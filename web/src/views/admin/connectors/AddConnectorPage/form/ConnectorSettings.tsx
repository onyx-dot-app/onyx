import { useTranslations } from "next-intl";
import { Card, Collapsible, InputTypeIn } from "@opal/components";
import { InputVertical, Section } from "@opal/layouts";
import { FormikField } from "@/refresh-components/form/FormikField";
import DocumentAccessField from "@/lib/connectors/components/DocumentAccessField";
import ManageAccessField from "@/lib/connectors/components/ManageAccessField";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import type { Credential } from "@/lib/credentials/types";
import { getSourceDisplayName } from "@/lib/sources";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";

interface ConnectorSettingsProps {
  connector: ConfigurableSources;
  currentCredential: Credential<any> | null;
  disabled?: boolean;
}

/** The connector's name, who can read its documents, and who manages it. */
export default function ConnectorSettings({
  connector,
  currentCredential,
  disabled,
}: ConnectorSettingsProps) {
  const t = useTranslations("admin.connectorsList.settings");
  // Below Business every connector is public and only admins manage it.
  const businessTier = useTierAtLeast(Tier.BUSINESS);

  return (
    <Collapsible
      title={t("title")}
      description={t("description")}
      disabled={disabled}
    >
      <Section gap={3} alignItems="stretch" height="fit">
        <Card border="solid" rounding={4} padding={4} disabled={disabled}>
          <Section gap={4} alignItems="stretch" height="fit">
            <InputVertical
              withLabel="name"
              disabled={disabled}
              title={t("displayName.title")}
            >
              <FormikField<string>
                name="name"
                render={(field) => (
                  <InputTypeIn
                    id="name"
                    data-testid="connector-name"
                    name={field.name}
                    value={field.value ?? ""}
                    onChange={field.onChange}
                    onBlur={field.onBlur}
                    placeholder={getSourceDisplayName(connector) ?? undefined}
                    variant={disabled ? "disabled" : "primary"}
                  />
                )}
              />
            </InputVertical>
            <DocumentAccessField
              connector={connector}
              currentCredential={currentCredential}
              disabled={disabled}
            />
          </Section>
        </Card>

        {businessTier && (
          <Card border="solid" rounding={4} padding={4} disabled={disabled}>
            <ManageAccessField disabled={disabled} />
          </Card>
        )}
      </Section>
    </Collapsible>
  );
}
