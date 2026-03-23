/**
 * Stories for Formik-connected form field components.
 *
 * All these components call `useField` from Formik internally, so every story
 * wraps the component in a minimal `<Formik>` provider. The forms are
 * non-submitting; they exist purely to demonstrate the field UI.
 *
 * Components covered:
 * - CheckboxField (unlabeled, from CheckboxField.tsx)
 * - LabeledCheckboxField (from LabeledCheckboxField.tsx)
 * - SwitchField
 * - InputTypeInField
 * - InputTextAreaField
 * - InputSelectField
 * - InputDatePickerField
 * - PasswordInputTypeInField
 */

import type { Meta, StoryObj } from "@storybook/react";
import { Formik, Form } from "formik";
import React from "react";

import UnlabeledCheckboxField from "./CheckboxField";
import { CheckboxField as LabeledCheckboxField } from "./LabeledCheckboxField";
import SwitchField from "./SwitchField";
import InputTypeInField from "./InputTypeInField";
import InputTextAreaField from "./InputTextAreaField";
import InputSelectField from "./InputSelectField";
import InputDatePickerField from "./InputDatePickerField";
import PasswordInputTypeInField from "./PasswordInputTypeInField";
import InputSelect from "@/refresh-components/inputs/InputSelect";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Minimal Formik wrapper that never submits. */
function FormikWrapper({
  initialValues,
  children,
}: {
  initialValues: Record<string, unknown>;
  children: React.ReactNode;
}) {
  return (
    <Formik initialValues={initialValues} onSubmit={() => {}}>
      <Form
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 16,
          maxWidth: 400,
        }}
      >
        {children}
      </Form>
    </Formik>
  );
}

// ---------------------------------------------------------------------------
// Meta (we use a dummy component since this file covers multiple components)
// ---------------------------------------------------------------------------

const meta: Meta = {
  title: "refresh-components/form/FormikFields",
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj;

// ---------------------------------------------------------------------------
// CheckboxField (unlabeled)
// ---------------------------------------------------------------------------

export const Checkbox: Story = {
  name: "CheckboxField (unlabeled)",
  render: () => (
    <FormikWrapper initialValues={{ agree: false }}>
      <UnlabeledCheckboxField name="agree" />
    </FormikWrapper>
  ),
};

// ---------------------------------------------------------------------------
// LabeledCheckboxField
// ---------------------------------------------------------------------------

export const LabeledCheckbox: Story = {
  name: "LabeledCheckboxField",
  render: () => (
    <FormikWrapper initialValues={{ terms: false }}>
      <LabeledCheckboxField
        name="terms"
        label="I agree to the terms and conditions"
        sublabel="You must accept before continuing."
      />
    </FormikWrapper>
  ),
};

export const LabeledCheckboxWithTooltip: Story = {
  name: "LabeledCheckboxField with tooltip",
  render: () => (
    <FormikWrapper initialValues={{ newsletter: true }}>
      <LabeledCheckboxField
        name="newsletter"
        label="Subscribe to newsletter"
        tooltip="We send at most one email per week."
      />
    </FormikWrapper>
  ),
};

// ---------------------------------------------------------------------------
// SwitchField
// ---------------------------------------------------------------------------

export const Switch: Story = {
  name: "SwitchField",
  render: () => (
    <FormikWrapper initialValues={{ notifications: true }}>
      <label htmlFor="notifications" style={{ fontWeight: 500 }}>
        Enable notifications
      </label>
      <SwitchField name="notifications" />
    </FormikWrapper>
  ),
};

// ---------------------------------------------------------------------------
// InputTypeInField
// ---------------------------------------------------------------------------

export const TextInput: Story = {
  name: "InputTypeInField",
  render: () => (
    <FormikWrapper initialValues={{ username: "" }}>
      <InputTypeInField name="username" placeholder="Enter your username" />
    </FormikWrapper>
  ),
};

export const TextInputDisabled: Story = {
  name: "InputTypeInField (disabled)",
  render: () => (
    <FormikWrapper initialValues={{ locked: "read-only value" }}>
      <InputTypeInField
        name="locked"
        placeholder="Disabled"
        variant="disabled"
      />
    </FormikWrapper>
  ),
};

// ---------------------------------------------------------------------------
// InputTextAreaField
// ---------------------------------------------------------------------------

export const TextArea: Story = {
  name: "InputTextAreaField",
  render: () => (
    <FormikWrapper initialValues={{ bio: "" }}>
      <InputTextAreaField name="bio" placeholder="Tell us about yourself..." />
    </FormikWrapper>
  ),
};

// ---------------------------------------------------------------------------
// InputSelectField
// ---------------------------------------------------------------------------

export const Select: Story = {
  name: "InputSelectField",
  render: () => (
    <FormikWrapper initialValues={{ role: "" }}>
      <InputSelectField name="role">
        <InputSelect.Trigger placeholder="Select a role" />
        <InputSelect.Content>
          <InputSelect.Item value="admin">Admin</InputSelect.Item>
          <InputSelect.Item value="editor">Editor</InputSelect.Item>
          <InputSelect.Item value="viewer">Viewer</InputSelect.Item>
        </InputSelect.Content>
      </InputSelectField>
    </FormikWrapper>
  ),
};

// ---------------------------------------------------------------------------
// InputDatePickerField
// ---------------------------------------------------------------------------

export const DatePicker: Story = {
  name: "InputDatePickerField",
  render: () => (
    <FormikWrapper initialValues={{ startDate: null }}>
      <InputDatePickerField name="startDate" />
    </FormikWrapper>
  ),
};

// ---------------------------------------------------------------------------
// PasswordInputTypeInField
// ---------------------------------------------------------------------------

export const PasswordInput: Story = {
  name: "PasswordInputTypeInField",
  render: () => (
    <FormikWrapper initialValues={{ apiKey: "" }}>
      <PasswordInputTypeInField name="apiKey" placeholder="sk-..." />
    </FormikWrapper>
  ),
};

export const PasswordInputNoLabel: Story = {
  name: "PasswordInputTypeInField (no label)",
  render: () => (
    <FormikWrapper initialValues={{ secret: "" }}>
      <PasswordInputTypeInField name="secret" placeholder="Enter secret" />
    </FormikWrapper>
  ),
};
