"use client";

import React from "react";
import useSWR from "swr";
import { FetchError, errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { usePopup } from "@/components/admin/connectors/Popup";
import { ConnectorIndexingStatus } from "@/lib/types";
import {
  usePublicCredentials,
  useConnectorCredentialIndexingStatus,
} from "@/lib/hooks";
import Title from "@/components/ui/title";
import { DriveJsonUploadSection, DriveAuthSection } from "./Credential";
import {
  Credential,
  GoogleDriveCredentialJson,
  GoogleDriveServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";
import { GoogleDriveConfig } from "@/lib/connectors/connectors";
import { useUser } from "@/components/user/UserProvider";

const GDriveMain = ({}: {}) => {
  const { isLoadingUser, isAdmin, user } = useUser();

  const {
    data: appCredentialData,
    isLoading: isAppCredentialLoading,
    error: isAppCredentialError,
  } = useSWR<{ client_id: string }, FetchError>(
    "/api/manage/admin/connector/google-drive/app-credential",
    errorHandlingFetcher
  );

  const {
    data: serviceAccountKeyData,
    isLoading: isServiceAccountKeyLoading,
    error: isServiceAccountKeyError,
  } = useSWR<{ service_account_email: string }, FetchError>(
    "/api/manage/admin/connector/google-drive/service-account-key",
    errorHandlingFetcher
  );

  const {
    data: connectorIndexingStatuses,
    isLoading: isConnectorIndexingStatusesLoading,
    error: connectorIndexingStatusesError,
  } = useConnectorCredentialIndexingStatus();
  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  const { popup, setPopup } = usePopup();

  const appCredentialSuccessfullyFetched =
    appCredentialData ||
    (isAppCredentialError && isAppCredentialError.status === 404);
  const serviceAccountKeySuccessfullyFetched =
    serviceAccountKeyData ||
    (isServiceAccountKeyError && isServiceAccountKeyError.status === 404);

  if (isLoadingUser) {
    return <></>;
  }

  if (
    (!appCredentialSuccessfullyFetched && isAppCredentialLoading) ||
    (!serviceAccountKeySuccessfullyFetched && isServiceAccountKeyLoading) ||
    (!connectorIndexingStatuses && isConnectorIndexingStatusesLoading) ||
    (!credentialsData && isCredentialsLoading)
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

  if (connectorIndexingStatusesError || !connectorIndexingStatuses) {
    return <ErrorCallout errorTitle="Failed to load connectors." />;
  }

  if (
    !appCredentialSuccessfullyFetched ||
    !serviceAccountKeySuccessfullyFetched
  ) {
    return (
      <ErrorCallout errorTitle="Error loading Google Drive app credentials. Contact an administrator." />
    );
  }

  const googleDrivePublicCredential:
    | Credential<GoogleDriveCredentialJson>
    | undefined = credentialsData.find(
    (credential) =>
      credential.credential_json?.google_tokens &&
      credential.admin_public &&
      credential.source === "google_drive"
  );
  const googleDriveServiceAccountCredential:
    | Credential<GoogleDriveServiceAccountCredentialJson>
    | undefined = credentialsData.find(
    (credential) => credential.credential_json?.google_service_account_key
  );

  const googleDriveConnectorIndexingStatuses: ConnectorIndexingStatus<
    GoogleDriveConfig,
    GoogleDriveCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "google_drive"
  );

  return (
    <>
      {popup}
      <Title className="mb-2 mt-6 ml-auto mr-auto">
        Step 1: Provide your Credentials
      </Title>
      <DriveJsonUploadSection
        setPopup={setPopup}
        appCredentialData={appCredentialData}
        serviceAccountCredentialData={serviceAccountKeyData}
        isAdmin={isAdmin}
      />

      {isAdmin && (
        <>
          <Title className="mb-2 mt-6 ml-auto mr-auto">
            Step 2: Authenticate with Danswer
          </Title>
          <DriveAuthSection
            setPopup={setPopup}
            refreshCredentials={refreshCredentials}
            googleDrivePublicCredential={googleDrivePublicCredential}
            googleDriveServiceAccountCredential={
              googleDriveServiceAccountCredential
            }
            appCredentialData={appCredentialData}
            serviceAccountKeyData={serviceAccountKeyData}
            connectorExists={googleDriveConnectorIndexingStatuses.length > 0}
            user={user}
          />
        </>
      )}
    </>
  );
};

export default GDriveMain;
