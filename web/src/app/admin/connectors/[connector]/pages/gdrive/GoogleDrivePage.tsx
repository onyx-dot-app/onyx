"use client";

import React from "react";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { ValidSources } from "@/lib/types";
import { usePublicCredentials } from "@/lib/hooks";
import { DriveAuthSection } from "./Credential";
import {
  Credential,
  GoogleDriveCredentialJson,
  GoogleDriveServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";
import { useUser } from "@/providers/UserProvider";
import {
  useGoogleCredentials,
  useConnectorsByCredentialId,
  filterUploadedCredentials,
  checkConnectorsExist,
  refreshAllGoogleData,
} from "@/lib/googleConnector";

const GDriveMain = () => {
  const { isAdmin, user } = useUser();

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
  const { credential_id } = filterUploadedCredentials(googleDriveCredentials);

  // Get connectors for the credential ID
  const {
    data: googleDriveConnectors,
    isLoading: isGoogleDriveConnectorsLoading,
    error: googleDriveConnectorsError,
    refreshConnectorsByCredentialId,
  } = useConnectorsByCredentialId(credential_id);

  // Handle refresh of all data
  const handleRefresh = () => {
    refreshCredentials();
    refreshConnectorsByCredentialId();
    refreshAllGoogleData(ValidSources.GoogleDrive);
  };

  // Loading state
  if (
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
      {isAdmin && (
        <>
          <DriveAuthSection
            refreshCredentials={handleRefresh}
            googleDrivePublicUploadedCredential={
              googleDrivePublicUploadedCredential
            }
            googleDriveServiceAccountCredential={
              googleDriveServiceAccountCredential
            }
            connectorAssociated={connectorAssociated}
            user={user}
          />
        </>
      )}
    </>
  );
};

export default GDriveMain;
