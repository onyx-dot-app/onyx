import { describe, expect, it } from "@jest/globals";

import { visibleProviders } from "@/api/auth/providers";
import type { AuthType, AuthTypeMetadata } from "@/api/types";

function config(auth_type: AuthType, oauth_enabled: boolean): AuthTypeMetadata {
  return {
    auth_type,
    requires_verification: false,
    password_min_length: 8,
    has_users: true,
    oauth_enabled,
  };
}

function ids(metadata: AuthTypeMetadata | undefined): string[] {
  return visibleProviders(metadata).map((provider) => provider.id);
}

describe("visibleProviders", () => {
  it("returns nothing until the config loads", () => {
    expect(visibleProviders(undefined)).toEqual([]);
  });

  it("shows only password for a basic instance", () => {
    expect(ids(config("basic", false))).toEqual(["password"]);
  });

  it("shows password and Google for cloud", () => {
    expect(ids(config("cloud", true))).toEqual(["password", "google"]);
  });

  it("shows only Google for a google_oauth-only instance", () => {
    expect(ids(config("google_oauth", true))).toEqual(["google"]);
  });

  it("hides Google when oauth is disabled even on a Google auth_type", () => {
    expect(ids(config("google_oauth", false))).toEqual([]);
  });

  it("shows nothing for SSO types not yet supported on mobile", () => {
    expect(ids(config("saml", true))).toEqual([]);
    expect(ids(config("oidc", true))).toEqual([]);
  });

  it("marks Google as a browser provider with an authorize path", () => {
    const google = visibleProviders(config("cloud", true)).find(
      (provider) => provider.id === "google",
    );
    expect(google?.kind).toBe("browser");
    expect(google?.authorizePath).toBe("/auth/mobile/oauth/authorize");
  });
});
