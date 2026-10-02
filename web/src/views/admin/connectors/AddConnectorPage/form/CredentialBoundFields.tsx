import { useTranslations } from "next-intl";
import { Section } from "@opal/layouts";
import { Text } from "@opal/components";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import type { CredentialBindingFieldError } from "@/lib/connectors/bindingGate";
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
  /** Field name to the error the backend gave for the field and credential. */
  fieldErrors?: Record<string, CredentialBindingFieldError>;
  /** Called when focus leaves a bound field. */
  onFieldBlur?: () => void;
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
  fieldErrors = {},
  onFieldBlur,
}: CredentialBoundFieldsProps) {
  const t = useTranslations("admin.connectorsList.boundFields");
  const visibleFields = fields.filter((field) => !field.hidden);
  const visibleAdvancedFields = showAdvancedFields
    ? advancedFields.filter((field) => !field.hidden)
    : [];

  function errorText(error: CredentialBindingFieldError): string {
    return error.kind === "missing"
      ? t("errors.missing")
      : t("errors.invalid", { detail: error.detail });
  }

  function renderField(field: ConnectorField) {
    const error = fieldErrors[field.name];
    return (
      <Section key={field.name} gap={0.5} alignItems="start" width="full">
        <RenderField
          field={field}
          values={values}
          connector={connector}
          currentCredential={currentCredential}
        />
        {error && (
          <Text font="secondary-body" color="status-error-05" role="alert">
            {errorText(error)}
          </Text>
        )}
      </Section>
    );
  }

  return (
    <Section
      gap={4}
      alignItems="start"
      width="full"
      data-testid="credential-bound-fields"
      onBlur={onFieldBlur}
    >
      {visibleFields.map(renderField)}
      {visibleAdvancedFields.length > 0 && (
        <SimpleCollapsible defaultOpen={false}>
          <SimpleCollapsible.Header
            title={t("advancedOptions")}
            sizePreset="main-ui"
          />
          <SimpleCollapsible.Content>
            <Section gap={4} alignItems="start" width="full">
              {visibleAdvancedFields.map(renderField)}
            </Section>
          </SimpleCollapsible.Content>
        </SimpleCollapsible>
      )}
    </Section>
  );
}
