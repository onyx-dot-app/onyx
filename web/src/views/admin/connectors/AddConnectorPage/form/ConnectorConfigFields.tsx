import React, { useEffect, useState } from "react";
import CredentialSubText from "@/lib/credentials/components/CredentialFields";
import type { ConnectionConfiguration } from "@/lib/connectors/types";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import type { Credential } from "@/lib/credentials/types";
import { RenderField } from "./FieldRendering";
import { useFormikContext } from "formik";

export interface ConnectorConfigFieldsProps {
  config: ConnectionConfiguration;
  values: any;
  connector: ConfigurableSources;
  currentCredential: Credential<any> | null;
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

  return (
    <>
      {config.subtext && (
        <CredentialSubText>{config.subtext}</CredentialSubText>
      )}

      {config.values.map(
        (field) =>
          !field.hidden && (
            <RenderField
              key={field.name}
              field={field}
              values={values}
              connector={connector}
              currentCredential={currentCredential}
            />
          )
      )}

      {/* Advanced fields are all optional, so they sit in the same flat
        list instead of behind a toggle. */}
      {(!config.advancedValuesVisibleCondition ||
        config.advancedValuesVisibleCondition(values, currentCredential)) &&
        config.advanced_values.map(
          (field) =>
            !field.hidden && (
              <RenderField
                key={field.name}
                field={field}
                values={values}
                connector={connector}
                currentCredential={currentCredential}
              />
            )
        )}
    </>
  );
}
