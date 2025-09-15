import React, { useEffect, useState } from "react";
import CredentialSubText from "@/components/credentials/CredentialFields";
import { ConnectionConfiguration } from "@/lib/connectors/connectors";
import { TextFormField } from "@/components/Field";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { AccessTypeForm } from "@/components/admin/connectors/AccessTypeForm";
import { AccessTypeGroupSelector } from "@/components/admin/connectors/AccessTypeGroupSelector";
import { ConfigurableSources } from "@/lib/types";
import { Credential } from "@/lib/connectors/credentials";
import { RenderField } from "./FieldRendering";
import { useFormikContext } from "formik";

export interface DynamicConnectionFormProps {
  config: ConnectionConfiguration;
  values: any;
  connector: ConfigurableSources;
  currentCredential: Credential<any> | null;
}

export default function DynamicConnectionForm({
  config,
  values,
  connector,
  currentCredential,
}: DynamicConnectionFormProps) {
  const { setFieldValue } = useFormikContext<any>(); // Get Formik's context functions

  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);
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

      <TextFormField
        subtext="A descriptive name for the connector."
        type={"text"}
        label={"Connector Name"}
        name={"name"}
      />

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

      <AccessTypeForm
        connector={connector}
        currentCredential={currentCredential}
      />
      <AccessTypeGroupSelector connector={connector} />

      {config.advanced_values.length > 0 &&
        (!config.advancedValuesVisibleCondition ||
          config.advancedValuesVisibleCondition(values, currentCredential)) && (
          <>
            <AdvancedOptionsToggle
              showAdvancedOptions={showAdvancedOptions}
              setShowAdvancedOptions={setShowAdvancedOptions}
            />
            {showAdvancedOptions &&
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
        )}
    </>
  );
}
