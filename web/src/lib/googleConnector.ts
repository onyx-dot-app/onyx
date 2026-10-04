import useSWR, { mutate } from "swr";
import { FetchError, errorHandlingFetcher } from "@/lib/fetcher";
import type { ConnectorSnapshot } from "@/lib/connectors/types";
import { ValidSources } from "@/lib/connectors/types/source";
import { refreshSourceCredentials } from "@/lib/credentials/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";

// Constants for service names to avoid typos
export const GOOGLE_SERVICES = {
  GMAIL: "gmail",
  GOOGLE_DRIVE: "google-drive",
} as const;

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

export const checkConnectorsExist = (
  connectors: ConnectorSnapshot[] | undefined
): boolean => {
  return !!connectors && connectors.length > 0;
};

export const refreshAllGoogleData = (
  source: ValidSources.Gmail | ValidSources.GoogleDrive
) => {
  refreshSourceCredentials(source);
};
