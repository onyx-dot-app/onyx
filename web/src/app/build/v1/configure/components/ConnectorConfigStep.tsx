"use client";

import { useState } from "react";
import { Formik, Form, useFormikContext } from "formik";
import { Section } from "@/layouts/general-layouts";
import Button from "@/refresh-components/buttons/Button";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { ValidSources } from "@/lib/types";
import { Credential } from "@/lib/connectors/credentials";
import Separator from "@/refresh-components/Separator";
import {
  connectorConfigs,
  isLoadState,
  createConnectorInitialValues,
} from "@/lib/connectors/connectors";
import { createConnector } from "@/lib/connector";
import { linkCredential } from "@/lib/credential";
import CardSection from "@/components/admin/CardSection";
import { RenderField } from "@/app/admin/connectors/[connector]/pages/FieldRendering";

interface ConnectorConfigStepProps {
  connectorType: ValidSources;
  credential: Credential<any>;
  onSuccess: () => void;
  onBack: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
}

function ConnectorConfigForm({
  connectorType,
  credential,
  onSuccess,
  onBack,
  setPopup,
}: ConnectorConfigStepProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { values } = useFormikContext<Record<string, any>>();

  const config =
    connectorConfigs[connectorType as keyof typeof connectorConfigs];

  const handleSubmit = async () => {
    setIsSubmitting(true);

    try {
      const { connector_name, access_type, ...connectorConfig } = values;

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

      // Link credential to connector with file_system processing mode
      // Build mode connectors write documents to the file system for CLI agent access
      const linkResponse = await linkCredential(
        connector.id,
        credential.id,
        connector_name,
        "private",
        [], // No groups for build mode connectors
        undefined, // No auto sync options
        "file_system" // Use file system processing mode for build connectors
      );

      if (!linkResponse.ok) {
        const linkError = await linkResponse.json();
        throw new Error(linkError.detail || "Failed to link credential");
      }

      onSuccess();
    } catch (err) {
      setPopup({
        message:
          err instanceof Error ? err.message : "Failed to create connector",
        type: "error",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Check if there are any config fields to show
  const hasConfigFields = config?.values && config.values.length > 0;

  return (
    <Form className="w-full flex flex-col items-center">
      <CardSection className="flex flex-col gap-y-4">
        {hasConfigFields &&
          config.values.map((field) => (
            <RenderField
              key={field.name}
              field={field}
              values={values}
              connector={connectorType as any}
              currentCredential={credential}
            />
          ))}
        <Separator />
        {config?.advanced_values &&
          config.advanced_values.length > 0 &&
          config.advanced_values.map((field) => (
            <RenderField
              key={field.name}
              field={field}
              values={values}
              connector={connectorType as any}
              currentCredential={credential}
            />
          ))}
        <Section flexDirection="row" justifyContent="between" height="fit">
          <Button secondary onClick={onBack} disabled={isSubmitting}>
            Back
          </Button>
          <Button
            primary
            type="button"
            onClick={handleSubmit}
            disabled={isSubmitting}
          >
            {isSubmitting ? "Creating..." : "Create Connector"}
          </Button>
        </Section>
      </CardSection>
    </Form>
  );
}

export default function ConnectorConfigStep({
  connectorType,
  credential,
  onSuccess,
  onBack,
  setPopup,
}: ConnectorConfigStepProps) {
  // Build initial values using the shared utility
  const baseInitialValues = createConnectorInitialValues(connectorType as any);
  const initialValues: Record<string, any> = {
    ...baseInitialValues,
    connector_name: `build-mode-${connectorType}`,
  };

  return (
    <Formik
      initialValues={initialValues}
      onSubmit={() => {}}
      enableReinitialize
    >
      <ConnectorConfigForm
        connectorType={connectorType}
        credential={credential}
        onSuccess={onSuccess}
        onBack={onBack}
        setPopup={setPopup}
      />
    </Formik>
  );
}
