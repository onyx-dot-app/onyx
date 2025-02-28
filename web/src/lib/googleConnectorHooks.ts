import useSWR, { mutate } from "swr";
import { FetchError, errorHandlingFetcher } from "@/lib/fetcher";
import { Credential } from "@/lib/connectors/credentials";
import { ConnectorSnapshot } from "@/lib/connectors/connectors";
import { ValidSources } from "@/lib/types";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";

/**
 * Hook to fetch app credentials for Google services
 * @param service - The Google service (gmail or google_drive)
 */
export const useGoogleAppCredential = (service: "gmail" | "google_drive") => {
  const endpoint = `/api/manage/admin/connector/${
    service === "gmail" ? "gmail" : "google-drive"
  }/app-credential`;

  return useSWR<{ client_id: string }, FetchError>(
    endpoint,
    errorHandlingFetcher
  );
};

/**
 * Hook to fetch service account key for Google services
 * @param service - The Google service (gmail or google_drive)
 */
export const useGoogleServiceAccountKey = (
  service: "gmail" | "google_drive"
) => {
  const endpoint = `/api/manage/admin/connector/${
    service === "gmail" ? "gmail" : "google-drive"
  }/service-account-key`;

  return useSWR<{ service_account_email: string }, FetchError>(
    endpoint,
    errorHandlingFetcher
  );
};

/**
 * Hook to fetch credentials for a specific Google service
 * @param source - The source type (Gmail or GoogleDrive)
 */
export const useGoogleCredentials = (
  source: ValidSources.Gmail | ValidSources.GoogleDrive
) => {
  return useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(source),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );
};

/**
 * Hook to fetch connectors by credential ID
 * @param credential_id - The credential ID to fetch connectors for
 */
export const useConnectorsByCredentialId = (credential_id: number | null) => {
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

/**
 * Helper function to check if app credentials and service account keys were successfully fetched
 */
export const checkCredentialsFetched = (
  appCredentialData: any,
  appCredentialError: FetchError | undefined,
  serviceAccountKeyData: any,
  serviceAccountKeyError: FetchError | undefined
) => {
  const appCredentialSuccessfullyFetched =
    appCredentialData ||
    (appCredentialError && appCredentialError.status === 404);

  const serviceAccountKeySuccessfullyFetched =
    serviceAccountKeyData ||
    (serviceAccountKeyError && serviceAccountKeyError.status === 404);

  return {
    appCredentialSuccessfullyFetched,
    serviceAccountKeySuccessfullyFetched,
  };
};

/**
 * Helper function to filter uploaded credentials
 */
export const filterUploadedCredentials = <
  T extends { authentication_method?: string },
>(
  credentials: Credential<T>[] | undefined
): { credential_id: number | null; uploadedCredentials: Credential<T>[] } => {
  let credential_id = null;
  let uploadedCredentials: Credential<T>[] = [];

  if (credentials) {
    uploadedCredentials = credentials.filter(
      (credential) =>
        credential.credential_json.authentication_method !== "oauth_interactive"
    );

    if (uploadedCredentials.length > 0) {
      credential_id = uploadedCredentials[0].id;
    }
  }

  return { credential_id, uploadedCredentials };
};

/**
 * Helper function to check if connectors exist for a credential
 */
export const checkConnectorsExist = (
  connectors: ConnectorSnapshot[] | undefined
): boolean => {
  return !!connectors && connectors.length > 0;
};

/**
 * Helper function to refresh all Google connector data
 */
export const refreshAllGoogleData = (
  source: ValidSources.Gmail | ValidSources.GoogleDrive
) => {
  // Refresh credentials
  mutate(buildSimilarCredentialInfoURL(source));

  // Refresh app credential
  const service = source === ValidSources.Gmail ? "gmail" : "google-drive";
  mutate(`/api/manage/admin/connector/${service}/app-credential`);

  // Refresh service account key
  mutate(`/api/manage/admin/connector/${service}/service-account-key`);
};
