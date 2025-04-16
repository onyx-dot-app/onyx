"use client";

import React from "react";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { usePopup } from "@/components/admin/connectors/Popup";
import { CCPairBasicInfo, ValidSources } from "@/lib/types";
import {
  Credential,
  GmailCredentialJson,
  GmailServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";
import { GmailAuthSection, GmailJsonUploadSection } from "./Credential";
import { usePublicCredentials, useBasicConnectorStatus } from "@/lib/hooks";
import Title from "@/components/ui/title";
import { useUser } from "@/components/user/UserProvider";
import {
  useGoogleAppCredential,
  useGoogleServiceAccountKey,
  useGoogleCredentials,
  useConnectorsByCredentialId,
  checkCredentialsFetched,
  filterUploadedCredentials,
  checkConnectorsExist,
  refreshAllGoogleData,
} from "@/lib/googleConnector";

export const GmailMain = () => {
  const { isAdmin, user } = useUser();
  const { popup, setPopup } = usePopup();

  const {
    data: appCredentialData,
    isLoading: isAppCredentialLoading,
    error: isAppCredentialError,
  } = useGoogleAppCredential("gmail");

  const {
    data: serviceAccountKeyData,
    isLoading: isServiceAccountKeyLoading,
    error: isServiceAccountKeyError,
  } = useGoogleServiceAccountKey("gmail");

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

  const { credential_id, uploadedCredentials } =
    filterUploadedCredentials(gmailCredentials);

  const {
    data: gmailConnectors,
    isLoading: isGmailConnectorsLoading,
    error: gmailConnectorsError,
    refreshConnectorsByCredentialId,
  } = useConnectorsByCredentialId(credential_id);

  const {
    appCredentialSuccessfullyFetched,
    serviceAccountKeySuccessfullyFetched,
  } = checkCredentialsFetched(
    appCredentialData,
    isAppCredentialError,
    serviceAccountKeyData,
    isServiceAccountKeyError
  );

  const handleRefresh = () => {
    refreshCredentials();
    refreshConnectorsByCredentialId();
    refreshAllGoogleData(ValidSources.Gmail);
  };

  if (
    (!appCredentialSuccessfullyFetched && isAppCredentialLoading) ||
    (!serviceAccountKeySuccessfullyFetched && isServiceAccountKeyLoading) ||
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

  if (
    !appCredentialSuccessfullyFetched ||
    !serviceAccountKeySuccessfullyFetched
  ) {
    return (
      <ErrorCallout errorTitle="Error loading Gmail app credentials. Contact an administrator." />
    );
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

  const hasUploadedCredentials =
    Boolean(appCredentialData?.client_id) ||
    Boolean(serviceAccountKeyData?.service_account_email);

  return (
    <>
      {popup}
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your Credentials
      </Title>
      <GmailJsonUploadSection
        setPopup={setPopup}
        appCredentialData={appCredentialData}
        serviceAccountCredentialData={serviceAccountKeyData}
        isAdmin={isAdmin}
        onSuccess={handleRefresh}
        existingAuthCredential={Boolean(
          gmailPublicUploadedCredential || gmailServiceAccountCredential
        )}
      />

      {isAdmin && hasUploadedCredentials && (
        <>
          <Title className="mb-2 mt-6 ml-auto mr-auto">
            Step 2: Authenticate with Onyx
          </Title>
          <GmailAuthSection
            setPopup={setPopup}
            refreshCredentials={handleRefresh}
            gmailPublicCredential={gmailPublicUploadedCredential}
            gmailServiceAccountCredential={gmailServiceAccountCredential}
            appCredentialData={appCredentialData}
            serviceAccountKeyData={serviceAccountKeyData}
            connectorExists={connectorExists}
            user={user}
          />
        </>
      )}
    </>
  );
};
