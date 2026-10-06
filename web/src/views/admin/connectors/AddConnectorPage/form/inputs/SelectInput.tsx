import { useTranslations } from "next-intl";
import { InputSingleSelectField } from "@opal/form";
import { markdown } from "@opal/utils";
import { InputVertical } from "@opal/layouts";
import type { StringWithDescription } from "@/lib/connectors/types";

interface SelectInputProps {
  name: string;
  label: string;
  description?: string;
  optional?: boolean;
  disabled?: boolean;
  options: StringWithDescription[];
}

/** A single choice from a fixed list of options. */
export default function SelectInput({
  name,
  label,
  description,
  optional,
  disabled,
  options,
}: SelectInputProps) {
  const t = useTranslations("admin.connectorsList.selectInput");

  return (
    // The field name ties the label to the select's id and shows the field's
    // Formik error under it.
    <InputVertical
      withLabel={name}
      disabled={disabled}
      title={label}
      subDescription={description ? markdown(description) : undefined}
      suffix={optional ? "optional" : undefined}
    >
      <InputSingleSelectField
        name={name}
        id={name}
        placeholder={t("emptyOption.label")}
        disabled={disabled}
        options={[
          {
            options: options.map((option) => ({
              value: option.name,
              title: option.name,
            })),
          },
        ]}
      />
    </InputVertical>
  );
}
