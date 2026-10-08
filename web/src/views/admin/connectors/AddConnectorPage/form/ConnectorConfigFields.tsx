import React, { useEffect, useState } from "react";
import CredentialSubText from "@/lib/credentials/components/CredentialFields";
import type { ConnectionConfiguration } from "@/lib/connectors/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import type { CredentialValues } from "@/lib/credentials/types";
import { RenderField } from "./FieldRendering";
import { useFormikContext } from "formik";

type ConnectorField = ConnectionConfiguration["values"][number];

export interface ConnectorConfigFieldsProps {
  config: ConnectionConfiguration;
  values: any;
  connector: ConfigurableSources;
  currentCredential: CredentialValues | null;
}

export default function ConnectorConfigFields({
  config,
  values,
  connector,
  currentCredential,
}: ConnectorConfigFieldsProps) {
  const { setFieldValue } = useFormikContext<any>(); // Get Formik's context functions

  const [connectorNameInitialized, setConnectorNameInitialized] =
    useState(false);

  let initialConnectorName = "";
  if (config.initialConnectorName) {
    initialConnectorName =
      currentCredential?.credential_json?.[config.initialConnectorName] ?? "";
  }

  useEffect(() => {
    const field_value = values["name"];
    if (initialConnectorName && !connectorNameInitialized && !field_value) {
      setFieldValue("name", initialConnectorName);
      setConnectorNameInitialized(true);
    }
  }, [initialConnectorName, setFieldValue, values]);

  // Advanced fields are all optional, so they sit in the same flat list
  // instead of behind a toggle. A field's own visibleCondition still applies.
  const showAdvanced: boolean =
    !config.advancedValuesVisibleCondition ||
    config.advancedValuesVisibleCondition(values, currentCredential);
  const visibleFields: ConnectorField[] = [
    ...config.values,
    ...(showAdvanced ? config.advanced_values : []),
  ].filter(
    (field) =>
      !field.hidden &&
      (!field.visibleCondition ||
        field.visibleCondition(values, currentCredential))
  );

  return (
    <>
      {config.subtext && (
        <CredentialSubText>{config.subtext}</CredentialSubText>
      )}

      {visibleFields.map((field) => (
        <RenderField
          key={field.name}
          field={field}
          values={values}
          connector={connector}
          currentCredential={currentCredential}
        />
      ))}
    </>
  );
}
