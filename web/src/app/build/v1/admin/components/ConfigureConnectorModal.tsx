"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import { SourceIcon } from "@/components/SourceIcon";
import { ValidSources } from "@/lib/types";
import { getSourceMetadata } from "@/lib/sources";
import { SvgPlug, SvgRefreshCw, SvgTrash } from "@opal/icons";
import { Credential } from "@/lib/connectors/credentials";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import { BuildConnectorConfig } from "./ConnectorCard";
import CredentialStep from "./CredentialStep";
import ConnectorConfigStep from "./ConnectorConfigStep";

type ModalStep = "credential" | "configure";

interface ConfigureConnectorModalProps {
  connectorType: ValidSources | null;
  existingConfig: BuildConnectorConfig | null;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

const OAUTH_STATE_KEY = "build_oauth_state";

export default function ConfigureConnectorModal({
  connectorType,
  existingConfig,
  open,
  onClose,
  onSuccess,
}: ConfigureConnectorModalProps) {
  const [step, setStep] = useState<ModalStep>("credential");
  const [selectedCredential, setSelectedCredential] =
    useState<Credential<any> | null>(null);

  const sourceMetadata = connectorType
    ? getSourceMetadata(connectorType)
    : null;
  const isConfigured = !!existingConfig;

  // Fetch credentials for this connector type
  const { data: credentials, mutate: refreshCredentials } = useSWR<
    Credential<any>[]
  >(
    connectorType && open && !isConfigured
      ? buildSimilarCredentialInfoURL(connectorType)
      : null,
    errorHandlingFetcher
  );

  // Reset state when modal opens/closes or connector type changes
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

  const handleReindex = async () => {
    if (!existingConfig) return;
    try {
      await fetch(
        `/api/manage/admin/cc-pair/${existingConfig.cc_pair_id}/run`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ from_beginning: false }),
        }
      );
      onSuccess();
    } catch (error) {
      console.error("Failed to trigger reindex:", error);
    }
  };

  const handleDelete = async () => {
    if (!existingConfig) return;
    if (!confirm("Are you sure you want to delete this connector?")) {
      return;
    }
    try {
      await fetch(`/api/manage/admin/cc-pair/${existingConfig.cc_pair_id}`, {
        method: "DELETE",
      });
      onSuccess();
    } catch (error) {
      console.error("Failed to delete connector:", error);
    }
  };

  const handleCredentialCreated = (cred: Credential<any>) => {
    setSelectedCredential(cred);
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

  // Render content for existing/configured connector
  if (isConfigured) {
    return (
      <Modal open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
        <Modal.Content width="sm" height="fit">
          <Modal.Header
            icon={SvgPlug}
            title={sourceMetadata.displayName}
            description="Manage your data source connection"
            onClose={onClose}
          />
          <Modal.Body>
            <Section gap={1} alignItems="start" height="fit">
              <Section
                flexDirection="row"
                alignItems="center"
                gap={0.75}
                height="fit"
              >
                <SourceIcon sourceType={connectorType} iconSize={32} />
                <Section alignItems="start" gap={0.25} width="fit" height="fit">
                  <Text mainUiBody>{existingConfig.name}</Text>
                  <Text secondaryBody text03>
                    {existingConfig.docs_indexed > 0
                      ? `${existingConfig.docs_indexed.toLocaleString()} documents indexed`
                      : existingConfig.status === "indexing"
                        ? "Currently indexing..."
                        : "Connected"}
                  </Text>
                </Section>
              </Section>

              {existingConfig.last_indexed && (
                <Text secondaryBody text03>
                  Last indexed:{" "}
                  {new Date(existingConfig.last_indexed).toLocaleString()}
                </Text>
              )}

              {existingConfig.error_message && (
                <Text secondaryBody className="text-red-500">
                  Error: {existingConfig.error_message}
                </Text>
              )}
            </Section>
          </Modal.Body>
          <Modal.Footer>
            <Button
              action
              secondary
              leftIcon={SvgRefreshCw}
              onClick={handleReindex}
            >
              Re-index
            </Button>
            <Button danger secondary leftIcon={SvgTrash} onClick={handleDelete}>
              Delete
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    );
  }

  // Render content for new/unconfigured connector - Step flow
  const stepTitle =
    step === "credential"
      ? `Connect ${sourceMetadata.displayName}`
      : `Configure ${sourceMetadata.displayName}`;

  const stepDescription =
    step === "credential"
      ? "Step 1: Select or create a credential"
      : "Step 2: Configure your connector";

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="md" height="fit">
        <Modal.Header
          icon={SvgPlug}
          title={stepTitle}
          description={stepDescription}
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
              onContinue={handleContinue}
              onOAuthRedirect={handleOAuthRedirect}
            />
          ) : selectedCredential ? (
            <ConnectorConfigStep
              connectorType={connectorType}
              credential={selectedCredential}
              onSuccess={handleConnectorSuccess}
              onBack={handleBack}
            />
          ) : null}
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
