import useSWR, { mutate } from "swr";
import { toast } from "@/hooks/useToast";
import { FetchError, errorHandlingFetcher } from "@/lib/fetcher";
import { Credential } from "@/lib/connectors/credentials";
import { ConnectorSnapshot } from "@/lib/connectors/connectors";
import { ValidSources } from "@/lib/types";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";
import { SWR_KEYS } from "@/lib/swr-keys";

// Constants for service names to avoid typos
export const GOOGLE_SERVICES = {
  GMAIL: "gmail",
  GOOGLE_DRIVE: "google-drive",
} as const;

// Parse an uploaded OAuth app JSON; toasts and returns null when invalid.
export const parseOauthAppCredentialJson = (
  value: string
): Record<string, unknown> | null => {
  try {
    const parsed = JSON.parse(value) as Record<string, unknown>;
    const web = parsed.web as Record<string, unknown> | undefined;
    if (
      !web ||
      typeof web.client_id !== "string" ||
      typeof web.client_secret !== "string"
    ) {
      toast.error(
        "Invalid file provided - expected an OAuth app JSON key with web.client_id and web.client_secret"
      );
      return null;
    }
    return parsed;
  } catch (error) {
    toast.error(`Invalid file provided - ${error}`);
    return null;
  }
};

export const useGoogleCredentials = (
  source: ValidSources.Gmail | ValidSources.GoogleDrive
) => {
  return useSWR<Credential<any>[]>(
    buildSimilarCredentialInfoURL(source),
    errorHandlingFetcher,
    { refreshInterval: 5000 }
  );
};

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

    if (uploadedCredentials.length > 0 && uploadedCredentials[0]) {
      credential_id = uploadedCredentials[0].id;
    }
  }

  return { credential_id, uploadedCredentials };
};

export const checkConnectorsExist = (
  connectors: ConnectorSnapshot[] | undefined
): boolean => {
  return !!connectors && connectors.length > 0;
};

export const refreshAllGoogleData = (
  source: ValidSources.Gmail | ValidSources.GoogleDrive
) => {
  mutate(buildSimilarCredentialInfoURL(source));
};
