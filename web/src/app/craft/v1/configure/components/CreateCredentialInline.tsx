"use client";

import { useState } from "react";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { TextFormField } from "@/components/Field";
import { ValidSources } from "@/lib/types";
import {
  Credential,
  credentialTemplates,
  getDisplayNameForCredentialKey,
} from "@/lib/connectors/credentials";
import { createCredential } from "@/lib/credential";
import { getSourceMetadata } from "@/lib/sources";

interface CreateCredentialInlineProps {
  connectorType: ValidSources;
  onSuccess: (credential: Credential<any>) => void;
  onCancel: () => void;
}

export default function CreateCredentialInline({
  connectorType,
  onSuccess,
  onCancel,
}: CreateCredentialInlineProps) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const sourceMetadata = getSourceMetadata(connectorType);
  const credentialTemplate = credentialTemplates[connectorType];

  if (!credentialTemplate) {
    return (
      <Section gap={0.5} alignItems="center" height="fit">
        <Text secondaryBody text03>
          No credential configuration available for {sourceMetadata.displayName}
          .
        </Text>
        <Button action secondary onClick={onCancel}>
          Cancel
        </Button>
      </Section>
    );
  }

  // Build initial values and validation schema from template
  const initialValues: Record<string, string> = {};
  const schemaFields: Record<string, Yup.StringSchema> = {};

  // Filter out metadata fields and build form config
  Object.entries(credentialTemplate).forEach(([key, value]) => {
    if (key === "authentication_method" || key === "authMethods") {
      return;
    }
    initialValues[key] = typeof value === "string" ? value : "";
    schemaFields[key] = Yup.string().required(
      `${getDisplayNameForCredentialKey(key)} is required`
    );
  });

  // Add credential name field
  initialValues["credential_name"] = "";

  const validationSchema = Yup.object().shape(schemaFields);

  const handleSubmit = async (values: Record<string, string>) => {
    setIsSubmitting(true);
    setError(null);

    try {
      // Extract credential name and build credential_json
      const { credential_name, ...credentialFields } = values;

      const response = await createCredential({
        credential_json: credentialFields,
        admin_public: false,
        source: connectorType,
        name: credential_name || `${sourceMetadata.displayName} Credential`,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Failed to create credential");
      }

      const credential = await response.json();
      onSuccess(credential);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to create credential"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={handleSubmit}
    >
      {({ isValid, dirty }) => (
        <Form>
          <Section gap={1} alignItems="stretch" height="fit">
            <TextFormField
              name="credential_name"
              label="Credential Name"
              placeholder={`My ${sourceMetadata.displayName} Credential`}
              type="text"
            />

            {Object.entries(credentialTemplate).map(([key, value]) => {
              // Skip metadata fields
              if (key === "authentication_method" || key === "authMethods") {
                return null;
              }

              const isSecret =
                key.toLowerCase().includes("token") ||
                key.toLowerCase().includes("password") ||
                key.toLowerCase().includes("secret") ||
                key.toLowerCase().includes("key");

              return (
                <TextFormField
                  key={key}
                  name={key}
                  label={getDisplayNameForCredentialKey(key)}
                  placeholder={typeof value === "string" ? value : ""}
                  type={isSecret ? "password" : "text"}
                />
              );
            })}

            {error && (
              <Text secondaryBody className="text-status-error-05">
                {error}
              </Text>
            )}

            <Section
              flexDirection="row"
              justifyContent="end"
              gap={0.5}
              height="fit"
            >
              <Button
                action
                secondary
                onClick={onCancel}
                disabled={isSubmitting}
              >
                Cancel
              </Button>
              <Button
                action
                primary
                type="submit"
                disabled={!isValid || !dirty || isSubmitting}
              >
                {isSubmitting ? "Creating..." : "Create Credential"}
              </Button>
            </Section>
          </Section>
        </Form>
      )}
    </Formik>
  );
}
