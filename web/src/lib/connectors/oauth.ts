import useSWR from "swr";

import { OAuthDetails } from "@/lib/connectors/credentials";
import { errorHandlingFetcher, parseErrorDetail } from "@/lib/fetcher";
import { ValidSources } from "@/lib/types";

const OAUTH_REDIRECT_ERROR = "Unable to start OAuth";
const OAUTH_REDIRECT_LOG_ERROR = "Failed to fetch OAuth redirect URL";

interface OAuthRedirectResponse {
  redirect_url: string;
}

export async function getConnectorOauthRedirectUrl(
  connector: ValidSources,
  additional_kwargs: Record<string, string>
): Promise<string> {
  try {
    const queryParams = new URLSearchParams({
      desired_return_url: `${window.location.pathname}${window.location.search}${window.location.hash}`,
      ...additional_kwargs,
    });
    const response = await fetch(
      `/api/connector/oauth/authorize/${connector}?${queryParams.toString()}`
    );

    if (!response.ok) {
      throw new Error(await parseErrorDetail(response, OAUTH_REDIRECT_ERROR));
    }

    const data = (await response.json()) as OAuthRedirectResponse;
    return data.redirect_url;
  } catch (error) {
    console.error(`${OAUTH_REDIRECT_LOG_ERROR} for ${connector}:`, error);
    throw error;
  }
}

export function useOAuthDetails(sourceType: ValidSources) {
  return useSWR<OAuthDetails>(
    `/api/connector/oauth/details/${sourceType}`,
    errorHandlingFetcher,
    {
      shouldRetryOnError: false,
    }
  );
}
