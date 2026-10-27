import { render, screen } from "@tests/setup/test-utils";
import { Formik } from "formik";
import ConnectorConfigFields from "@/views/admin/connectors/AddConnectorPage/form/ConnectorConfigFields";
import { useConnectorConfiguration } from "@/lib/connectors/connectors";
import { createConnectorInitialValues } from "@/lib/connectors/utils";
import { ValidSources } from "@/lib/connectors/types/source";
import type { Credential } from "@/lib/credentials/types";

// Field descriptions render as Opal markdown. Under Jest, react-markdown's
// default export loads as a module object, so render the source text as is.
jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }: { children?: string }) => children ?? null,
}));

function credentialWith(json: Record<string, unknown>): Credential<unknown> {
  return { id: 1, credential_json: json } as unknown as Credential<unknown>;
}

// The form shows the translated config, as the add-connector page does.
function DriveFields({
  values,
  currentCredential,
}: {
  values: ReturnType<typeof createConnectorInitialValues>;
  currentCredential: Credential<unknown> | null;
}) {
  const config = useConnectorConfiguration(ValidSources.GoogleDrive);
  return (
    <ConnectorConfigFields
      config={config}
      values={values}
      connector={ValidSources.GoogleDrive}
      currentCredential={currentCredential}
      reportScope={
        currentCredential
          ? { credentialId: currentCredential.id, connectorId: null }
          : null
      }
    />
  );
}

function renderDriveFields(currentCredential: Credential<unknown> | null) {
  const values = createConnectorInitialValues(ValidSources.GoogleDrive);
  render(
    <Formik initialValues={values} onSubmit={() => {}}>
      <DriveFields values={values} currentCredential={currentCredential} />
    </Formik>
  );
}

test("an advanced field hides when its own visibleCondition fails", () => {
  renderDriveFields(credentialWith({ google_tokens: "oauth" }));

  expect(screen.queryByText("Specific User Emails")).not.toBeInTheDocument();
});

test("an advanced field shows when its visibleCondition passes", () => {
  renderDriveFields(credentialWith({ google_service_account_key: "key" }));

  expect(screen.getByText("Specific User Emails")).toBeInTheDocument();
});
