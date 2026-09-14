import useSWR, { mutate } from "swr";
import { toast } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { Credential } from "@/lib/connectors/credentials";
import { ValidSources } from "@/lib/types";
import { buildSimilarCredentialInfoURL } from "@/app/admin/connector/[ccPairId]/lib";

// Constants for service names to avoid typos

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

export const refreshAllGoogleData = (
  source: ValidSources.Gmail | ValidSources.GoogleDrive
) => {
  mutate(buildSimilarCredentialInfoURL(source));
};
