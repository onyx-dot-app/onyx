"use client";

import { useFormikContext } from "formik";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { FormField } from "@/refresh-components/form/FormField";
import { InputKeyValue, type KeyValue } from "@opal/components";
import { InputTypeIn } from "@opal/components";
import { Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { richNodes } from "@opal/utils";
import type { MCPAuthFormValues } from "@/views/admin/PluginsPage/components/mcp/types";
import { getRequiredHeaderFields } from "@/views/admin/PluginsPage/components/mcp/mcpAuthForm";

// Rendered verbatim inside the help copy. Kept as ICU arguments so the braces
// are not parsed as message placeholders.
const API_KEY_PLACEHOLDER = "{api_key}";
const USER_EMAIL_PLACEHOLDER = "{user_email}";

interface PerUserAuthConfigProps {
  values: MCPAuthFormValues;
  setFieldValue: (
    field: keyof MCPAuthFormValues | string,
    value: MCPAuthFormValues[keyof MCPAuthFormValues] | string[]
  ) => void;
  mode?: "per-user" | "shared";
  section: "credentials" | "headers";
}

export function PerUserAuthConfig({
  values,
  setFieldValue,
  mode = "per-user",
  section,
}: PerUserAuthConfigProps) {
  const t = useTranslations("actions");
  const { errors } = useFormikContext<MCPAuthFormValues>();

  // Use draft state for KeyValue array (like in LLMConnectionFieldsCustom)
  const [headersDraft, setHeadersDraft] = useState<KeyValue[]>(
    Object.entries(values.auth_template?.headers || {}).map(([key, value]) => ({
      key,
      value: String(value),
    }))
  );

  // Update headers from KeyValue array
  const handleHeadersChange = (items: KeyValue[]) => {
    // Update draft state first
    setHeadersDraft(items);

    // Convert KeyValue[] to Record<string, string> for form value
    const headersObject: Record<string, string> = {};
    items.forEach((item) => {
      if (item.key.trim()) {
        headersObject[item.key] = item.value;
      }
    });
    setFieldValue("auth_template", {
      headers: headersObject,
      required_fields: getRequiredHeaderFields(headersObject),
    });
  };

  // Update user credential value
  const updateUserCredential = (field: string, value: string) => {
    const currentCreds = values.user_credentials || {};
    setFieldValue("user_credentials", {
      ...currentCreds,
      [field]: value,
    });
  };

  const requiredFields: string[] = values.auth_template?.required_fields?.length
    ? values.auth_template.required_fields
    : getRequiredHeaderFields(values.auth_template?.headers || {});
  const credentialFields =
    mode === "shared"
      ? requiredFields.filter((field) => field !== "api_key")
      : requiredFields;
  const credentialHelpField = credentialFields.includes("api_key")
    ? "api_key"
    : credentialFields[0];
  const userCredentials = values.user_credentials || {};

  // Shared templates must render the org's single shared key, so at least one
  // header value has to contain `{api_key}`. Surface this inline rather than
  // relying on the backend validator's generic toast.
  const hasApiKeyPlaceholder = Object.values(
    values.auth_template?.headers || {}
  ).some((value) => typeof value === "string" && value.includes("{api_key}"));
  const missingSharedApiKey = mode === "shared" && !hasApiKeyPlaceholder;

  if (section === "credentials" && credentialFields.length === 0) return null;

  return (
    <Section gap={4} alignItems="stretch" height="auto">
      {section === "credentials" && credentialFields.length > 0 && (
        <Section gap={3} alignItems="stretch" height="auto">
          {credentialFields.map((field: string) => {
            const isSecretField =
              field.toLowerCase().includes("key") ||
              field.toLowerCase().includes("token") ||
              field.toLowerCase().includes("secret") ||
              field.toLowerCase().includes("password");

            return (
              <FormField
                key={field}
                name={`user_credentials.${field}`}
                state={errors.user_credentials?.[field] ? "error" : "idle"}
              >
                <FormField.Label>
                  {field === "api_key"
                    ? t("mcpAuthModal.sharedApiKey.label")
                    : field
                        .replace(/_/g, " ")
                        .replace(/\b\w/g, (l) => l.toUpperCase())}
                </FormField.Label>
                {field === credentialHelpField && (
                  <FormField.Description>
                    {mode === "per-user"
                      ? t("perUserAuth.credentials.perUserDescription")
                      : t("perUserAuth.credentials.sharedDescription")}
                  </FormField.Description>
                )}
                <FormField.Control asChild>
                  <InputTypeIn
                    name={`user_credentials.${field}`}
                    type={isSecretField ? "password" : "text"}
                    value={userCredentials[field] || ""}
                    onChange={(e) =>
                      updateUserCredential(field, e.target.value)
                    }
                    placeholder={t("perUserAuth.credentialField.placeholder", {
                      field:
                        field === "api_key"
                          ? t("mcpAuthModal.sharedApiKey.label")
                          : field.replace(/_/g, " "),
                    })}
                  />
                </FormField.Control>
                <FormField.Message
                  messages={{ error: errors.user_credentials?.[field] }}
                />
              </FormField>
            );
          })}
        </Section>
      )}
      {section === "headers" && (
        <FormField
          name="auth_template.headers"
          state={missingSharedApiKey ? "error" : "idle"}
        >
          <FormField.Label>{t("perUserAuth.headers.label")}</FormField.Label>
          <FormField.Control asChild>
            <InputKeyValue
              keyTitle={t("perUserAuth.headers.keyTitle")}
              valueTitle={t("perUserAuth.headers.valueTitle")}
              items={headersDraft}
              onChange={handleHeadersChange}
              mode="fixed-line"
              layout="equal"
              addButtonLabel={t("perUserAuth.headers.addButton.label")}
            />
          </FormField.Control>
          <FormField.Description>
            {mode === "per-user"
              ? t.rich("perUserAuth.headers.perUserDescription", {
                  apiKey: API_KEY_PLACEHOLDER,
                  userEmail: USER_EMAIL_PLACEHOLDER,
                  mono: (chunks) => (
                    <Text color="text-03" font="secondary-mono">
                      {richNodes(chunks)}
                    </Text>
                  ),
                })
              : t.rich("perUserAuth.headers.sharedDescription", {
                  apiKey: API_KEY_PLACEHOLDER,
                  mono: (chunks) => (
                    <Text color="text-03" font="secondary-mono">
                      {richNodes(chunks)}
                    </Text>
                  ),
                })}
          </FormField.Description>
          <FormField.Message
            messages={{
              error: t("perUserAuth.headers.error.message", {
                apiKey: API_KEY_PLACEHOLDER,
              }),
            }}
          />
        </FormField>
      )}
    </Section>
  );
}
