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
  return (
    <TextArrayField
      name={name}
      label={typeof label === "function" ? label(null) : label}
      values={values}
      subtext={
        typeof description === "function" ? description(null) : description
      }
      placeholder={`Enter ${
        typeof label === "function" ? label(null) : label.toLowerCase()
      }`}
    />
  );
};

export default ListInput;
