import CredentialSubText from "@/lib/credentials/components/CredentialFields";
import { StringWithDescription } from "@/lib/connectors/connectors";
import { Field } from "formik";
import { useTranslations } from "next-intl";

export default function SelectInput({
  name,
  optional,
  description,
  options,
  label,
}: {
  name: string;
  optional?: boolean;
  description?: string;
  options: StringWithDescription[];
  label?: string;
}) {
  const t = useTranslations("admin.connectorsList");

  return (
    <>
      <label
        htmlFor={name}
        className="block text-sm font-medium text-text-700 mb-1"
      >
        {label}
        {optional && (
          <span className="text-text-500 ml-1">
            {t("field.optional.label")}
          </span>
        )}
      </label>
      {description && <CredentialSubText>{description}</CredentialSubText>}

      <Field
        as="select"
        name={name}
        className="w-full p-2 border border-border-03 rounded-08 bg-transparent text-text-04 focus:ring-2 focus:ring-lighter-agent focus:border-lighter-agent focus:outline-hidden"
      >
        <option value="">{t("selectInput.emptyOption.label")}</option>
        {options?.map((option: any) => (
          <option key={option.name} value={option.name}>
            {option.name}
          </option>
        ))}
      </Field>
    </>
  );
}
