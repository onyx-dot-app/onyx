import userEvent from "@testing-library/user-event";
import { render, screen } from "@tests/setup/test-utils";
import { Formik } from "formik";
import { RenderField } from "@/views/admin/connectors/AddConnectorPage/form/FieldRendering";
import { connectorConfigs } from "@/lib/connectors/connectors";
import {
  createConnectorInitialValues,
  createConnectorValidationSchema,
} from "@/lib/connectors/utils";
import { ValidSources } from "@/lib/connectors/types/source";

// Field descriptions render as Opal markdown. Under Jest, react-markdown's
// default export loads as a module object, so render the source text as is.
jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }: { children?: string }) => children ?? null,
}));

function ZoomForm() {
  const config = connectorConfigs.zoom;
  return (
    <Formik
      initialValues={createConnectorInitialValues(ValidSources.Zoom)}
      onSubmit={() => {}}
    >
      {({ values }) => (
        <>
          {[...config.values, ...config.advanced_values].map((field) => (
            <RenderField
              key={field.name}
              field={field}
              values={values}
              connector={ValidSources.Zoom}
              currentCredential={null}
            />
          ))}
        </>
      )}
    </Formik>
  );
}

test("every discovery mechanism is on the form at once", () => {
  render(<ZoomForm />);

  for (const label of [
    "Meeting IDs",
    "Webinar IDs",
    "Host Emails",
    "Zoom Group ID",
  ]) {
    expect(screen.getByText(label)).toBeInTheDocument();
  }
});

test("meetings and webinars are both included until the admin unticks one", () => {
  const values = createConnectorInitialValues(ValidSources.Zoom);

  expect(values.include_meetings).toBe(true);
  expect(values.include_webinars).toBe(true);
});

test("the form posts the names the connector takes", () => {
  const names = connectorConfigs.zoom.values.map((field) => field.name);

  expect(names).toEqual([
    "meeting_ids",
    "webinar_ids",
    "host_emails",
    "group_id",
    "include_meetings",
    "include_webinars",
    "plan_tier",
  ]);
});

test("the plan select offers exactly the tiers the backend parses", async () => {
  const user = userEvent.setup();
  render(<ZoomForm />);

  await user.click(screen.getByRole("combobox"));
  expect(
    screen.getAllByRole("option").map((option) => option.textContent)
  ).toEqual(["pro", "business_plus"]);
});

test("the rate limit share is an advanced number field", () => {
  render(<ZoomForm />);

  const rateLimit = screen.getByLabelText(/Zoom API Rate Limit/);
  expect(rateLimit).toHaveAttribute("id", "rate_limit_percent");
  // Connector number fields allow -1, so the pattern takes a leading minus.
  expect(rateLimit).toHaveAttribute("pattern", "-?[0-9]*");
});

test("the plan has to be chosen", async () => {
  const schema = createConnectorValidationSchema(ValidSources.Zoom);
  const filled = {
    ...createConnectorInitialValues(ValidSources.Zoom),
    name: "zoom",
    meeting_ids: ["111"],
  };

  await expect(schema.validate(filled)).rejects.toThrow(
    "Zoom Plan is required"
  );
  await expect(
    schema.validate({ ...filled, plan_tier: "pro" })
  ).resolves.toBeTruthy();
});
