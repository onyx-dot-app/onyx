import { useTranslations } from "next-intl";
import { Disabled } from "@opal/core";
import { Card, Collapsible } from "@opal/components";
import { InputVertical, Section } from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import DocumentAccessField from "@/views/admin/connectors/AddConnectorPage/sections/shared/DocumentAccessField";
import ManageAccessField from "@/views/admin/connectors/AddConnectorPage/sections/shared/ManageAccessField";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import type { Credential } from "@/lib/credentials/types";
import { getSourceDisplayName } from "@/lib/sources";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";

interface ConnectorSettingsSectionProps {
  connector: ConfigurableSources;
  currentCredential: Credential<any> | null;
  disabled?: boolean;
  /** Why the section is disabled, shown as a tooltip. */
  disabledReason?: string;
}

/** The connector's name, who can read its documents, and who manages it. */
export default function ConnectorSettingsSection({
  connector,
  currentCredential,
  disabled,
  disabledReason,
}: ConnectorSettingsSectionProps) {
  const t = useTranslations("admin.connectorsList.settings");
  // Below Business every connector is public and only admins manage it.
  const businessTier = useTierAtLeast(Tier.BUSINESS);

  return (
    <Disabled disabled={disabled} tooltip={disabledReason}>
      {/* A disabled fieldset also takes the controls out of the tab order;
        the wrapper above only blocks the pointer. */}
      <fieldset disabled={disabled} className="contents">
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
                  <InputTypeInField
                    name="name"
                    data-testid="connector-name"
                    placeholder={getSourceDisplayName(connector) ?? undefined}
                    variant={disabled ? "disabled" : "primary"}
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
      </fieldset>
    </Disabled>
  );
}
