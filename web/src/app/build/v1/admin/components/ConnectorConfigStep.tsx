"use client";

import { useState } from "react";
import { Formik, Form } from "formik";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { TextFormField, BooleanFormField } from "@/components/Field";
import { ValidSources } from "@/lib/types";
import { Credential } from "@/lib/connectors/credentials";
import { connectorConfigs, isLoadState } from "@/lib/connectors/connectors";
import { createConnector } from "@/lib/connector";
import { linkCredential } from "@/lib/credential";
import { getSourceMetadata } from "@/lib/sources";

interface ConnectorConfigStepProps {
  connectorType: ValidSources;
  credential: Credential<any>;
  onSuccess: () => void;
  onBack: () => void;
}

export default function ConnectorConfigStep({
  connectorType,
  credential,
  onSuccess,
  onBack,
}: ConnectorConfigStepProps) {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const sourceMetadata = getSourceMetadata(connectorType);
  const config =
    connectorConfigs[connectorType as keyof typeof connectorConfigs];

  // Build initial values from config
  const initialValues: Record<string, any> = {
    connector_name:
      credential.name || `${sourceMetadata.displayName} Connector`,
  };

  // Add fields from config values (not advanced_values for Build mode)
  if (config?.values) {
    config.values.forEach((field) => {
      if (field.type === "text") {
        initialValues[field.name] = field.default || "";
      } else if (field.type === "checkbox") {
        initialValues[field.name] = field.default || false;
      } else if (field.type === "list") {
        initialValues[field.name] = field.default || [];
      } else if (field.type === "multiselect") {
        initialValues[field.name] = field.default || [];
      } else if (field.type === "select") {
        initialValues[field.name] = field.default || "";
      } else if (field.type === "number") {
        initialValues[field.name] = field.default || "";
      }
      // Skip tab fields for now - they're complex
    });
  }

  const handleSubmit = async (values: Record<string, any>) => {
    setIsSubmitting(true);
    setError(null);

    try {
      const { connector_name, ...connectorConfig } = values;

      // Filter out empty values
      const filteredConfig: Record<string, any> = {};
      Object.entries(connectorConfig).forEach(([key, value]) => {
        if (value !== "" && value !== null && value !== undefined) {
          if (Array.isArray(value) && value.length === 0) {
            return; // Skip empty arrays
          }
          filteredConfig[key] = value;
        }
      });

      // Create connector
      const [connectorError, connector] = await createConnector({
        name: connector_name,
        source: connectorType,
        input_type: isLoadState(connectorType) ? "load_state" : "poll",
        connector_specific_config: filteredConfig,
        refresh_freq: config?.overrideDefaultFreq || 1800, // 30 minutes default
        prune_freq: 2592000, // 30 days default
        indexing_start: null,
        access_type: "private",
      });

      if (connectorError || !connector) {
        throw new Error(connectorError || "Failed to create connector");
      }

      // Link credential to connector
      const linkResponse = await linkCredential(
        connector.id,
        credential.id,
        connector_name,
        "private"
      );

      if (!linkResponse.ok) {
        const linkError = await linkResponse.json();
        throw new Error(linkError.detail || "Failed to link credential");
      }

      onSuccess();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to create connector"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  // Check if there are any config fields to show
  const hasConfigFields = config?.values && config.values.length > 0;

  return (
    <Formik initialValues={initialValues} onSubmit={handleSubmit}>
      {({ isValid }) => (
        <Form>
          <Section gap={1} alignItems="stretch" height="fit">
            <Text mainUiBody>Configure {sourceMetadata.displayName}</Text>

            <TextFormField
              name="connector_name"
              label="Connector Name"
              placeholder={`My ${sourceMetadata.displayName} Connector`}
              type="text"
            />

            {hasConfigFields ? (
              config.values.map((field) => {
                // Only render simple field types
                if (field.type === "text") {
                  return (
                    <TextFormField
                      key={field.name}
                      name={field.name}
                      label={field.label as string}
                      placeholder={field.query || ""}
                      subtext={
                        typeof field.description === "string"
                          ? field.description
                          : undefined
                      }
                    />
                  );
                }

                if (field.type === "checkbox") {
                  return (
                    <BooleanFormField
                      key={field.name}
                      name={field.name}
                      label={field.label as string}
                      subtext={field.description as string | undefined}
                    />
                  );
                }

                // Skip complex field types (tab, list, multiselect) for now
                // They would require more complex UI components
                return null;
              })
            ) : (
              <Text secondaryBody text03>
                No additional configuration needed for{" "}
                {sourceMetadata.displayName}.
              </Text>
            )}

            {error && (
              <Text secondaryBody className="text-red-500">
                {error}
              </Text>
            )}

            <Section flexDirection="row" justifyContent="between" height="fit">
              <Button action secondary onClick={onBack} disabled={isSubmitting}>
                Back
              </Button>
              <Button action primary type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Creating..." : "Create Connector"}
              </Button>
            </Section>
          </Section>
        </Form>
      )}
    </Formik>
  );
}
