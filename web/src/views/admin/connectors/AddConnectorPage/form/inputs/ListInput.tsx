import React from "react";
import { TextArrayField } from "@/components/Field";
import { useFormikContext } from "formik";
import { useTranslations } from "next-intl";

interface ListInputProps {
  name: string;
  label: string | ((credential: any) => string);
  description: string | ((credential: any) => string);
}

const ListInput: React.FC<ListInputProps> = ({ name, label, description }) => {
  const t = useTranslations("admin.connectorsList");
  const { values } = useFormikContext<any>();
  return (
    <TextArrayField
      name={name}
      label={typeof label === "function" ? label(null) : label}
      values={values}
      subtext={
        typeof description === "function" ? description(null) : description
      }
      placeholder={t("listInput.placeholder", {
        label: typeof label === "function" ? label(null) : label.toLowerCase(),
      })}
    />
  );
};

export default ListInput;
