"use client";

import { useTranslations } from "next-intl";
import { InputTypeIn } from "@opal/components";
import { InputVertical } from "@opal/layouts";
import { FormikField } from "@/refresh-components/form/FormikField";

interface AccountNameFieldProps {
  /** The Formik path of the name, e.g. `name` or `new_account.name`. */
  name: string;
}

/** A new account's optional display name. Left blank, it shows as "Untitled". */
export function AccountNameField({ name }: AccountNameFieldProps) {
  const t = useTranslations("admin.credentials.create");
  return (
    <InputVertical
      withLabel={name}
      title={t("nameField.title")}
      suffix="optional"
    >
      <FormikField<string>
        name={name}
        render={(formikField) => (
          <InputTypeIn
            {...formikField}
            id={name}
            value={formikField.value ?? ""}
            placeholder={t("nameField.placeholder")}
          />
        )}
      />
    </InputVertical>
  );
}
