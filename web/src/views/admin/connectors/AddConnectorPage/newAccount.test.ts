import { connectorConfigs } from "@/lib/connectors/connectors";
import { ValidSources } from "@/lib/connectors/types/source";
import { connectorConfigFromForm } from "@/lib/connectors/utils";
import type { CredentialValidationMessages } from "@/lib/credentials/types";
import {
  NEW_ACCOUNT_FIELD,
  initialNewAccountValues,
  newAccountSchema,
  typedAccountSpec,
  typedDraft,
} from "@/views/admin/connectors/AddConnectorPage/newAccount";

const MESSAGES: CredentialValidationMessages = {
  fieldTitle: (key) => key,
  required: (field) => `${field} is required`,
  empty: (field) => `${field} is empty`,
  invalidEmail: (field) => `${field} is not an email`,
  fileRequired: (field) => `${field} needs a file`,
  authMethodRequired: "Pick a method",
};

test("a new account gets the realm, and the connector config does not", () => {
  const source = ValidSources.Zendesk;
  const spec = typedAccountSpec(source);
  if (spec === null) throw new Error("Zendesk takes a typed account");
  const formValues: Record<string, unknown> = {
    zendesk_subdomain: " acme ",
    content_type: "articles",
    [NEW_ACCOUNT_FIELD]: {
      ...initialNewAccountValues(spec),
      zendesk_email: "admin@acme.com",
      zendesk_token: "token",
    },
  };

  const draft = typedDraft(
    source,
    newAccountSchema(spec, MESSAGES),
    formValues
  );

  expect(draft?.credential_json).toEqual({
    zendesk_email: "admin@acme.com",
    zendesk_token: "token",
    zendesk_subdomain: "acme",
  });
  expect(
    connectorConfigFromForm(
      source,
      connectorConfigs[source],
      formValues,
      new Set([NEW_ACCOUNT_FIELD])
    )
  ).toEqual({ content_type: "articles" });
});
