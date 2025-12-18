"use client";

import React from "react";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { ValidSources } from "@/lib/types";
import { usePublicCredentials } from "@/lib/hooks";
import Title from "@/components/ui/title";
import { DriveJsonUploadSection, DriveAuthSection } from "./Credential";
import {
  Credential,
  GoogleDriveCredentialJson,
  GoogleDriveServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";
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

const GDriveMain = ({
  setPopup,
}: {
  setPopup: (popup: PopupSpec | null) => void;
}) => {
  const { isAdmin, user } = useUser();

  // Get app credential and service account key
  const {
    data: appCredentialData,
    isLoading: isAppCredentialLoading,
    error: isAppCredentialError,
  } = useGoogleAppCredential("google_drive");

  const {
    data: serviceAccountKeyData,
    isLoading: isServiceAccountKeyLoading,
    error: isServiceAccountKeyError,
  } = useGoogleServiceAccountKey("google_drive");

  // Get all public credentials
  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  // Get Google Drive-specific credentials
  const {
    data: googleDriveCredentials,
    isLoading: isGoogleDriveCredentialsLoading,
    error: googleDriveCredentialsError,
  } = useGoogleCredentials(ValidSources.GoogleDrive);

  // Filter uploaded credentials and get credential ID
  const { credential_id, uploadedCredentials } = filterUploadedCredentials(
    googleDriveCredentials
  );

  // Get connectors for the credential ID
  const {
    data: googleDriveConnectors,
    isLoading: isGoogleDriveConnectorsLoading,
    error: googleDriveConnectorsError,
    refreshConnectorsByCredentialId,
  } = useConnectorsByCredentialId(credential_id);

  // Check if credentials were successfully fetched
  const {
    appCredentialSuccessfullyFetched,
    serviceAccountKeySuccessfullyFetched,
  } = checkCredentialsFetched(
    appCredentialData,
    isAppCredentialError,
    serviceAccountKeyData,
    isServiceAccountKeyError
  );

  // Handle refresh of all data
  const handleRefresh = () => {
    refreshCredentials();
    refreshConnectorsByCredentialId();
    refreshAllGoogleData(ValidSources.GoogleDrive);
  };

  // Loading state
  if (
    (!appCredentialSuccessfullyFetched && isAppCredentialLoading) ||
    (!serviceAccountKeySuccessfullyFetched && isServiceAccountKeyLoading) ||
    (!credentialsData && isCredentialsLoading) ||
    (!googleDriveCredentials && isGoogleDriveCredentialsLoading) ||
    (!googleDriveConnectors && isGoogleDriveConnectorsLoading)
  ) {
    return (
      <div className="mx-auto">
        <LoadingAnimation text="" />
      </div>
    );
  }

  // Error states
  if (credentialsError || !credentialsData) {
    return <ErrorCallout errorTitle="Failed to load credentials." />;
  }

  if (googleDriveCredentialsError || !googleDriveCredentials) {
    return (
      <ErrorCallout errorTitle="Failed to load Google Drive credentials." />
    );
  }

  if (
    !appCredentialSuccessfullyFetched ||
    !serviceAccountKeySuccessfullyFetched
  ) {
    return (
      <ErrorCallout errorTitle="Error loading Google Drive app credentials. Contact an administrator." />
    );
  }

  if (googleDriveConnectorsError) {
    return (
      <ErrorCallout errorTitle="Failed to load Google Drive associated connectors." />
    );
  }

  // Check if connectors exist
  const connectorAssociated = checkConnectorsExist(googleDriveConnectors);

  // Get the uploaded OAuth credential
  const googleDrivePublicUploadedCredential:
    | Credential<GoogleDriveCredentialJson>
    | undefined = credentialsData.find(
    (credential) =>
      credential.credential_json?.google_tokens &&
      credential.admin_public &&
      credential.source === "google_drive" &&
      credential.credential_json.authentication_method !== "oauth_interactive"
  );

  // Get the service account credential
  const googleDriveServiceAccountCredential:
    | Credential<GoogleDriveServiceAccountCredentialJson>
    | undefined = credentialsData.find(
    (credential) =>
      credential.credential_json?.google_service_account_key &&
      credential.source === "google_drive"
  );

  return (
    <>
      <Title className="mb-2 mt-6">Step 1: Provide your Credentials</Title>
      <DriveJsonUploadSection
        setPopup={setPopup}
        appCredentialData={appCredentialData}
        serviceAccountCredentialData={serviceAccountKeyData}
        isAdmin={isAdmin}
        onSuccess={handleRefresh}
        existingAuthCredential={Boolean(
          googleDrivePublicUploadedCredential ||
            googleDriveServiceAccountCredential
        )}
      />

      {isAdmin &&
        (appCredentialData?.client_id ||
          serviceAccountKeyData?.service_account_email) && (
          <>
            <Title className="mb-2 mt-6">Step 2: Authenticate with Onyx</Title>
            <DriveAuthSection
              setPopup={setPopup}
              refreshCredentials={handleRefresh}
              googleDrivePublicUploadedCredential={
                googleDrivePublicUploadedCredential
              }
              googleDriveServiceAccountCredential={
                googleDriveServiceAccountCredential
              }
              appCredentialData={appCredentialData}
              serviceAccountKeyData={serviceAccountKeyData}
              connectorAssociated={connectorAssociated}
              user={user}
            />
          </>
        )}
    </>
  );
};

export default GDriveMain;
