import React from "react";
import { ListOption } from "@/lib/connectors/connectors";
import { TextArrayField } from "@/components/admin/connectors/Field";
import { useFormikContext } from "formik";

interface ListInputProps {
  field: ListOption;
}

const ListInput: React.FC<ListInputProps> = ({ field }) => {
  const { values } = useFormikContext<any>();
  return (
    <TextArrayField
      name={field.name}
      label={field.label}
      values={values}
      subtext={field.description}
      placeholder={`Enter ${field.label.toLowerCase()}`}
    />
  );
};

export default ListInput;
