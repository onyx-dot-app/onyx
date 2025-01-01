import { ValidSources } from "../types";

export async function getConnectorOauthRedirectUrl(
  connector: ValidSources,
  additional_kwargs: Record<string, string>
): Promise<string | null> {
  const queryParams = new URLSearchParams({
    desired_return_url: window.location.href,
    ...additional_kwargs,
  });
  const response = await fetch(
    `/api/connector/oauth/authorize/${connector}?${queryParams.toString()}`
  );

  if (!response.ok) {
    console.error(`Failed to fetch OAuth redirect URL for ${connector}`);
    return null;
  }

  const data = await response.json();
  return data.redirect_url as string;
}
