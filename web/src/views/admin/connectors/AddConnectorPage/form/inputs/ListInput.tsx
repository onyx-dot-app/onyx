import React from "react";
import { TextArrayField } from "@/components/Field";
import { getIn, useFormikContext } from "formik";
import { useTranslations } from "next-intl";

interface ListInputProps {
  name: string;
  label: string | ((credential: any) => string);
  description: string | ((credential: any) => string);
}

const ListInput: React.FC<ListInputProps> = ({ name, label, description }) => {
  const t = useTranslations("admin.connectorsList");
  const { errors, touched, values } = useFormikContext<any>();
  const error = getIn(errors, name);
  const showArrayError = getIn(touched, name) && typeof error === "string";

  return (
    <>
      <TextArrayField
        name={name}
        label={typeof label === "function" ? label(null) : label}
        values={values}
        subtext={
          typeof description === "function" ? description(null) : description
        }
        placeholder={t("listInput.placeholder", {
          label:
            typeof label === "function" ? label(null) : label.toLowerCase(),
        })}
      />
      {showArrayError && (
        <div className="text-action-danger-05 text-sm mt-1">{error}</div>
      )}
    </>
  );
};

export default ListInput;
