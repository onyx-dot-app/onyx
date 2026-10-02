import { useState } from "react";
import { Section } from "@opal/layouts";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import type { ConnectionConfiguration } from "@/lib/connectors/types";
import type { Credential } from "@/lib/credentials/types";
import { RenderField } from "@/views/admin/connectors/AddConnectorPage/form/FieldRendering";

type ConnectorField = ConnectionConfiguration["values"][number];

export interface CredentialBoundFieldsProps {
  /** Bound fields shown at all times. */
  fields: ConnectorField[];
  /** Bound fields shown behind the advanced options toggle. */
  advancedFields: ConnectorField[];
  /** Shows the advanced toggle, as `advancedValuesVisibleCondition` does. */
  showAdvancedFields: boolean;
  values: Record<string, unknown>;
  connector: ConfigurableSources;
  currentCredential: Credential<unknown> | null;
}

/**
 * The connector fields bound to the credential, such as the site URL. The
 * create page shows them above the credential section, because the account
 * must belong to the site they name.
 */
export default function CredentialBoundFields({
  fields,
  advancedFields,
  showAdvancedFields,
  values,
  connector,
  currentCredential,
}: CredentialBoundFieldsProps) {
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);
  const visibleFields = fields.filter((field) => !field.hidden);
  const visibleAdvancedFields = showAdvancedFields
    ? advancedFields.filter((field) => !field.hidden)
    : [];

  function renderField(field: ConnectorField) {
    return (
      <RenderField
        key={field.name}
        field={field}
        values={values}
        connector={connector}
        currentCredential={currentCredential}
      />
    );
  }

  return (
    <Section
      gap={4}
      alignItems="start"
      width="full"
      data-testid="credential-bound-fields"
    >
      {visibleFields.map(renderField)}
      {visibleAdvancedFields.length > 0 && (
        <>
          <AdvancedOptionsToggle
            showAdvancedOptions={showAdvancedOptions}
            setShowAdvancedOptions={setShowAdvancedOptions}
          />
          {showAdvancedOptions && visibleAdvancedFields.map(renderField)}
        </>
      )}
    </Section>
  );
}
