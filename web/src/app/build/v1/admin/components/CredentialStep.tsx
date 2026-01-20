"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import Card from "@/refresh-components/cards/Card";
import { SvgPlus, SvgCheck } from "@opal/icons";
import { ValidSources } from "@/lib/types";
import { Credential } from "@/lib/connectors/credentials";
import { getSourceMetadata } from "@/lib/sources";
import {
  useOAuthDetails,
  getConnectorOauthRedirectUrl,
} from "@/lib/connectors/oauth";
import CreateCredentialInline from "@/app/build/v1/admin/components/CreateCredentialInline";

interface CredentialStepProps {
  connectorType: ValidSources;
  credentials: Credential<any>[];
  selectedCredential: Credential<any> | null;
  onSelectCredential: (cred: Credential<any>) => void;
  onCredentialCreated: (cred: Credential<any>) => void;
  onContinue: () => void;
  onOAuthRedirect: () => void;
}

export default function CredentialStep({
  connectorType,
  credentials,
  selectedCredential,
  onSelectCredential,
  onCredentialCreated,
  onContinue,
  onOAuthRedirect,
}: CredentialStepProps) {
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [isRedirecting, setIsRedirecting] = useState(false);

  const { data: oauthDetails, isLoading: oauthLoading } =
    useOAuthDetails(connectorType);
  const sourceMetadata = getSourceMetadata(connectorType);

  const isOAuthConnector = oauthDetails?.oauth_enabled === true;
  const hasCredentials = credentials.length > 0;

  const handleCreateNew = async () => {
    if (isOAuthConnector) {
      // For OAuth connectors, redirect to OAuth flow
      setIsRedirecting(true);
      onOAuthRedirect(); // Save state before redirect

      const redirectUrl = await getConnectorOauthRedirectUrl(connectorType, {});
      if (redirectUrl) {
        window.location.href = redirectUrl;
      } else {
        setIsRedirecting(false);
        console.error("Failed to get OAuth redirect URL");
      }
    } else {
      // For token-based connectors, show inline form
      setShowCreateForm(true);
    }
  };

  const handleCredentialCreated = (cred: Credential<any>) => {
    setShowCreateForm(false);
    onCredentialCreated(cred);
  };

  // Show create form for token-based connectors
  if (showCreateForm && !isOAuthConnector) {
    return (
      <Section gap={1} alignItems="stretch" height="fit">
        <Text mainUiBody>Create {sourceMetadata.displayName} Credential</Text>
        <CreateCredentialInline
          connectorType={connectorType}
          onSuccess={handleCredentialCreated}
          onCancel={() => setShowCreateForm(false)}
        />
      </Section>
    );
  }

  return (
    <Section gap={1} alignItems="stretch" height="fit">
      <Text mainUiBody>
        {hasCredentials
          ? `Select a credential for ${sourceMetadata.displayName}`
          : `Create a credential for ${sourceMetadata.displayName}`}
      </Text>

      {/* Existing credentials list */}
      {hasCredentials && (
        <Section gap={0.5} alignItems="stretch" height="fit">
          {credentials.map((cred) => (
            <button
              key={cred.id}
              onClick={() => onSelectCredential(cred)}
              className="w-full text-left focus:outline-none"
            >
              <Card
                variant={
                  selectedCredential?.id === cred.id ? "primary" : "secondary"
                }
              >
                <Section
                  flexDirection="row"
                  justifyContent="between"
                  alignItems="center"
                  gap={0.5}
                  height="fit"
                >
                  <Section alignItems="start" gap={0.25} height="fit">
                    <Text mainUiBody>
                      {cred.name || `Credential #${cred.id}`}
                    </Text>
                    <Text secondaryBody text03>
                      Created {new Date(cred.time_created).toLocaleDateString()}
                    </Text>
                  </Section>
                  {selectedCredential?.id === cred.id && (
                    <SvgCheck className="w-5 h-5 text-green-500" />
                  )}
                </Section>
              </Card>
            </button>
          ))}
        </Section>
      )}

      {/* Create new button */}
      <Button
        action
        secondary
        leftIcon={SvgPlus}
        onClick={handleCreateNew}
        disabled={isRedirecting || oauthLoading}
      >
        {isRedirecting
          ? "Redirecting..."
          : isOAuthConnector
            ? `Connect with ${sourceMetadata.displayName}`
            : "Create New Credential"}
      </Button>

      {/* Continue button */}
      {hasCredentials && (
        <Section flexDirection="row" justifyContent="end" height="fit">
          <Button
            action
            primary
            onClick={onContinue}
            disabled={!selectedCredential}
          >
            Continue
          </Button>
        </Section>
      )}
    </Section>
  );
}
