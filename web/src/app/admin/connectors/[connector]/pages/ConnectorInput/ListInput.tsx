import React from "react";
import { TextArrayField } from "@/components/Field";
import { useFormikContext } from "formik";

interface ListInputProps {
  name: string;
  label: string | ((credential: any) => string);
  description: string | ((credential: any) => string);
}

const ListInput: React.FC<ListInputProps> = ({ name, label, description }) => {
  const { values } = useFormikContext<any>();
  const resolvedLabel = typeof label === "function" ? label(null) : label;
  return (
    <div>
      <TextArrayField
        name={name}
        label={resolvedLabel}
        values={values}
        subtext={
          typeof description === "function" ? description(null) : description
        }
        placeholder={`Enter ${resolvedLabel.toLowerCase()}`}
      />
    </div>
  );
};

export default ListInput;
