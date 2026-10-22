/**
 * The mounted checks card starts a run only from Start Checks or Re-run
 * Checks: a form change after a run flags the change and waits.
 */
import { Formik, useFormikContext, type FormikContextType } from "formik";
import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import CredentialChecksCard from "@/views/admin/connectors/AddConnectorPage/components/CredentialChecksCard";
import {
  fetchDraftCheckPlan,
  startDraftCheckRun,
} from "@/lib/connectors/checks/svc";
import type {
  DraftCheckRunSnapshot,
  DraftCheckState,
} from "@/lib/connectors/checks/types";
import { ValidSources } from "@/lib/connectors/types/source";

jest.mock("@/lib/connectors/checks/svc", () => ({
  startDraftCheckRun: jest.fn(),
  startPairEditCheckRun: jest.fn(),
  fetchDraftCheckPlan: jest.fn(),
  cancelDraftCheckRun: jest.fn(async () => undefined),
}));
// A run fetch returns what the latest start request returned.
jest.mock("@/lib/fetcher", () => ({
  errorHandlingFetcher: jest.fn(async () => {
    const { startDraftCheckRun } = jest.requireMock(
      "@/lib/connectors/checks/svc"
    );
    return startDraftCheckRun.mock.results.at(-1)?.value;
  }),
}));
// No credential-bound fields, and every form value is part of what a run checks.
jest.mock("@/lib/connectors/connectors", () => ({
  useConnectorConfiguration: () => ({ values: [], advanced_values: [] }),
}));
jest.mock("@/lib/connectors/utils", () => ({
  splitCredentialBoundFields: () => ({ values: [], advancedValues: [] }),
}));
jest.mock("@/lib/connectors/checks/formState", () => ({
  connectorFormState: (
    _source: unknown,
    _configuration: unknown,
    values: unknown
  ) => values,
}));
jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ appName: "Onyx" }),
}));

const startMock = startDraftCheckRun as jest.MockedFunction<
  typeof startDraftCheckRun
>;
const planMock = fetchDraftCheckPlan as jest.MockedFunction<
  typeof fetchDraftCheckPlan
>;

const SIGN_IN: DraftCheckState = {
  check_id: "sign_in",
  display_name: "Sign in",
  capability: "indexing",
  required: true,
  state: "pending",
  message: "",
  missing_fields: [],
  invalid_fields: [],
  remediation: null,
  docs_link: null,
  duration_ms: null,
  from_cache: false,
  validates_binding: true,
  findings: [],
};

const PASSED_RUN: DraftCheckRunSnapshot = {
  run_id: "run-1",
  draft_key: "draft",
  source: ValidSources.Confluence,
  credential_id: 1,
  access_type: "public",
  status: "completed",
  form_errors: {},
  unknown_fields: [],
  checks: [{ ...SIGN_IN, state: "passed", duration_ms: 1 }],
};

let form: FormikContextType<Record<string, unknown>> | null = null;

function FormProbe() {
  form = useFormikContext<Record<string, unknown>>();
  return null;
}

function renderCard() {
  return render(
    <Formik initialValues={{}} onSubmit={() => {}}>
      <>
        <FormProbe />
        <CredentialChecksCard
          source={ValidSources.Confluence}
          credential={{ credential_id: 1 }}
          locked={false}
        />
      </>
    </Formik>
  );
}

beforeEach(() => {
  form = null;
  startMock.mockReset();
  planMock.mockReset();
  planMock.mockResolvedValue({
    source: ValidSources.Confluence,
    access_type: "public",
    form_errors: {},
    unknown_fields: [],
    checks: [SIGN_IN],
  });
  startMock.mockResolvedValue(PASSED_RUN);
});

it("starts no run when a field changes after a run, until Re-run Checks", async () => {
  const user = setupUser();
  renderCard();

  await user.click(await screen.findByRole("button", { name: "Start Checks" }));
  await waitFor(() => expect(startMock).toHaveBeenCalledTimes(1));
  await screen.findByText("1 successful");

  await act(() => form!.setFieldValue("include_comments", true));

  expect(await screen.findByText("Settings changed")).toBeInTheDocument();
  expect(startMock).toHaveBeenCalledTimes(1);

  await user.click(screen.getByRole("button", { name: "Re-run Checks" }));
  await waitFor(() => expect(startMock).toHaveBeenCalledTimes(2));
  // A re-run after a change reuses the cached results of unchanged checks.
  expect(startMock.mock.calls[1]?.[0]).toMatchObject({
    form_state: { include_comments: true },
    rerun: "none",
  });
  await waitFor(() =>
    expect(screen.queryByText("Settings changed")).not.toBeInTheDocument()
  );
});
