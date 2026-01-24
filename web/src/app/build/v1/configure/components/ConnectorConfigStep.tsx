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
  createConnectorInitialValues,
} from "@/lib/connectors/connectors";
import CardSection from "@/components/admin/CardSection";
import { RenderField } from "@/app/admin/connectors/[connector]/pages/FieldRendering";
import { createBuildConnector } from "@/app/build/v1/configure/utils/createBuildConnector";
import { useUser } from "@/components/user/UserProvider";

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
  const { user } = useUser();

  const config =
    connectorConfigs[connectorType as keyof typeof connectorConfigs];

  const handleSubmit = async () => {
    setIsSubmitting(true);

    try {
      // Extract connector_name and exclude access_type/groups (these are top-level fields)
      const { connector_name, access_type, groups, ...connectorConfig } =
        values;

      const result = await createBuildConnector({
        connectorType,
        credential,
        connectorSpecificConfig: connectorConfig,
        connectorName: connector_name,
        userEmail: user?.email,
      });

      if (!result.success) {
        throw new Error(result.error);
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

function getUserIdentifier(email?: string): string {
  if (!email) return "";
  const prefix = email.split("@")[0] || email;
  return `-${prefix.replace(/[^a-zA-Z0-9]/g, "-")}`;
}

export default function ConnectorConfigStep({
  connectorType,
  credential,
  onSuccess,
  onBack,
  setPopup,
}: ConnectorConfigStepProps) {
  const { user } = useUser();
  const baseInitialValues = createConnectorInitialValues(connectorType as any);
  const userIdentifier = getUserIdentifier(user?.email);
  const initialValues: Record<string, any> = {
    ...baseInitialValues,
    connector_name: `build-mode-${connectorType}${userIdentifier}`,
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
