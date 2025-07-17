import React from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useFormikContext } from "formik";
import {
  BooleanFormField,
  TextFormField,
  TypedFileUploadFormField,
} from "@/components/Field";
import {
  getDisplayNameForCredentialKey,
  CredentialTemplateWithAuth,
} from "@/lib/connectors/credentials";
import { dictionaryType } from "../types";
import { isTypedFileField } from "@/lib/connectors/fileTypes";

interface CredentialFieldsRendererProps {
  credentialTemplate: dictionaryType;
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

  // remove other auth‐method fields when switching
  const handleAuthMethodChange = (newMethod: string) => {
    // start from current form values
    const cleaned = { ...values, authentication_method: newMethod };
    // delete every field not in the selected auth method
    templateWithAuth.authMethods?.forEach((m) => {
      if (m.value !== newMethod) {
        Object.keys(m.fields).forEach((fieldKey) => {
          delete cleaned[fieldKey];
        });
      }
    });
    setValues(cleaned);
    setAuthMethod?.(newMethod);
  };

  // Check if this credential template has multiple auth methods
  const hasMultipleAuthMethods =
    templateWithAuth.authMethods && templateWithAuth.authMethods.length > 1;

  if (hasMultipleAuthMethods && templateWithAuth.authMethods) {
    return (
      <div className="w-full space-y-4">
        {/* Render authentication_method as a hidden field */}
        <input
          type="hidden"
          name="authentication_method"
          value={authMethod || (templateWithAuth.authMethods?.[0]?.value ?? "")}
        />

        <Tabs
          value={authMethod || templateWithAuth.authMethods?.[0]?.value || ""}
          onValueChange={handleAuthMethodChange}
          className="w-full"
        >
          <TabsList
            className="grid w-full"
            style={{
              gridTemplateColumns: `repeat(${
                templateWithAuth.authMethods!.length
              }, minmax(0, 1fr))`,
            }}
          >
            {templateWithAuth.authMethods.map((method) => (
              <TabsTrigger key={method.value} value={method.value}>
                {method.label}
              </TabsTrigger>
            ))}
          </TabsList>

          {templateWithAuth.authMethods.map((method) => (
            <TabsContent
              key={method.value}
              value={method.value}
              className="space-y-4"
            >
              {/* Show description if method has no fields but has a description */}
              {Object.keys(method.fields).length === 0 &&
                method.description && (
                  <div className="p-4 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded-md">
                    <p className="text-sm text-blue-800 dark:text-blue-200">
                      {method.description}
                    </p>
                  </div>
                )}

              {Object.entries(method.fields).map(([key, val]) => {
                if (isTypedFileField(key)) {
                  return (
                    <TypedFileUploadFormField
                      key={key}
                      name={key}
                      label={getDisplayNameForCredentialKey(key)}
                    />
                  );
                }

                if (typeof val === "boolean") {
                  return (
                    <BooleanFormField
                      key={key}
                      name={key}
                      label={getDisplayNameForCredentialKey(key)}
                    />
                  );
                }
                return (
                  <TextFormField
                    key={key}
                    name={key}
                    placeholder={val}
                    label={getDisplayNameForCredentialKey(key)}
                    type={
                      key.toLowerCase().includes("token") ||
                      key.toLowerCase().includes("password") ||
                      key.toLowerCase().includes("secret")
                        ? "password"
                        : "text"
                    }
                  />
                );
              })}
            </TabsContent>
          ))}
        </Tabs>
      </div>
    );
  }

  // Render single auth method fields (existing behavior)
  return (
    <>
      {Object.entries(credentialTemplate).map(([key, val]) => {
        // Skip auth method metadata fields
        if (key === "authentication_method" || key === "authMethods") {
          return null;
        }
        if (isTypedFileField(key)) {
          return (
            <TypedFileUploadFormField
              key={key}
              name={key}
              label={getDisplayNameForCredentialKey(key)}
            />
          );
        }

        if (typeof val === "boolean") {
          return (
            <BooleanFormField
              key={key}
              name={key}
              label={getDisplayNameForCredentialKey(key)}
            />
          );
        }
        return (
          <TextFormField
            key={key}
            name={key}
            placeholder={val as string}
            label={getDisplayNameForCredentialKey(key)}
            type={
              key.toLowerCase().includes("token") ||
              key.toLowerCase().includes("password") ||
              key.toLowerCase().includes("secret")
                ? "password"
                : "text"
            }
          />
        );
      })}
    </>
  );
}
