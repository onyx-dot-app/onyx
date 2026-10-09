import { shouldAutoStartSso } from "@/lib/auth/utils";
import type { AuthTypeMetadata, SSOProviderOption } from "@/lib/auth/types";

function provider(name: string): SSOProviderOption {
  return {
    name,
    displayName: name,
    providerType: "OIDC",
    authorizeUrl: `/api/auth/oidc/${name}/authorize`,
  };
}

// Self-hosted deployment where SSO is the only way in.
function ssoOnlyMetadata(
  overrides: Partial<AuthTypeMetadata> = {}
): AuthTypeMetadata {
  return {
    multiTenant: false,
    requiresVerification: false,
    anonymousUserEnabled: false,
    passwordMinLength: 8,
    passwordMaxLength: 64,
    passwordRequireUppercase: false,
    passwordRequireLowercase: false,
    passwordRequireDigit: false,
    passwordRequireSpecialChar: false,
    hasUsers: true,
    oauthEnabled: false,
    passwordAuthEnabled: false,
    ssoProviders: [provider("okta")],
    ...overrides,
  };
}

describe("shouldAutoStartSso", () => {
  test("starts the flow when one provider is the only way in", () => {
    expect(shouldAutoStartSso(ssoOnlyMetadata(), true)).toBe(true);
  });

  test("keeps the button while password login is on", () => {
    expect(
      shouldAutoStartSso(ssoOnlyMetadata({ passwordAuthEnabled: true }), true)
    ).toBe(false);
  });

  test("keeps the buttons when the user has to pick a provider", () => {
    expect(
      shouldAutoStartSso(
        ssoOnlyMetadata({
          ssoProviders: [provider("okta"), provider("entra")],
        }),
        true
      )
    ).toBe(false);
  });

  test("never starts with no provider to start", () => {
    expect(
      shouldAutoStartSso(ssoOnlyMetadata({ ssoProviders: [] }), true)
    ).toBe(false);
    expect(
      shouldAutoStartSso(ssoOnlyMetadata({ ssoProviders: undefined }), true)
    ).toBe(false);
  });

  test("never starts on cloud, where the workspace is not known yet", () => {
    expect(
      shouldAutoStartSso(ssoOnlyMetadata({ multiTenant: true }), true)
    ).toBe(false);
  });

  test("honors the escape hatch", () => {
    expect(shouldAutoStartSso(ssoOnlyMetadata(), false)).toBe(false);
  });

  test("does nothing when the auth metadata failed to load", () => {
    expect(shouldAutoStartSso(null, true)).toBe(false);
  });
});
