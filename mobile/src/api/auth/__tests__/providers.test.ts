import { describe, expect, it } from "@jest/globals";

import { visibleProviders } from "@/api/auth/providers";
import type { AuthTypeMetadata } from "@/api/types";

function config(
  multi_tenant: boolean,
  oauth_enabled: boolean,
): AuthTypeMetadata {
  return {
    multi_tenant,
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

  it("shows only password for a self-hosted instance without oauth creds", () => {
    expect(ids(config(false, false))).toEqual(["password"]);
  });

  it("shows password and Google for cloud", () => {
    expect(ids(config(true, true))).toEqual(["password", "google"]);
  });

  it("shows password and Google for a self-hosted instance with oauth creds", () => {
    expect(ids(config(false, true))).toEqual(["password", "google"]);
  });

  it("marks Google as a browser provider with an authorize path", () => {
    const google = visibleProviders(config(true, true)).find(
      (provider) => provider.id === "google",
    );
    expect(google?.kind).toBe("browser");
    expect(google?.authorizePath).toBe("/auth/mobile/oauth/authorize");
  });
});
