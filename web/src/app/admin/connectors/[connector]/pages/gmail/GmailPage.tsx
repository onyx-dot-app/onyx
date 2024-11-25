"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { LoadingAnimation } from "@/components/Loading";
import { usePopup } from "@/components/admin/connectors/Popup";
import { ConnectorIndexingStatus } from "@/lib/types";
import {
  Credential,
  GmailCredentialJson,
  GmailServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";
import { GmailAuthSection, GmailJsonUploadSection } from "./Credential";
import {
  usePublicCredentials,
  useConnectorCredentialIndexingStatus,
} from "@/lib/hooks";
import Title from "@/components/ui/title";
import { GmailConfig } from "@/lib/connectors/connectors";
import { useUser } from "@/components/user/UserProvider";

export const GmailMain = () => {
  const { isLoadingUser, isAdmin, user } = useUser();

  const {
    data: appCredentialData,
    isLoading: isAppCredentialLoading,
    error: isAppCredentialError,
  } = useSWR<{ client_id: string }>(
    "/api/manage/admin/connector/gmail/app-credential",
    errorHandlingFetcher
  );
  const {
    data: serviceAccountKeyData,
    isLoading: isServiceAccountKeyLoading,
    error: isServiceAccountKeyError,
  } = useSWR<{ service_account_email: string }>(
    "/api/manage/admin/connector/gmail/service-account-key",
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
    return (
      <div className="mx-auto">
        <div className="text-red-500">Failed to load credentials.</div>
      </div>
    );
  }

  if (connectorIndexingStatusesError || !connectorIndexingStatuses) {
    return (
      <div className="mx-auto">
        <div className="text-red-500">Failed to load connectors.</div>
      </div>
    );
  }

  if (
    !appCredentialSuccessfullyFetched ||
    !serviceAccountKeySuccessfullyFetched
  ) {
    return (
      <div className="mx-auto">
        <div className="text-red-500">
          Error loading Gmail app credentials. Contact an administrator.
        </div>
      </div>
    );
  }

  const gmailPublicCredential: Credential<GmailCredentialJson> | undefined =
    credentialsData.find(
      (credential) =>
        (credential.credential_json?.google_service_account_key ||
          credential.credential_json?.google_tokens) &&
        credential.admin_public
    );
  const gmailServiceAccountCredential:
    | Credential<GmailServiceAccountCredentialJson>
    | undefined = credentialsData.find(
    (credential) =>
      credential.credential_json?.google_service_account_key &&
      credential.source === "gmail"
  );
  const gmailConnectorIndexingStatuses: ConnectorIndexingStatus<
    GmailConfig,
    GmailCredentialJson
  >[] = connectorIndexingStatuses.filter(
    (connectorIndexingStatus) =>
      connectorIndexingStatus.connector.source === "gmail"
  );

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
      />

      {isAdmin && (
        <>
          <Title className="mb-2 mt-6 ml-auto mr-auto">
            Step 2: Authenticate with Danswer
          </Title>
          <GmailAuthSection
            setPopup={setPopup}
            refreshCredentials={refreshCredentials}
            gmailPublicCredential={gmailPublicCredential}
            gmailServiceAccountCredential={gmailServiceAccountCredential}
            appCredentialData={appCredentialData}
            serviceAccountKeyData={serviceAccountKeyData}
            connectorExists={gmailConnectorIndexingStatuses.length > 0}
            user={user}
          />
        </>
      )}
    </>
  );
};
