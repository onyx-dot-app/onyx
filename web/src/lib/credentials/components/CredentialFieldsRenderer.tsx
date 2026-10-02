"use client";

import {
  InputPasswordTypeIn,
  InputSwitch,
  InputTypeIn,
  MessageCard,
  Tabs,
} from "@opal/components";
import { InputHorizontal, InputVertical, Section } from "@opal/layouts";
import { useFormikContext } from "formik";
import { useTranslations } from "next-intl";
import { TypedFileUploadFormField } from "@/components/Field";
import { FormikField } from "@/refresh-components/form/FormikField";
import { useCredentialFieldCopy } from "@/lib/credentials/hooks";
import type { CredentialTemplateWithAuth } from "@/lib/credentials/types";
import { isTypedFileField } from "@/lib/connectors/utils";
import type {
  CredentialFieldValue,
  CredentialFieldValues,
} from "@/lib/credentials/types";

/** Whether a credential key holds an email address. */
function isEmailKey(key: string): boolean {
  return key.toLowerCase().includes("email");
}

/** Whether a credential key holds a secret, so its input masks the value. */
function isSecretKey(key: string): boolean {
  const lower = key.toLowerCase();
  return (
    lower.includes("token") ||
    lower.includes("password") ||
    lower.includes("secret")
  );
}

interface CredentialFieldProps {
  fieldKey: string;
  value: CredentialFieldValue;
}

/** One field of a credential template, drawn with the Opal input for its type. */
function CredentialField({ fieldKey, value }: CredentialFieldProps) {
  const t = useTranslations("admin");
  const isEmail = isEmailKey(fieldKey);
  const copy = useCredentialFieldCopy()(fieldKey);
  const label = copy.title;

  // A file such as a .pfx key is binary; Opal's InputFile reads text, so
  // this field keeps the typed upload until Opal can hand back a File.
  if (isTypedFileField(fieldKey)) {
    return <TypedFileUploadFormField name={fieldKey} label={label} />;
  }

  if (typeof value === "boolean") {
    return (
      <InputHorizontal withLabel={fieldKey} title={label}>
        <FormikField<boolean>
          name={fieldKey}
          render={(field, helper) => (
            <InputSwitch
              checked={!!field.value}
              onCheckedChange={(checked) => helper.setValue(checked)}
            />
          )}
        />
      </InputHorizontal>
    );
  }

  // An email field shows an example address; any other field shows its
  // template's placeholder, if it has one.
  const placeholder = isEmail
    ? t("credentials.create.emailField.placeholder")
    : typeof value === "string" && value !== ""
      ? value
      : undefined;

  return (
    <InputVertical withLabel={fieldKey} title={label}>
      <FormikField<string>
        name={fieldKey}
        render={(field, _helper, _meta, status) =>
          isSecretKey(fieldKey) ? (
            <InputPasswordTypeIn
              {...field}
              value={field.value ?? ""}
              placeholder={placeholder}
              error={status === "error"}
            />
          ) : (
            <InputTypeIn
              {...field}
              value={field.value ?? ""}
              placeholder={placeholder}
              variant={status === "error" ? "error" : "primary"}
            />
          )
        }
      />
    </InputVertical>
  );
}

interface CredentialFieldsRendererProps {
  credentialTemplate: CredentialFieldValues;
  authMethod?: string;
  setAuthMethod?: (method: string) => void;
}

export function CredentialFieldsRenderer({
  credentialTemplate,
  authMethod,
  setAuthMethod,
}: CredentialFieldsRendererProps) {
  const templateWithAuth =
    credentialTemplate as CredentialTemplateWithAuth<any>;
  const { values, setValues } = useFormikContext<any>();

  // Switching auth method drops the other methods' fields from the values.
  function handleAuthMethodChange(newMethod: string) {
    const cleaned = { ...values, authentication_method: newMethod };
    templateWithAuth.authMethods?.forEach((method) => {
      if (method.value !== newMethod) {
        Object.keys(method.fields).forEach((fieldKey) => {
          delete cleaned[fieldKey];
        });
      }
    });
    setValues(cleaned);
    setAuthMethod?.(newMethod);
  }

  const authMethods = templateWithAuth.authMethods;
  if (authMethods && authMethods.length > 1) {
    return (
      <Tabs
        value={authMethod || authMethods[0]?.value || ""}
        onValueChange={handleAuthMethodChange}
      >
        <Tabs.List>
          {authMethods.map((method) => (
            <Tabs.Trigger key={method.value} value={method.value}>
              {method.label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        {authMethods.map((method) => (
          <Tabs.Content key={method.value} value={method.value}>
            <Section alignItems="stretch" gap={4}>
              {/* A method with nothing to fill in explains itself instead. */}
              {Object.keys(method.fields).length === 0 &&
                method.description && (
                  <MessageCard variant="info" title={method.description} />
                )}
              {Object.entries(method.fields).map(([key, value]) => (
                <CredentialField
                  key={key}
                  fieldKey={key}
                  value={value as CredentialFieldValue}
                />
              ))}
            </Section>
          </Tabs.Content>
        ))}
      </Tabs>
    );
  }

  return (
    <>
      {Object.entries(credentialTemplate).map(([key, value]) =>
        // Auth-method metadata is not a field.
        key === "authentication_method" || key === "authMethods" ? null : (
          <CredentialField key={key} fieldKey={key} value={value} />
        )
      )}
    </>
  );
}
