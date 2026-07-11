import React from "react";
import { TextArrayField } from "@/components/Field";
import { useFormikContext } from "formik";
import { Button } from "@opal/components";

interface ListInputProps {
  name: string;
  label: string | ((credential: any) => string);
  description: string | ((credential: any) => string);
  defaultValues?: string[];
}

const ListInput: React.FC<ListInputProps> = ({
  name,
  label,
  description,
  defaultValues,
}) => {
  const { values, setFieldValue } = useFormikContext<any>();
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
      {defaultValues && defaultValues.length > 0 && (
        <div className="pt-2">
          <Button
            type="button"
            prominence="tertiary"
            size="sm"
            onClick={() => setFieldValue(name, defaultValues)}
          >
            Use defaults
          </Button>
        </div>
      )}
    </div>
  );
};

export default ListInput;
