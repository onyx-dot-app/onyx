"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { FormField } from "@/refresh-components/form/FormField";
import InputKeyValue, {
  KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import { InputTypeIn } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { Divider } from "@opal/components";
import type { MCPAuthFormValues } from "@/sections/actions/modals/MCPAuthenticationModal";
import { MCPAuthenticationType } from "@/lib/tools/types";
import { SvgUser } from "@opal/icons";

// Rendered verbatim inside the help copy. Kept as ICU arguments so the braces
// are not parsed as message placeholders.
const API_KEY_PLACEHOLDER = "{api_key}";
const USER_EMAIL_PLACEHOLDER = "{user_email}";

interface PerUserAuthConfigProps {
  values: MCPAuthFormValues;
  setFieldValue: (
    field: keyof MCPAuthFormValues | string,
    value: unknown
  ) => void;
  mode?: "per-user" | "shared";
}

export function PerUserAuthConfig({
  values,
  setFieldValue,
  mode = "per-user",
}: PerUserAuthConfigProps) {
  const t = useTranslations("actions");

  // Use draft state for KeyValue array (like in LLMConnectionFieldsCustom)
  const [headersDraft, setHeadersDraft] = useState<KeyValue[]>(
    Object.entries(values.auth_template?.headers || {}).map(([key, value]) => ({
      key,
      value: String(value),
    }))
  );

  // API-token setup keeps its existing bearer default.
  useEffect(() => {
    if (
      values.auth_type === MCPAuthenticationType.API_TOKEN &&
      Object.keys(values.auth_template?.headers || {}).length === 0
    ) {
      const initialHeaders = { Authorization: "Bearer {api_key}" };
      setFieldValue("auth_template", {
        headers: initialHeaders,
        required_fields: ["api_key"],
      });
      setHeadersDraft([{ key: "Authorization", value: "Bearer {api_key}" }]);
    }
  }, [values.auth_template, values.auth_type, setFieldValue]);

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
    setFieldValue("auth_template.headers", headersObject);
    updateRequiredFields(headersObject);
  };

  const computeRequiredFieldsFromHeaders = (
    headers: Record<string, string>
  ): string[] => {
    const placeholderRegex = /\{([^}]+)\}/g;
    const requiredFields = new Set<string>();

    Object.values(headers).forEach((value) => {
      const matches = value.match(placeholderRegex);
      if (matches) {
        matches.forEach((match: string) => {
          const field = match.slice(1, -1);
          if (field !== "user_email") {
            // user_email is automatically provided
            requiredFields.add(field);
          }
        });
      }
    });
    return Array.from(requiredFields);
  };

  // Extract required fields from placeholders in header values
  const updateRequiredFields = (headers: Record<string, string>) => {
    const requiredFields = computeRequiredFieldsFromHeaders(headers);
    setFieldValue("auth_template.required_fields", requiredFields);
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
    : computeRequiredFieldsFromHeaders(values.auth_template?.headers || {});
  const credentialFields =
    mode === "shared"
      ? requiredFields.filter((field) => field !== "api_key")
      : requiredFields;
  const userCredentials = values.user_credentials || {};

  // Shared templates must render the org's single shared key, so at least one
  // header value has to contain `{api_key}`. Surface this inline rather than
  // relying on the backend validator's generic toast.
  const hasApiKeyPlaceholder = Object.values(
    values.auth_template?.headers || {}
  ).some((value) => typeof value === "string" && value.includes("{api_key}"));
  const missingSharedApiKey = mode === "shared" && !hasApiKeyPlaceholder;

  return (
    <div className="flex flex-col gap-4 -mx-2 px-2 py-2 bg-background-tint-00 rounded-12">
      {/* Authentication Headers */}
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
                  <Text text03 secondaryMono className="inline">
                    {chunks}
                  </Text>
                ),
              })
            : t.rich("perUserAuth.headers.sharedDescription", {
                apiKey: API_KEY_PLACEHOLDER,
                mono: (chunks) => (
                  <Text text03 secondaryMono className="inline">
                    {chunks}
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

      {credentialFields.length > 0 && (
        <>
          <Divider paddingParallel={0} paddingPerpendicular={0} />

          <div className="flex flex-col gap-4">
            <div className="flex items-start gap-1">
              <SvgUser className="w-4 h-4 stroke-text-04 mt-0.5" />
              <div className="flex flex-col gap-1">
                <Text text04 secondaryAction as="p">
                  {mode === "per-user"
                    ? t("perUserAuth.credentials.perUserTitle")
                    : t("perUserAuth.credentials.sharedTitle")}
                </Text>
                <Text text03 secondaryBody as="p">
                  {mode === "per-user"
                    ? t("perUserAuth.credentials.perUserDescription")
                    : t("perUserAuth.credentials.sharedDescription")}
                </Text>
              </div>
            </div>

            {/* User Credentials Fields */}
            <div className="flex flex-col gap-3">
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
                    state="idle"
                  >
                    <FormField.Label>
                      {field
                        .replace(/_/g, " ")
                        .replace(/\b\w/g, (l) => l.toUpperCase())}
                    </FormField.Label>
                    <FormField.Control asChild>
                      <InputTypeIn
                        name={`user_credentials.${field}`}
                        type={isSecretField ? "password" : "text"}
                        value={userCredentials[field] || ""}
                        onChange={(e) =>
                          updateUserCredential(field, e.target.value)
                        }
                        placeholder={t(
                          "perUserAuth.credentialField.placeholder",
                          {
                            field: field.replace(/_/g, " "),
                          }
                        )}
                      />
                    </FormField.Control>
                  </FormField>
                );
              })}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
