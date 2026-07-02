"use client";

import React from "react";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { toast } from "@/hooks/useToast";
import { CCPairBasicInfo, ValidSources } from "@/lib/types";
import {
  Credential,
  GmailCredentialJson,
  GmailServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";
import { GmailAuthSection } from "./Credential";
import { usePublicCredentials, useBasicConnectorStatus } from "@/lib/hooks";
import { useUser } from "@/providers/UserProvider";
import {
  useGoogleCredentials,
  useConnectorsByCredentialId,
  filterUploadedCredentials,
  checkConnectorsExist,
  refreshAllGoogleData,
} from "@/lib/googleConnector";

interface GmailMainProps {
  buildMode?: boolean;
  onOAuthRedirect?: () => void;
  onCredentialCreated?: (
    credential: Credential<
      GmailCredentialJson | GmailServiceAccountCredentialJson
    >
  ) => void;
}

export const GmailMain = ({
  buildMode = false,
  onOAuthRedirect,
  onCredentialCreated,
}: GmailMainProps) => {
  const { isAdmin, user } = useUser();

  const {
    data: connectorIndexingStatuses,
    isLoading: isConnectorIndexingStatusesLoading,
    error: connectorIndexingStatusesError,
  } = useBasicConnectorStatus();

  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  const {
    data: gmailCredentials,
    isLoading: isGmailCredentialsLoading,
    error: gmailCredentialsError,
  } = useGoogleCredentials(ValidSources.Gmail);

  const { credential_id } = filterUploadedCredentials(gmailCredentials);

  const {
    data: gmailConnectors,
    isLoading: isGmailConnectorsLoading,
    error: gmailConnectorsError,
    refreshConnectorsByCredentialId,
  } = useConnectorsByCredentialId(credential_id);

  const handleRefresh = () => {
    refreshCredentials();
    refreshConnectorsByCredentialId();
    refreshAllGoogleData(ValidSources.Gmail);
  };

  if (
    (!connectorIndexingStatuses && isConnectorIndexingStatusesLoading) ||
    (!credentialsData && isCredentialsLoading) ||
    (!gmailCredentials && isGmailCredentialsLoading) ||
    (!gmailConnectors && isGmailConnectorsLoading)
  ) {
    return (
      <div className="mx-auto">
        <LoadingAnimation text="" />
      </div>
    );
  }

  if (credentialsError || !credentialsData) {
    return <ErrorCallout errorTitle="Failed to load credentials." />;
  }

  if (gmailCredentialsError || !gmailCredentials) {
    return <ErrorCallout errorTitle="Failed to load Gmail credentials." />;
  }

  if (connectorIndexingStatusesError || !connectorIndexingStatuses) {
    return <ErrorCallout errorTitle="Failed to load connectors." />;
  }

  if (gmailConnectorsError) {
    return (
      <ErrorCallout errorTitle="Failed to load Gmail associated connectors." />
    );
  }

  const connectorExistsFromCredential = checkConnectorsExist(gmailConnectors);

  const gmailPublicUploadedCredential:
    | Credential<GmailCredentialJson>
    | undefined = credentialsData.find(
    (credential) =>
      credential.credential_json?.google_tokens &&
      credential.admin_public &&
      credential.source === "gmail" &&
      credential.credential_json.authentication_method !== "oauth_interactive"
  );

  const gmailServiceAccountCredential:
    | Credential<GmailServiceAccountCredentialJson>
    | undefined = credentialsData.find(
    (credential) =>
      credential.credential_json?.google_service_account_key &&
      credential.source === "gmail"
  );

  const gmailConnectorIndexingStatuses: CCPairBasicInfo[] =
    connectorIndexingStatuses.filter(
      (connectorIndexingStatus) => connectorIndexingStatus.source === "gmail"
    );

  const connectorExists =
    connectorExistsFromCredential || gmailConnectorIndexingStatuses.length > 0;

  return (
    <>
      {isAdmin && (
        <>
          <GmailAuthSection
            refreshCredentials={handleRefresh}
            gmailPublicCredential={gmailPublicUploadedCredential}
            gmailServiceAccountCredential={gmailServiceAccountCredential}
            connectorExists={connectorExists}
            user={user}
            buildMode={buildMode}
            onOAuthRedirect={onOAuthRedirect}
            // Necessary prop drilling for build mode v1.
            // TODO: either integrate gmail into normal flow
            // or create a build-mode specific Gmail flow
            onCredentialCreated={onCredentialCreated}
          />
        </>
      )}
    </>
  );
};
