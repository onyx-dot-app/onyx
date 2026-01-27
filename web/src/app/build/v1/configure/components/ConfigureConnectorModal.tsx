"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import Modal from "@/refresh-components/Modal";
import { ValidSources, ConfigurableSources } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import { SvgPlug } from "@opal/icons";
import { Credential, credentialTemplates } from "@/lib/connectors/credentials";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import CredentialStep from "@/app/build/v1/configure/components/CredentialStep";
import ConnectorConfigStep from "@/app/build/v1/configure/components/ConnectorConfigStep";
import { usePopup } from "@/components/admin/connectors/Popup";
import { OAUTH_STATE_KEY } from "@/app/build/v1/constants";
import { connectorConfigs } from "@/lib/connectors/connectors";

type ModalStep = "credential" | "configure";

function connectorNeedsCredentials(connectorType: ValidSources): boolean {
  return credentialTemplates[connectorType] != null;
}

function connectorNeedsConfigStep(connectorType: ValidSources): boolean {
  const config = connectorConfigs[connectorType as ConfigurableSources];
  if (!config) return false;

  // Only check main values, not advanced_values
  // Advanced values are optional configuration and shouldn't force a 2-step flow
  const hasVisibleValues = config.values.some(
    (field) => !("hidden" in field && field.hidden)
  );

  return hasVisibleValues;
}

interface ConfigureConnectorModalProps {
  connectorType: ValidSources | null;
  existingConfig: unknown | null;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export default function ConfigureConnectorModal({
  connectorType,
  existingConfig,
  open,
  onClose,
  onSuccess,
}: ConfigureConnectorModalProps) {
  const { popup, setPopup } = usePopup();
  const [step, setStep] = useState<ModalStep>("credential");
  const [selectedCredential, setSelectedCredential] =
    useState<Credential<any> | null>(null);

  const sourceMetadata = connectorType
    ? getSourceMetadata(connectorType)
    : null;
  const isConfigured = !!existingConfig;

  const needsCredentials = connectorType
    ? connectorNeedsCredentials(connectorType)
    : true;
  const needsConfigStep = connectorType
    ? connectorNeedsConfigStep(connectorType)
    : false;
  const isSingleStep = needsCredentials && !needsConfigStep;

  // Fetch credentials for this connector type
  const { data: credentials, mutate: refreshCredentials } = useSWR<
    Credential<any>[]
  >(
    connectorType && open && !isConfigured
      ? buildSimilarCredentialInfoURL(connectorType)
      : null,
    errorHandlingFetcher
  );

  useEffect(() => {
    if (open && !isConfigured) {
      setStep("credential");
      setSelectedCredential(null);
    }
  }, [open, connectorType, isConfigured]);

  // Auto-select credential if there's only one
  useEffect(() => {
    if (credentials?.length === 1 && !selectedCredential && credentials[0]) {
      setSelectedCredential(credentials[0]);
    }
  }, [credentials, selectedCredential]);

  if (!connectorType || !sourceMetadata) return null;

  // Don't render for configured connectors (handled by popover in ConnectorCard)
  if (isConfigured) return null;

  const handleCredentialCreated = (cred: Credential<any>) => {
    setSelectedCredential(cred);
    refreshCredentials();
  };

  const handleCredentialDeleted = (credId: number) => {
    if (selectedCredential?.id === credId) {
      setSelectedCredential(null);
    }
    refreshCredentials();
  };

  const handleOAuthRedirect = () => {
    // Save state before OAuth redirect
    sessionStorage.setItem(
      OAUTH_STATE_KEY,
      JSON.stringify({
        connectorType,
        timestamp: Date.now(),
      })
    );
  };

  const handleContinue = () => {
    if (selectedCredential) {
      setStep("configure");
    }
  };

  const handleBack = () => {
    setStep("credential");
  };

  const handleConnectorSuccess = () => {
    onSuccess();
  };

  // Dynamic title and description based on flow type
  const getStepTitle = () => {
    if (isSingleStep) {
      return `Connect ${sourceMetadata.displayName}`;
    }
    return step === "credential"
      ? `Connect ${sourceMetadata.displayName}`
      : `Configure ${sourceMetadata.displayName}`;
  };

  const getStepDescription = () => {
    if (isSingleStep) {
      return "Select or create a credential to connect";
    }
    return step === "credential"
      ? "Step 1: Select or create a credential"
      : "Step 2: Configure your connector";
  };

  return (
    <>
      <Modal open={open} onOpenChange={onClose}>
        <Modal.Content width="md" height="fit">
          <Modal.Header
            icon={SvgPlug}
            title={getStepTitle()}
            description={getStepDescription()}
            onClose={onClose}
          />
          <Modal.Body>
            {step === "credential" ? (
              <CredentialStep
                connectorType={connectorType}
                credentials={credentials || []}
                selectedCredential={selectedCredential}
                onSelectCredential={setSelectedCredential}
                onCredentialCreated={handleCredentialCreated}
                onCredentialDeleted={handleCredentialDeleted}
                onContinue={handleContinue}
                onOAuthRedirect={handleOAuthRedirect}
                refresh={refreshCredentials}
                isSingleStep={isSingleStep}
                onConnectorSuccess={handleConnectorSuccess}
                setPopup={setPopup}
              />
            ) : selectedCredential ? (
              <ConnectorConfigStep
                connectorType={connectorType}
                credential={selectedCredential}
                onSuccess={handleConnectorSuccess}
                onBack={handleBack}
                setPopup={setPopup}
              />
            ) : null}
          </Modal.Body>
        </Modal.Content>
      </Modal>
      {popup}
    </>
  );
}
