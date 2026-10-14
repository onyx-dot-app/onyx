import { CREDENTIAL_SPECS } from "@/lib/credentials/constants";
import type { Credential } from "@/lib/credentials/types";
import type { CredentialFieldValues } from "@/lib/credentials/types";
import { ValidSources } from "@/lib/connectors/types/source";

import {
  canEditCredentialWithForm,
  createInitialValues,
  createValidationSchema,
  getCredentialCreationMethods,
  getEditableCredentialFields,
  shouldRedirectToOAuth,
  bindingCheckCredentialId,
  credentialMatchesBoundFields,
  toCredentialRequest,
} from "@/lib/credentials/utils";
import {
  CredentialCreationMethod,
  type CredentialValidationMessages,
  type OAuthDetails,
} from "@/lib/credentials/types";

function buildCredential(
  credential: Partial<Credential<CredentialFieldValues>>
): Credential<CredentialFieldValues> {
  return {
    id: 1,
    credential_json: {},
    admin_public: true,
    source: ValidSources.Jira,
    user_id: null,
    user_email: null,
    user_personal_name: null,
    time_created: "2026-01-01T00:00:00Z",
    time_updated: "2026-01-01T00:00:00Z",
    ...credential,
  };
}

describe("credential edit helpers", () => {
  it("includes optional template fields omitted from stored credential json", () => {
    const credential = buildCredential({
      credential_json: {
        jira_api_token: "masked-token",
        stored_uneditable_key: "should-not-render",
      },
      source: ValidSources.Jira,
    });

    const editableFields = getEditableCredentialFields(
      credential,
      ValidSources.Jira
    );

    expect(editableFields).toEqual({
      jira_user_email: null,
      jira_api_token: "masked-token",
    });
    expect(createInitialValues(credential, editableFields)).toMatchObject({
      name: "",
      jira_user_email: "",
      jira_api_token: "",
    });
  });

  it("uses fields from the stored auth method for multi-auth templates", () => {
    const credential = buildCredential({
      credential_json: {
        authentication_method: "iam_role",
      },
      source: ValidSources.S3,
    });

    const editableFields = getEditableCredentialFields(
      credential,
      ValidSources.S3
    );

    expect(editableFields).toEqual({
      authentication_method: "iam_role",
      aws_role_arn: "",
    });
  });

  it("restores the legacy OneDrive certificate auth method", () => {
    const credential = buildCredential({
      credential_json: {
        onedrive_authentication_method: "certificate",
        onedrive_client_id: "client-id",
        onedrive_directory_id: "directory-id",
        onedrive_private_key: "masked-certificate",
      },
      source: ValidSources.OneDrive,
    });

    expect(
      getEditableCredentialFields(credential, ValidSources.OneDrive)
    ).toEqual({
      authentication_method: "certificate",
      onedrive_client_id: "client-id",
      onedrive_directory_id: "directory-id",
      onedrive_certificate_password: "",
      onedrive_private_key: "masked-certificate",
    });
  });

  it("does not expose OAuth-managed credential internals in the edit form", () => {
    const credential = buildCredential({
      credential_json: {
        access_token: "oauth-access-token",
        refresh_token: "oauth-refresh-token",
        expires_at: "2026-01-01T01:00:00Z",
      },
      source: ValidSources.Linear,
    });

    expect(
      getEditableCredentialFields(credential, ValidSources.Linear)
    ).toEqual({});
    expect(canEditCredentialWithForm(credential, ValidSources.Linear)).toBe(
      false
    );
  });
});

const MESSAGES: CredentialValidationMessages = {
  fieldTitle: (key) => key,
  required: (field) => `required: ${field}`,
  empty: (field) => `empty: ${field}`,
  invalidEmail: (field) => `invalid email: ${field}`,
  fileRequired: (field) => `file required: ${field}`,
  authMethodRequired: "auth method required",
};

describe("createValidationSchema", () => {
  const schema = createValidationSchema(
    CREDENTIAL_SPECS[ValidSources.Outlook],
    MESSAGES
  );
  const ids = {
    outlook_client_id: "client-id",
    outlook_directory_id: "directory-id",
  };

  it("requires the fields both auth methods share under each of them", () => {
    expect(
      schema.isValidSync({
        authentication_method: "client_secret",
        outlook_client_secret: "secret",
      })
    ).toBe(false);
    expect(
      schema.isValidSync({
        authentication_method: "certificate",
        outlook_certificate_password: "pass",
        outlook_private_key: {},
      })
    ).toBe(false);
  });

  it("accepts a complete form without the other method's fields", () => {
    expect(
      schema.isValidSync({
        ...ids,
        authentication_method: "client_secret",
        outlook_client_secret: "secret",
      })
    ).toBe(true);
    expect(
      schema.isValidSync({
        ...ids,
        authentication_method: "certificate",
        outlook_certificate_password: "pass",
        outlook_private_key: {},
      })
    ).toBe(true);
  });

  it("requires the SharePoint app ids under both of its methods", () => {
    const sharepointSchema = createValidationSchema(
      CREDENTIAL_SPECS[ValidSources.Sharepoint],
      MESSAGES
    );
    const sharepointIds = {
      sp_client_id: "client-id",
      sp_directory_id: "directory-id",
    };

    expect(
      sharepointSchema.isValidSync({
        authentication_method: "client_secret",
        sp_client_secret: "secret",
      })
    ).toBe(false);
    expect(
      sharepointSchema.isValidSync({
        authentication_method: "certificate",
        sp_certificate_password: "pass",
        sp_private_key: {},
      })
    ).toBe(false);
    expect(
      sharepointSchema.isValidSync({
        ...sharepointIds,
        authentication_method: "client_secret",
        sp_client_secret: "secret",
      })
    ).toBe(true);
    expect(
      sharepointSchema.isValidSync({
        ...sharepointIds,
        authentication_method: "certificate",
        sp_certificate_password: "pass",
        sp_private_key: {},
      })
    ).toBe(true);
  });
});

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

describe("naming a credential in a request", () => {
  const values = { api_token: "token" };
  const typed = { credential_json: values };
  const saved = { credential_id: 7, sent_values: JSON.stringify(values) };

  it("sends a typed account's values until a run saves a draft", () => {
    expect(toCredentialRequest(typed, null)).toEqual(typed);
    expect(bindingCheckCredentialId(typed, null)).toBeNull();
  });

  it("names the draft alone while it holds the values", () => {
    expect(toCredentialRequest(typed, saved)).toEqual({ credential_id: 7 });
    expect(bindingCheckCredentialId(typed, saved)).toBe(7);
  });

  it("sends changed values with the draft, and no binding check names it", () => {
    const changed = { credential_json: { api_token: "other" } };
    expect(toCredentialRequest(changed, saved)).toEqual({
      credential_id: 7,
      credential_json: changed.credential_json,
    });
    expect(bindingCheckCredentialId(changed, saved)).toBeNull();
  });

  it("names a saved credential by its id", () => {
    expect(toCredentialRequest({ credential_id: 3 }, saved)).toEqual({
      credential_id: 3,
    });
    expect(bindingCheckCredentialId({ credential_id: 3 }, saved)).toBe(3);
  });
});

describe("credentialMatchesBoundFields", () => {
  // GitHub's realm is optional and defaults to github.com.
  const github = CREDENTIAL_SPECS.github.fields;
  const at = (url: string) => ({ github_base_url: url });
  const matches = (
    credentialJson: Record<string, unknown>,
    formValues: Record<string, unknown>
  ) =>
    credentialMatchesBoundFields(
      ["github_base_url"],
      github,
      credentialJson,
      formValues
    );

  it("restricts nothing while the field is empty", () => {
    expect(matches(at("https://a.com"), {})).toBe(true);
    expect(matches(at("https://a.com"), at(" "))).toBe(true);
  });

  it("matches without case, scheme or a trailing slash", () => {
    expect(matches(at("https://A.com/"), at("a.com"))).toBe(true);
    expect(matches(at("https://b.com"), at("https://a.com"))).toBe(false);
  });

  it("reads an account without its own realm as the default", () => {
    expect(matches({}, at("https://github.com"))).toBe(true);
    expect(matches({}, at("https://a.com"))).toBe(false);
  });

  it("matches a pasted host to a stored subdomain", () => {
    expect(
      credentialMatchesBoundFields(
        ["zendesk_subdomain"],
        CREDENTIAL_SPECS.zendesk.fields,
        { zendesk_subdomain: "acme" },
        { zendesk_subdomain: "https://acme.zendesk.com" }
      )
    ).toBe(true);
  });

  it("compares a bound field the account stores, like an OAuth site", () => {
    const site = (url: string) => ({ wiki_base: url });
    const confluence = CREDENTIAL_SPECS.confluence.fields;
    expect(
      credentialMatchesBoundFields(
        ["wiki_base"],
        confluence,
        site("https://a.atlassian.net/wiki"),
        site("https://b.atlassian.net/wiki")
      )
    ).toBe(false);
    // An API-token account stores no site, so it cannot tell.
    expect(
      credentialMatchesBoundFields(
        ["wiki_base"],
        confluence,
        {},
        site("https://b.atlassian.net/wiki")
      )
    ).toBe(true);
  });
});
