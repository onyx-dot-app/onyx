"use client";

import { useTranslations } from "next-intl";
import { InputTypeIn } from "@opal/components";
import { InputVertical, Section } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { FormikField } from "@/refresh-components/form/FormikField";
import { useCredentialFieldCopy } from "@/lib/credentials/hooks";
import { getCredentialSpec } from "@/lib/credentials/utils";
import type { CredentialSpecField } from "@/lib/credentials/types";
import type { ValidSources } from "@/lib/connectors/types/source";
import { NEW_ACCOUNT_FIELD } from "@/views/admin/connectors/AddConnectorPage/newAccount";

interface AccountRealmFieldsProps {
  source: ValidSources;
  /** The source's realm fields (see `realmFields`). */
  fields: [string, CredentialSpecField][];
}

/**
 * Where the account works (its site, host or subdomain), asked for first:
 * the account cannot be checked without it. The values belong to the typed
 * account, under NEW_ACCOUNT_FIELD, and restrict the saved accounts below to
 * the ones that work there.
 */
export default function AccountRealmFields({
  source,
  fields,
}: AccountRealmFieldsProps) {
  const t = useTranslations("admin.connectorsList.add.realm");
  const fieldCopy = useCredentialFieldCopy(source);
  const brandName: string = getCredentialSpec(source)?.brandName ?? source;

  return (
    <Section alignItems="stretch" gap={4}>
      {fields.map(([key, field]) => {
        const name = `${NEW_ACCOUNT_FIELD}.${key}`;
        const defaultValue = field.optional ? field.defaultValue : undefined;
        return (
          <InputVertical
            key={key}
            withLabel={name}
            title={fieldCopy(key).title}
            suffix={field.optional ? "optional" : undefined}
            // Markdown, so the default renders as code.
            subDescription={markdown(
              t("description", {
                source: brandName,
                hasDefault: defaultValue ? "true" : "false",
                value: defaultValue ?? "",
              })
            )}
          >
            <FormikField<string>
              name={name}
              render={(formikField, _helper, _meta, status) => (
                <InputTypeIn
                  {...formikField}
                  id={name}
                  data-testid={key}
                  value={formikField.value ?? ""}
                  placeholder={defaultValue}
                  variant={status === "error" ? "error" : "primary"}
                />
              )}
            />
          </InputVertical>
        );
      })}
    </Section>
  );
}
