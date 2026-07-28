import type { Credential } from "@/lib/connectors/credentials";
import { ValidSources } from "@/lib/types";

import {
  canEditCredentialWithForm,
  createInitialValues,
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
