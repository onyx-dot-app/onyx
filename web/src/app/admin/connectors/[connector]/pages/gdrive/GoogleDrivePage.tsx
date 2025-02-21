"use client";

import React, { useEffect, useState } from "react";
import useSWR, { mutate } from "swr";
import { FetchError, errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LoadingAnimation } from "@/components/Loading";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { ValidSources } from "@/lib/types";
import { usePublicCredentials } from "@/lib/hooks";
import Title from "@/components/ui/title";
import { DriveJsonUploadSection, DriveAuthSection } from "./Credential";
import {
  Credential,
  GoogleDriveCredentialJson,
  GoogleDriveServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";
import { ConnectorSnapshot } from "@/lib/connectors/connectors";
import { useUser } from "@/components/user/UserProvider";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";

const useConnectorsByCredentialId = (credential_id: number | null) => {
  let url: string | null = null;
  if (credential_id !== null) {
    url = `/api/manage/admin/connector?credential=${credential_id}`;
  }
  const swrResponse = useSWR<ConnectorSnapshot[]>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshConnectorsByCredentialId: () => mutate(url),
  };
};

const GDriveMain = ({
  setPopup,
}: {
  setPopup: (popup: PopupSpec | null) => void;
}) => {
  const { isAdmin, user } = useUser();

  // tries getting the uploaded credential json
  const {
    data: appCredentialData,
    isLoading: isAppCredentialLoading,
    error: isAppCredentialError,
  } = useSWR<{ client_id: string }, FetchError>(
    "/api/manage/admin/connector/google-drive/app-credential",
    errorHandlingFetcher
  );

  // tries getting the uploaded service account key
  const {
    data: serviceAccountKeyData,
    isLoading: isServiceAccountKeyLoading,
    error: isServiceAccountKeyError,
  } = useSWR<{ service_account_email: string }, FetchError>(
    "/api/manage/admin/connector/google-drive/service-account-key",
    errorHandlingFetcher
  );

  // gets all public credentials
  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  // gets all credentials for source type google drive
  const {
    data: googleDriveCredentials,
    isLoading: isGoogleDriveCredentialsLoading,
    error: googleDriveCredentialsError,
  } = useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(ValidSources.GoogleDrive),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );

  // filters down to just credentials that were created via upload (there should be only one)
  let credential_id = null;
  if (googleDriveCredentials) {
    const googleDriveUploadedCredentials: Credential<GoogleDriveCredentialJson>[] =
      googleDriveCredentials.filter(
        (googleDriveCredential) =>
          googleDriveCredential.credential_json.authentication_method !==
          "oauth_interactive"
      );

    if (googleDriveUploadedCredentials.length > 0) {
      credential_id = googleDriveUploadedCredentials[0].id;
    }
  }

  // retrieves all connectors for that credential id
  const {
    data: googleDriveConnectors,
    isLoading: isGoogleDriveConnectorsLoading,
    error: googleDriveConnectorsError,
    refreshConnectorsByCredentialId,
  } = useConnectorsByCredentialId(credential_id);

  const appCredentialSuccessfullyFetched =
    appCredentialData ||
    (isAppCredentialError && isAppCredentialError.status === 404);
  const serviceAccountKeySuccessfullyFetched =
    serviceAccountKeyData ||
    (isServiceAccountKeyError && isServiceAccountKeyError.status === 404);

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

  // get the actual uploaded oauth or service account credentials
  const googleDrivePublicUploadedCredential:
    | Credential<GoogleDriveCredentialJson>
    | undefined = credentialsData.find(
    (credential) =>
      credential.credential_json?.google_tokens &&
      credential.admin_public &&
      credential.source === "google_drive" &&
      credential.credential_json.authentication_method !== "oauth_interactive"
  );

  const googleDriveServiceAccountCredential:
    | Credential<GoogleDriveServiceAccountCredentialJson>
    | undefined = credentialsData.find(
    (credential) =>
      credential.credential_json?.google_service_account_key &&
      credential.source === "google_drive"
  );

  if (googleDriveConnectorsError) {
    return (
      <ErrorCallout errorTitle="Failed to load Google Drive associated connectors." />
    );
  }

  let connectorAssociated = false;
  if (googleDriveConnectors) {
    if (googleDriveConnectors.length > 0) {
      connectorAssociated = true;
    }
  }

  return (
    <>
      <Title className="mb-2 mt-6">Step 1: Provide your Credentials</Title>
      <DriveJsonUploadSection
        setPopup={setPopup}
        appCredentialData={appCredentialData}
        serviceAccountCredentialData={serviceAccountKeyData}
        isAdmin={isAdmin}
      />

      {isAdmin && (
        <>
          <Title className="mb-2 mt-6">Step 2: Authenticate with Onyx</Title>
          <DriveAuthSection
            setPopup={setPopup}
            refreshCredentials={refreshCredentials}
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
