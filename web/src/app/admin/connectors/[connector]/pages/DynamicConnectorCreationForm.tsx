import React, { Dispatch, FC, SetStateAction, useState } from "react";
import CredentialSubText from "@/components/credentials/CredentialFields";
import { ConnectionConfiguration } from "@/lib/connectors/connectors";
import { TextFormField } from "@/components/admin/connectors/Field";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { AccessTypeForm } from "@/components/admin/connectors/AccessTypeForm";
import { AccessTypeGroupSelector } from "@/components/admin/connectors/AccessTypeGroupSelector";
import { ConfigurableSources } from "@/lib/types";
import { Credential } from "@/lib/connectors/credentials";
import { RenderField } from "./FieldRendering";

export interface DynamicConnectionFormProps {
  config: ConnectionConfiguration;
  values: any;
  connector: ConfigurableSources;
  currentCredential: Credential<any> | null;
}

const DynamicConnectionForm: FC<DynamicConnectionFormProps> = ({
  config,
  values,
  connector,
  currentCredential,
}) => {
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

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

      <AccessTypeForm connector={connector} />
      <AccessTypeGroupSelector connector={connector} />

      {config.advanced_values.length > 0 && (
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
};

export default DynamicConnectionForm;
