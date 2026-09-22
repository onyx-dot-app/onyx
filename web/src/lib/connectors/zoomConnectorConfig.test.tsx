import { render, screen } from "@tests/setup/test-utils";
import { Formik } from "formik";
import { RenderField } from "@/app/admin/connectors/[connector]/pages/FieldRendering";
import {
  connectorConfigs,
  createConnectorInitialValues,
  createConnectorValidationSchema,
} from "@/lib/connectors/connectors";
import { ValidSources } from "@/lib/types";

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

test("link access counts as public until the admin unticks it", () => {
  // Off leaves nearly every transcript readable by its owner alone.
  const values = createConnectorInitialValues(ValidSources.Zoom);

  expect(values.treat_link_access_as_public).toBe(true);
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
    "treat_link_access_as_public",
    "plan_tier",
  ]);
});

test("the plan select offers exactly the tiers the backend parses", () => {
  render(<ZoomForm />);

  const plan = screen.getByRole("combobox");
  expect(
    [...plan.querySelectorAll("option")].map((option) => option.value)
  ).toEqual(["", "pro", "business_plus"]);
});

test("the rate limit share is an advanced number field", () => {
  render(<ZoomForm />);

  const rateLimit = screen.getByRole("spinbutton");
  expect(rateLimit).toHaveAttribute("name", "rate_limit_percent");
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
