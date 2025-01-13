import {
  OAuthGoogleDriveCallbackResponse,
  OAuthPrepareAuthorizationResponse,
  OAuthSlackCallbackResponse,
} from "./types";

// server side handler to help initiate the oauth authorization request
export async function prepareOAuthAuthorizationRequest(
  connector: string,
  finalRedirect: string | null // a redirect (not the oauth redirect) for the user to return to after oauth is complete)
): Promise<OAuthPrepareAuthorizationResponse> {
  let url = `/api/oauth/prepare-authorization-request?connector=${encodeURIComponent(
    connector
  )}`;

  // Conditionally append the `redirect_on_success` parameter
  if (finalRedirect) {
    url += `&redirect_on_success=${encodeURIComponent(finalRedirect)}`;
  }

  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      connector: connector,
      redirect_on_success: finalRedirect,
    }),
  });

  if (!response.ok) {
    throw new Error(
      `Failed to prepare OAuth authorization request: ${response.status}`
    );
  }

  // Parse the JSON response
  const data = (await response.json()) as OAuthPrepareAuthorizationResponse;
  return data;
}

export async function handleOAuthAuthorizationResponse(
  connector: string,
  code: string,
  state: string
) {
  if (connector === "slack") {
    return handleOAuthSlackAuthorizationResponse(code, state);
  }

  if (connector === "google-drive") {
    return handleOAuthGoogleDriveAuthorizationResponse(code, state);
  }

  return;
}

// server side handler to process the oauth redirect callback
// https://api.slack.com/authentication/oauth-v2#exchanging
export async function handleOAuthSlackAuthorizationResponse(
  code: string,
  state: string
): Promise<OAuthSlackCallbackResponse> {
  const url = `/api/oauth/connector/slack/callback?code=${encodeURIComponent(
    code
  )}&state=${encodeURIComponent(state)}`;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ code, state }),
  });

  if (!response.ok) {
    let errorDetails = `Failed to handle OAuth authorization response: ${response.status}`;

    try {
      const responseBody = await response.text(); // Read the body as text
      errorDetails += `\nResponse Body: ${responseBody}`;
    } catch (err) {
      if (err instanceof Error) {
        errorDetails += `\nUnable to read response body: ${err.message}`;
      } else {
        errorDetails += `\nUnable to read response body: Unknown error type`;
      }
    }

    throw new Error(errorDetails);
  }

  // Parse the JSON response
  const data = (await response.json()) as OAuthSlackCallbackResponse;
  return data;
}

// server side handler to process the oauth redirect callback
// https://api.slack.com/authentication/oauth-v2#exchanging
export async function handleOAuthGoogleDriveAuthorizationResponse(
  code: string,
  state: string
): Promise<OAuthGoogleDriveCallbackResponse> {
  const url = `/api/oauth/connector/google-drive/callback?code=${encodeURIComponent(
    code
  )}&state=${encodeURIComponent(state)}`;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ code, state }),
  });

  if (!response.ok) {
    let errorDetails = `Failed to handle OAuth authorization response: ${response.status}`;

    try {
      const responseBody = await response.text(); // Read the body as text
      errorDetails += `\nResponse Body: ${responseBody}`;
    } catch (err) {
      if (err instanceof Error) {
        errorDetails += `\nUnable to read response body: ${err.message}`;
      } else {
        errorDetails += `\nUnable to read response body: Unknown error type`;
      }
    }

    throw new Error(errorDetails);
  }

  // Parse the JSON response
  const data = (await response.json()) as OAuthGoogleDriveCallbackResponse;
  return data;
}
