"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import LineItem from "@/refresh-components/buttons/LineItem";
import { SvgPlus, SvgCheck, SvgTrash } from "@opal/icons";
import { ValidSources } from "@/lib/types";
import { Credential } from "@/lib/connectors/credentials";
import { getSourceMetadata } from "@/lib/sources";
import {
  useOAuthDetails,
  getConnectorOauthRedirectUrl,
} from "@/lib/connectors/oauth";
import { deleteCredential } from "@/lib/credential";
import CreateCredentialInline from "@/app/build/v1/admin/components/CreateCredentialInline";

interface CredentialStepProps {
  connectorType: ValidSources;
  credentials: Credential<any>[];
  selectedCredential: Credential<any> | null;
  onSelectCredential: (cred: Credential<any>) => void;
  onCredentialCreated: (cred: Credential<any>) => void;
  onCredentialDeleted: (credId: number) => void;
  onContinue: () => void;
  onOAuthRedirect: () => void;
}

export default function CredentialStep({
  connectorType,
  credentials,
  selectedCredential,
  onSelectCredential,
  onCredentialCreated,
  onCredentialDeleted,
  onContinue,
  onOAuthRedirect,
}: CredentialStepProps) {
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [isRedirecting, setIsRedirecting] = useState(false);
  const [deletingCredId, setDeletingCredId] = useState<number | null>(null);

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

  const handleDeleteCredential = async (
    credId: number,
    e: React.MouseEvent
  ) => {
    e.stopPropagation();
    setDeletingCredId(credId);
    try {
      const response = await deleteCredential(credId);
      if (response.ok) {
        onCredentialDeleted(credId);
      } else {
        console.error("Failed to delete credential");
      }
    } catch (error) {
      console.error("Error deleting credential:", error);
    } finally {
      setDeletingCredId(null);
    }
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
    <Section flexDirection="column" gap={1} alignItems="start" height="fit">
      <Text mainUiBody>
        {hasCredentials
          ? `Select a credential for ${sourceMetadata.displayName}`
          : `Create a credential for ${sourceMetadata.displayName}`}
      </Text>

      {/* Existing credentials list */}
      {hasCredentials && (
        <div className="flex flex-col gap-1 max-w-md w-full">
          {credentials.map((cred) => {
            const isSelected = selectedCredential?.id === cred.id;
            const isDeleting = deletingCredId === cred.id;
            return (
              <LineItem
                key={cred.id}
                onClick={() => onSelectCredential(cred)}
                selected={isSelected}
                emphasized
                description={`Created ${new Date(
                  cred.time_created
                ).toLocaleDateString()}`}
                rightChildren={
                  <div className="flex items-center gap-1">
                    {isSelected && <SvgCheck size={16} />}
                    <IconButton
                      main
                      internal
                      icon={SvgTrash}
                      onClick={(e) => handleDeleteCredential(cred.id, e)}
                      disabled={isDeleting}
                    />
                  </div>
                }
              >
                {cred.name || `Credential #${cred.id}`}
              </LineItem>
            );
          })}
        </div>
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
