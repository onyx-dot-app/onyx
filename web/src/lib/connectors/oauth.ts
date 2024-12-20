import { ValidSources } from "../types";

export async function getConnectorOauthRedirectUrl(
  connector: ValidSources
): Promise<string | null> {
  const response = await fetch(
    `/api/connector/oauth/authorize/${connector}?desired_return_url=${encodeURIComponent(
      window.location.href
    )}`
  );

  if (!response.ok) {
    console.error(`Failed to fetch OAuth redirect URL for ${connector}`);
    return null;
  }

  const data = await response.json();
  return data.redirect_url as string;
}
