import {
  OAuthBaseCallbackResponse,
  OAuthConfluenceFinalizeResponse,
  OAuthConfluencePrepareFinalizationResponse,
  OAuthPrepareAuthorizationResponse,
  OAuthSlackCallbackResponse,
} from "./types";

// server side handler to help initiate the oauth authorization request
export async function prepareOAuthAuthorizationRequest(
  connector: string,
  finalRedirect: string | null // a redirect (not the oauth redirect) for the user to return to after oauth is complete)
): Promise<OAuthPrepareAuthorizationResponse> {
  let url: string;
  let method: string;
  let body: any;

  // For Linear, use the standard OAuth flow
  if (connector === "linear") {
    url = `/api/connector/oauth/authorize/${connector}`;
    if (finalRedirect) {
      url += `?desired_return_url=${encodeURIComponent(finalRedirect)}`;
    }
    method = "GET";
    body = undefined;
  } else {
    // For other connectors, use the ee OAuth flow
    url = `/api/oauth/prepare-authorization-request?connector=${encodeURIComponent(
      connector
    )}`;

    // Conditionally append the `redirect_on_success` parameter
    if (finalRedirect) {
      url += `&redirect_on_success=${encodeURIComponent(finalRedirect)}`;
    }

    method = "POST";
    body = JSON.stringify({
      connector: connector,
      redirect_on_success: finalRedirect,
    });
  }

  const response = await fetch(url, {
    method: method,
    headers: body
      ? {
          "Content-Type": "application/json",
        }
      : undefined,
    body: body,
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

  if (connector === "confluence") {
    return handleOAuthConfluenceAuthorizationResponse(code, state);
  }

  if (connector === "linear") {
    return handleOAuthLinearAuthorizationResponse(code, state);
  }

  return;
}

// Handler for federated connector OAuth callbacks
export async function handleFederatedOAuthCallback(
  federatedConnectorId: string,
  code: string,
  state: string
): Promise<OAuthBaseCallbackResponse> {
  // Use the generic callback endpoint - the connector ID will be extracted from the state parameter
  const url = `/api/federated/callback?code=${encodeURIComponent(
    code
  )}&state=${encodeURIComponent(state)}`;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    const requestId = response.headers.get("x-request-id") || "n/a";
    const statusText = response.statusText || "Unknown";
    throw new Error(
      `Failed to handle federated OAuth callback: ${response.status} ${statusText} (req: ${requestId})`
    );
  }

  // Parse the JSON response and extract the data field
  const result = await response.json();

  if (!result.success) {
    throw new Error(result.message || "OAuth callback failed");
  }

  return {
    success: true,
    message: result.message || "OAuth authorization successful",
    redirect_on_success: `/admin/federated/${federatedConnectorId}`,
    finalize_url: null,
  };
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
    const requestId = response.headers.get("x-request-id") || "n/a";
    const statusText = response.statusText || "Unknown";
    throw new Error(
      `Failed to handle OAuth Slack authorization response: ${response.status} ${statusText} (req: ${requestId})`
    );
  }

  // Parse the JSON response
  const data = (await response.json()) as OAuthSlackCallbackResponse;
  return data;
}

export async function handleOAuthGoogleDriveAuthorizationResponse(
  code: string,
  state: string
): Promise<OAuthBaseCallbackResponse> {
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
    const requestId = response.headers.get("x-request-id") || "n/a";
    const statusText = response.statusText || "Unknown";
    throw new Error(
      `Failed to handle OAuth Google Drive authorization response: ${response.status} ${statusText} (req: ${requestId})`
    );
  }

  // Parse the JSON response
  const data = (await response.json()) as OAuthBaseCallbackResponse;
  return data;
}

// call server side helper
// https://developer.atlassian.com/cloud/confluence/oauth-2-3lo-apps
export async function handleOAuthConfluenceAuthorizationResponse(
  code: string,
  state: string
): Promise<OAuthBaseCallbackResponse> {
  const url = `/api/oauth/connector/confluence/callback?code=${encodeURIComponent(
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
    const requestId = response.headers.get("x-request-id") || "n/a";
    const statusText = response.statusText || "Unknown";
    throw new Error(
      `Failed to handle OAuth Confluence authorization response: ${response.status} ${statusText} (req: ${requestId})`
    );
  }

  // Parse the JSON response
  const data = (await response.json()) as OAuthBaseCallbackResponse;
  return data;
}

export async function handleOAuthPrepareFinalization(
  connector: string,
  credential: number
) {
  if (connector === "confluence") {
    return handleOAuthConfluencePrepareFinalization(credential);
  }

  return;
}

// call server side helper
// https://developer.atlassian.com/cloud/confluence/oauth-2-3lo-apps
export async function handleOAuthConfluencePrepareFinalization(
  credential: number
): Promise<OAuthConfluencePrepareFinalizationResponse> {
  const url = `/api/oauth/connector/confluence/accessible-resources?credential_id=${encodeURIComponent(
    credential
  )}`;

  const response = await fetch(url, {
    method: "GET",
  });

  if (!response.ok) {
    const requestId = response.headers.get("x-request-id") || "n/a";
    const statusText = response.statusText || "Unknown";
    throw new Error(
      `Failed to handle OAuth Confluence prepare finalization response: ${response.status} ${statusText} (req: ${requestId})`
    );
  }

  // Parse the JSON response
  const data =
    (await response.json()) as OAuthConfluencePrepareFinalizationResponse;
  return data;
}

export async function handleOAuthConfluenceFinalize(
  credential_id: number,
  cloud_id: string,
  cloud_name: string,
  cloud_url: string
): Promise<OAuthConfluenceFinalizeResponse> {
  const url = `/api/oauth/connector/confluence/finalize?credential_id=${encodeURIComponent(
    credential_id
  )}&cloud_id=${encodeURIComponent(cloud_id)}&cloud_name=${encodeURIComponent(
    cloud_name
  )}&cloud_url=${encodeURIComponent(cloud_url)}`;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    const requestId = response.headers.get("x-request-id") || "n/a";
    const statusText = response.statusText || "Unknown";
    throw new Error(
      `Failed to handle OAuth Confluence finalization response: ${response.status} ${statusText} (req: ${requestId})`
    );
  }

  // Parse the JSON response
  const data = (await response.json()) as OAuthConfluenceFinalizeResponse;
  return data;
}

export async function handleOAuthLinearAuthorizationResponse(
  code: string,
  state: string
): Promise<OAuthBaseCallbackResponse> {
  const url = `/api/connector/oauth/callback/linear?code=${encodeURIComponent(
    code
  )}&state=${encodeURIComponent(state)}`;

  const response = await fetch(url, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    const requestId = response.headers.get("x-request-id") || "n/a";
    const statusText = response.statusText || "Unknown";
    throw new Error(
      `Failed to handle OAuth Linear authorization response: ${response.status} ${statusText} (req: ${requestId})`
    );
  }

  // Backend returns { redirect_url: string }; adapt to OAuthBaseCallbackResponse
  const raw = (await response.json()) as { redirect_url?: string };
  if (!raw || !raw.redirect_url) {
    throw new Error(
      "Invalid OAuth Linear callback response: missing redirect_url"
    );
  }

  return {
    success: true,
    message: "OAuth authorization successful",
    finalize_url: null,
    redirect_on_success: raw.redirect_url,
  };
}
