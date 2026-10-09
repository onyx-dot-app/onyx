import { render, waitFor } from "@tests/setup/test-utils";
import { Formik } from "formik";
import { CredentialDerivedConfig } from "@/views/admin/connectors/AddConnectorPage/form/CredentialDerivedConfig";
import { connectorConfigs } from "@/lib/connectors/connectors";
import { connectorFormState } from "@/lib/connectors/checks/formState";
import { createConnectorInitialValues } from "@/lib/connectors/utils";
import { ValidSources } from "@/lib/connectors/types/source";
import type { Credential } from "@/lib/credentials/types";

function credentialWith(json: Record<string, unknown>): Credential<unknown> {
  return { id: 1, credential_json: json } as unknown as Credential<unknown>;
}

function renderDriveForm(credential: Credential<unknown> | null): {
  values: () => Record<string, unknown>;
  rerender: (credential: Credential<unknown> | null) => void;
} {
  let latestValues: Record<string, unknown> = {};
  const tree = (current: Credential<unknown> | null) => (
    <Formik
      initialValues={createConnectorInitialValues(ValidSources.GoogleDrive)}
      onSubmit={() => {}}
    >
      {(props) => {
        latestValues = props.values;
        return (
          <CredentialDerivedConfig
            configuration={connectorConfigs.google_drive}
            credential={current}
          />
        );
      }}
    </Formik>
  );
  const { rerender } = render(tree(credential));
  return {
    values: () => latestValues,
    rerender: (next) => rerender(tree(next)),
  };
}

test("the Drive form takes the credential kind from the picked credential", async () => {
  const form = renderDriveForm(
    credentialWith({ google_service_account_key: "****" })
  );

  await waitFor(() =>
    expect(form.values().credential_kind).toBe("service_account")
  );
  // The checks send it, though the field is hidden.
  expect(
    connectorFormState(connectorConfigs.google_drive, form.values())
      .credential_kind
  ).toBe("service_account");
});

test("a credential swap updates the credential kind", async () => {
  const form = renderDriveForm(
    credentialWith({ google_service_account_key: "****" })
  );
  await waitFor(() =>
    expect(form.values().credential_kind).toBe("service_account")
  );

  form.rerender(credentialWith({ google_tokens: "****" }));

  await waitFor(() => expect(form.values().credential_kind).toBe("oauth"));
});

test("without a credential the kind is not sent", async () => {
  const form = renderDriveForm(null);

  await waitFor(() =>
    expect(
      connectorFormState(connectorConfigs.google_drive, form.values())
    ).not.toHaveProperty("credential_kind")
  );
});
