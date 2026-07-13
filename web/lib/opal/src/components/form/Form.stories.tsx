import type { Meta, StoryObj } from "@storybook/react";
import { Formik, Form } from "formik";
import {
  FormField,
  FormikField,
  InputTypeIn,
  InputTypeInField,
  CheckboxField,
  LabeledCheckboxField,
  SwitchField,
} from "@opal/components";

const meta: Meta = {
  title: "opal/components/Form",
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj;

// Presentational FormField, driven directly by the `state` prop with no Formik.
function FieldPreview({ state }: { state: "idle" | "success" | "error" }) {
  return (
    <FormField state={state} required className="w-80">
      <FormField.Label required>Email</FormField.Label>
      <FormField.Description>
        {"We only use this to send account notifications."}
      </FormField.Description>
      <FormField.Control>
        <InputTypeIn
          placeholder="you@example.com"
          value={state === "idle" ? "" : "ada@onyx.app"}
          onChange={() => {}}
        />
      </FormField.Control>
      <FormField.Message
        messages={{
          error: "Enter a valid email address.",
          success: "Looks good.",
          idle: "",
        }}
      />
    </FormField>
  );
}

export const Idle: Story = {
  render: () => <FieldPreview state="idle" />,
};

export const Error: Story = {
  render: () => <FieldPreview state="error" />,
};

export const Success: Story = {
  render: () => <FieldPreview state="success" />,
};

// Full Formik integration. FormikField wires validation state into FormField,
// and InputTypeInField binds the input to formik. Blur the field to validate.
export const FormikIntegration: Story = {
  render: () => (
    <Formik
      initialValues={{ email: "" }}
      validate={(values) =>
        values.email.includes("@") ? {} : { email: "Enter a valid email." }
      }
      onSubmit={() => {}}
    >
      <Form className="w-80">
        <FormikField
          name="email"
          render={(_field, _helper, meta, state) => (
            <FormField state={state} required>
              <FormField.Label required>Email</FormField.Label>
              <FormField.Control>
                <InputTypeInField name="email" placeholder="you@example.com" />
              </FormField.Control>
              <FormField.Message
                messages={{ error: meta.error ?? "", idle: "" }}
              />
            </FormField>
          )}
        />
      </Form>
    </Formik>
  ),
};

export const Toggles: Story = {
  render: () => (
    <Formik
      initialValues={{ terms: false, notify: true, beta: false }}
      onSubmit={() => {}}
    >
      <Form className="flex flex-col gap-y-4 w-80">
        <div className="flex items-center gap-x-2">
          <CheckboxField name="terms" />
          <span className="font-secondary-body text-text-04">
            {"I accept the terms"}
          </span>
        </div>
        <LabeledCheckboxField
          name="notify"
          label="Email notifications"
          sublabel="Get notified when a document changes."
        />
        <div className="flex items-center justify-between">
          <span className="font-main-ui-action text-text-04">
            {"Enable beta features"}
          </span>
          <SwitchField name="beta" />
        </div>
      </Form>
    </Formik>
  ),
};
