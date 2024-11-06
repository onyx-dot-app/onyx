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

export interface DynamicConnectionFormProps {
  config: ConnectionConfiguration;
  selectedFiles: File[];
  setSelectedFiles: Dispatch<SetStateAction<File[]>>;
  values: any;
  connector: ConfigurableSources;
}

const DynamicConnectionForm: FC<DynamicConnectionFormProps> = ({
  config,
  selectedFiles,
  setSelectedFiles,
  values,
  connector,
}) => {
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);

  const renderField = (field: any) => (
    <div key={field.name}>
      {field.type === "file" ? (
        <FileUpload
          name={field.name}
          selectedFiles={selectedFiles}
          setSelectedFiles={setSelectedFiles}
        />
      ) : field.type === "zip" ? (
        <FileInput
          name={field.name}
          label={field.label}
          optional={field.optional}
          description={field.description}
        />
      ) : field.type === "list" ? (
        <ListInput field={field} />
      ) : field.type === "select" ? (
        <SelectInput
          name={field.name}
          optional={field.optional}
          description={field.description}
          options={field.options || []}
          label={field.label}
        />
      ) : field.type === "number" ? (
        <NumberInput
          label={field.label}
          optional={field.optional}
          description={field.description}
          name={field.name}
        />
      ) : field.type === "checkbox" ? (
        <AdminBooleanFormField
          checked={values[field.name]}
          subtext={field.description}
          name={field.name}
          label={field.label}
        />
      ) : (
        <TextFormField
          subtext={field.description}
          optional={field.optional}
          type={field.type}
          label={field.label}
          name={field.name}
        />
      )}
    </div>
  );

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

      {config.values.map((field) => !field.hidden && renderField(field))}

      <AccessTypeForm connector={connector} />
      <AccessTypeGroupSelector />

      {config.advanced_values.length > 0 && (
        <>
          <AdvancedOptionsToggle
            showAdvancedOptions={showAdvancedOptions}
            setShowAdvancedOptions={setShowAdvancedOptions}
          />
          {showAdvancedOptions && config.advanced_values.map(renderField)}
        </>
      )}
    </>
  );
};

export default DynamicConnectionForm;
