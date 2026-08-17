import { OAuthDetails } from "@/lib/connectors/credentials";
import {
  CredentialCreationMethod,
  getCredentialCreationMethods,
  shouldRedirectToOAuth,
} from "@/lib/credentials/credentialCreation";

function oauthDetails(
  oauthEnabled: boolean,
  supportsManualCredentials: boolean,
  hasAdditionalFields = false
): OAuthDetails {
  return {
    oauth_enabled: oauthEnabled,
    supports_manual_credentials: supportsManualCredentials,
    additional_kwargs: hasAdditionalFields
      ? [
          {
            name: "domain",
            display_name: "Domain",
            description: "Provider domain",
          },
        ]
      : [],
  };
}

test.each([
  [
    true,
    true,
    [CredentialCreationMethod.OAuth, CredentialCreationMethod.Manual],
  ],
  [true, false, [CredentialCreationMethod.OAuth]],
  [false, true, [CredentialCreationMethod.Manual]],
])(
  "selects credential methods for OAuth=%s and manual=%s",
  (oauthEnabled, supportsManual, expected) => {
    expect(
      getCredentialCreationMethods(oauthDetails(oauthEnabled, supportsManual))
    ).toEqual(expected);
  }
);

test("falls back to manual credentials without OAuth details", () => {
  expect(getCredentialCreationMethods()).toEqual([
    CredentialCreationMethod.Manual,
  ]);
});

test("redirects OAuth providers without additional fields", () => {
  expect(shouldRedirectToOAuth(oauthDetails(true, false))).toBe(true);
  expect(shouldRedirectToOAuth(oauthDetails(true, false, true))).toBe(false);
});
