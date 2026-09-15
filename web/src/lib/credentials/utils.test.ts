import {
  credentialTemplates,
  type Credential,
} from "@/lib/connectors/credentials";
import { ValidSources } from "@/lib/types";

import {
  canEditCredentialWithForm,
  createInitialValues,
  createValidationSchema,
  getEditableCredentialFields,
} from "@/lib/credentials/utils";

function buildCredential(
  credential: Partial<Credential<Record<string, unknown>>>
): Credential<Record<string, unknown>> {
  return {
    id: 1,
    credential_json: {},
    admin_public: true,
    source: ValidSources.Jira,
    user_id: null,
    user_email: null,
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

describe("createValidationSchema", () => {
  const schema = createValidationSchema(
    credentialTemplates[ValidSources.Outlook]
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

  it("accepts a complete form and ignores the other method's fields", () => {
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
});
