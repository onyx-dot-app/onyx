export interface CustomRefreshTokenResponse {
  access_token: string;
  refresh_token: string;
  session: {
    exp: number;
  };
  userinfo: {
    sub: string;
    familyName: string;
    givenName: string;
    fullName: string;
    userId: string;
    email: string;
  };
}

export function mockedRefreshToken(): CustomRefreshTokenResponse {
  /**
   * This function mocks the response from a token refresh endpoint.
   * It generates a mock access token, refresh token, and user information
   * with an expiration time set to 1 hour from now.
   * This is useful for testing or development when the actual refresh endpoint is not available.
   */
  const mockExp = Date.now() + 3600000; // 1 hour from now in milliseconds
  const data: CustomRefreshTokenResponse = {
    access_token: "Mock access token",
    refresh_token: "Mock refresh token",
    session: { exp: mockExp },
    userinfo: {
      sub: "Mock email",
      familyName: "Mock name",
      givenName: "Mock name",
      fullName: "Mock name",
      userId: "Mock User ID",
      email: "email@onyx.app",
    },
  };
  return data;
}

export async function refreshToken(
  customRefreshUrl: string
): Promise<CustomRefreshTokenResponse | null> {
  try {
    console.debug("Sending request to custom refresh URL");
    // support both absolute and relative
    const url = customRefreshUrl.startsWith("http")
      ? new URL(customRefreshUrl)
      : new URL(customRefreshUrl, window.location.origin);
    url.searchParams.append("info", "json");
    url.searchParams.append("access_token_refresh_interval", "3600");

    const response = await fetch(url.toString());
    if (!response.ok) {
      console.error(`Failed to refresh token: ${await response.text()}`);
      return null;
    }

    return await response.json();
  } catch (error) {
    console.error("Error refreshing token:", error);
    throw error;
  }
}
