import CredentialSubText from "@/lib/credentials/components/CredentialFields";
import type { StringWithDescription } from "@/lib/connectors/types";
import { InputSingleSelect } from "@opal/components";
import { useField } from "formik";
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
  const [field, , helpers] = useField<string>(name);

  return (
    <>
      <label
        htmlFor={name}
        className="block text-sm font-medium text-text-700 mb-1"
      >
        {label}
        {optional && (
          <span className="text-text-500 ms-1">
            {t("field.optional.label")}
          </span>
        )}
      </label>
      {description && <CredentialSubText>{description}</CredentialSubText>}

      <InputSingleSelect
        id={name}
        value={field.value ?? ""}
        onValueChange={(value) => {
          // The empty option is a choice here, as it was in the native select.
          void helpers.setValue(value);
          void helpers.setTouched(true, false);
        }}
        placeholder={t("selectInput.emptyOption.label")}
        options={[
          {
            options: options.map((option) => ({
              value: option.name,
              title: option.name,
            })),
          },
        ]}
      />
    </>
  );
}
