import React, { Dispatch, FC, SetStateAction, useState } from "react";
import CredentialSubText, {
  AdminBooleanFormField,
} from "@/components/credentials/CredentialFields";
import { FileUpload } from "@/components/admin/connectors/FileUpload";
import { ConnectionConfiguration } from "@/lib/connectors/connectors";
import SelectInput from "./ConnectorInput/SelectInput";
import NumberInput from "./ConnectorInput/NumberInput";
import { TextFormField } from "@/components/admin/connectors/Field";
import ListInput from "./ConnectorInput/ListInput";
import FileInput from "./ConnectorInput/FileInput";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import { AccessTypeForm } from "@/components/admin/connectors/AccessTypeForm";
import { AccessTypeGroupSelector } from "@/components/admin/connectors/AccessTypeGroupSelector";
import { ConfigurableSources } from "@/lib/types";
import { Credential } from "@/lib/connectors/credentials";
import CollapsibleSection from "@/app/admin/assistants/CollapsibleSection";

export interface DynamicConnectionFormProps {
  config: ConnectionConfiguration;
  selectedFiles: File[];
  setSelectedFiles: Dispatch<SetStateAction<File[]>>;
  values: any;
  connector: ConfigurableSources;
  currentCredential: Credential<any> | null;
}

interface RenderFieldProps {
  field: any;
  values: any;
  selectedFiles: File[];
  setSelectedFiles: Dispatch<SetStateAction<File[]>>;
  connector: ConfigurableSources;
  currentCredential: Credential<any> | null;
}

const RenderField: FC<RenderFieldProps> = ({
  field,
  values,
  selectedFiles,
  setSelectedFiles,
  connector,
  currentCredential,
}) => {
  if (
    field.visibleCondition &&
    !field.visibleCondition(values, currentCredential)
  ) {
    return null;
  }

  const label =
    typeof field.label === "function"
      ? field.label(currentCredential)
      : field.label;
  const description =
    typeof field.description === "function"
      ? field.description(currentCredential)
      : field.description;

  const fieldContent = (
    <>
      {field.type === "file" ? (
        <FileUpload
          name={field.name}
          selectedFiles={selectedFiles}
          setSelectedFiles={setSelectedFiles}
        />
      ) : field.type === "zip" ? (
        <FileInput
          name={field.name}
          label={label}
          optional={field.optional}
          description={description}
        />
      ) : field.type === "list" ? (
        <ListInput name={field.name} label={label} description={description} />
      ) : field.type === "select" ? (
        <SelectInput
          name={field.name}
          optional={field.optional}
          description={description}
          options={field.options || []}
          label={label}
        />
      ) : field.type === "number" ? (
        <NumberInput
          label={label}
          optional={field.optional}
          description={description}
          name={field.name}
        />
      ) : field.type === "checkbox" ? (
        <AdminBooleanFormField
          checked={values[field.name]}
          subtext={description}
          name={field.name}
          label={label}
        />
      ) : (
        <TextFormField
          subtext={description}
          optional={field.optional}
          type={field.type}
          label={label}
          name={field.name}
        />
      )}
    </>
  );

  if (
    field.visibleCondition &&
    field.visibleCondition(values, currentCredential)
  ) {
    return (
      <CollapsibleSection prompt={label} key={field.name}>
        {fieldContent}
      </CollapsibleSection>
    );
  } else {
    return <div key={field.name}>{fieldContent}</div>;
  }
};

const DynamicConnectionForm: FC<DynamicConnectionFormProps> = ({
  config,
  selectedFiles,
  setSelectedFiles,
  values,
  connector,
  currentCredential,
}) => {
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  return (
    <>
      <h2 className="text-2xl font-bold text-text-800">{config.description}</h2>

      {config.subtext && (
        <CredentialSubText>{config.subtext}</CredentialSubText>
      )}

      <TextFormField
        subtext="A descriptive name for the connector. This will be used to identify the connector in the Admin UI."
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
              selectedFiles={selectedFiles}
              setSelectedFiles={setSelectedFiles}
              connector={connector}
              currentCredential={currentCredential}
            />
          )
      )}

      <AccessTypeForm connector={connector} />
      <AccessTypeGroupSelector />

      {config.advanced_values.length > 0 && (
        <>
          <AdvancedOptionsToggle
            showAdvancedOptions={showAdvancedOptions}
            setShowAdvancedOptions={setShowAdvancedOptions}
          />
          {showAdvancedOptions &&
            config.advanced_values.map((field) => (
              <RenderField
                key={field.name}
                field={field}
                values={values}
                selectedFiles={selectedFiles}
                setSelectedFiles={setSelectedFiles}
                connector={connector}
                currentCredential={currentCredential}
              />
            ))}
        </>
      )}
    </>
  );
};

export default DynamicConnectionForm;
