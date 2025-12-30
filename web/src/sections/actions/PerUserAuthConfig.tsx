"use client";

import { useEffect, useState } from "react";
import { FormField } from "@/refresh-components/form/FormField";
import InputKeyValue, {
  KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";
import Separator from "@/refresh-components/Separator";
import type { MCPAuthFormValues } from "@/sections/actions/modals/MCPAuthenticationModal";
import { SvgUser } from "@opal/icons";

interface PerUserAuthConfigProps {
  values: MCPAuthFormValues;
  setFieldValue: (
    field: keyof MCPAuthFormValues | string,
    value: unknown
  ) => void;
}

export function PerUserAuthConfig({
  values,
  setFieldValue,
}: PerUserAuthConfigProps) {
  // Use draft state for KeyValue array (like in LLMConnectionFieldsCustom)
  const [headersDraft, setHeadersDraft] = useState<KeyValue[]>(
    Object.entries(values.auth_template?.headers || {}).map(([key, value]) => ({
      key,
      value: String(value),
    }))
  );

  // Initialize auth template if not exists
  useEffect(() => {
    if (!values.auth_template) {
      const initialHeaders = { Authorization: "Bearer {api_key}" };
      setFieldValue("auth_template", {
        headers: initialHeaders,
        required_fields: ["api_key"],
      });
      setHeadersDraft([{ key: "Authorization", value: "Bearer {api_key}" }]);
    }
  }, [values.auth_template, setFieldValue]);

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
  const userCredentials = values.user_credentials || {};

  return (
    <div className="flex flex-col gap-4 -mx-2 px-2 py-2 bg-background-tint-00 rounded-12">
      {/* Authentication Headers */}
      <FormField name="auth_template.headers" state="idle">
        <FormField.Label>Authentication Headers</FormField.Label>
        <FormField.Control asChild>
          <InputKeyValue
            keyTitle="Header Name"
            valueTitle="Header Value"
            items={headersDraft}
            onChange={handleHeadersChange}
            mode="fixed-line"
            layout="equal"
            addButtonLabel="Add Header"
          />
        </FormField.Control>
        <FormField.Description>
          Format headers for each user to fill in their individual credentials.
          Use placeholders like{" "}
          <Text text03 secondaryMono className="inline" as="span">
            {"{api_key}"}
          </Text>{" "}
          or{" "}
          <Text text03 secondaryMono className="inline" as="span">
            {"{user_email}"}
          </Text>
          . Users will be prompted to provide values for placeholders (except
          user_email).
        </FormField.Description>
      </FormField>

      {/* Only show user credentials section if there are required fields */}
      {requiredFields.length > 0 && (
        <>
          <Separator className="-my-2" />

          <div className="flex flex-col gap-4">
            <div className="flex items-start gap-1">
              <SvgUser className="w-4 h-4 stroke-text-04 mt-0.5" />
              <div className="flex flex-col gap-1">
                <Text text04 secondaryAction as="p">
                  Only for your own account
                </Text>
                <Text text03 secondaryBody as="p">
                  The following credentials will not be shared with your
                  organization.
                </Text>
              </div>
            </div>

            {/* User Credentials Fields */}
            <div className="flex flex-col gap-3">
              {requiredFields.map((field: string) => {
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
                        placeholder={`Enter ${field.replace(/_/g, " ")}`}
                        showClearButton={false}
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
