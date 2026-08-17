import useSWR from "swr";

import { OAuthDetails } from "@/lib/connectors/credentials";
import { errorHandlingFetcher, parseErrorDetail } from "@/lib/fetcher";
import { ValidSources } from "@/lib/types";

const OAUTH_REDIRECT_ERROR = "Unable to start OAuth";

interface OAuthRedirectResponse {
  redirect_url: string;
}

export async function getConnectorOauthRedirectUrl(
  connector: ValidSources,
  additional_kwargs: Record<string, string>
): Promise<string> {
  const queryParams = new URLSearchParams({
    desired_return_url: window.location.href,
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
