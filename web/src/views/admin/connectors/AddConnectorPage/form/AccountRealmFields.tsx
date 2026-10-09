"use client";

import { useTranslations } from "next-intl";
import { InputTypeIn } from "@opal/components";
import { InputVertical, Section } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { FormikField } from "@/refresh-components/form/FormikField";
import { useCredentialFieldCopy } from "@/lib/credentials/hooks";
import { getCredentialSpec } from "@/lib/credentials/utils";
import type { Credential, CredentialSpecField } from "@/lib/credentials/types";
import type { ValidSources } from "@/lib/connectors/types/source";
import { NEW_ACCOUNT_FIELD } from "@/views/admin/connectors/AddConnectorPage/newAccount";

interface AccountRealmFieldsProps {
  source: ValidSources;
  /** The source's realm fields (see `realmFields`). */
  fields: [string, CredentialSpecField][];
  /**
   * The saved account in use, if any. It brings its own realm, which the
   * fields then show, disabled.
   */
  savedCredential: Credential<any> | null;
}

/**
 * Where the account works (its site, host or subdomain), asked for first:
 * the account cannot be checked without it. The values belong to the typed
 * account, under NEW_ACCOUNT_FIELD. While a saved account is in use, the
 * fields show its realm and are disabled. The typed values stay, and come
 * back when the saved account is dropped.
 */
export default function AccountRealmFields({
  source,
  fields,
  savedCredential,
}: AccountRealmFieldsProps) {
  const t = useTranslations("admin.connectorsList.add.realm");
  const fieldCopy = useCredentialFieldCopy(source);
  const brandName: string = getCredentialSpec(source)?.brandName ?? source;

  return (
    <Section alignItems="stretch" gap={4}>
      {fields.map(([key, field]) => {
        const name = `${NEW_ACCOUNT_FIELD}.${key}`;
        const savedValue = savedCredential?.credential_json?.[key];
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
            {savedCredential ? (
              <InputTypeIn
                id={name}
                data-testid={key}
                value={typeof savedValue === "string" ? savedValue : ""}
                // An account without its own realm uses the default.
                placeholder={defaultValue}
                variant="disabled"
              />
            ) : (
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
            )}
          </InputVertical>
        );
      })}
    </Section>
  );
}
