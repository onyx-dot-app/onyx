import type { Meta, StoryObj } from "@storybook/react";
import { Formik, Form } from "formik";
import {
  Vertical,
  Horizontal,
  InputDivider,
  InputPadder,
  InputErrorText,
} from "@opal/layouts/inputs/components";
import { Button } from "@opal/components";

const meta: Meta = {
  title: "opal/layouts/InputLayouts",
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj;

const MockInput = (props: React.InputHTMLAttributes<HTMLInputElement>) => (
  <input
    {...props}
    className="rounded-08 border px-3 py-1.5 text-sm w-full"
    style={{ minWidth: 200 }}
  />
);

const MockSwitch = () => (
  <button
    type="button"
    className="w-10 h-5 rounded-full bg-background-neutral-03 relative"
  >
    <span className="absolute left-0.5 top-0.5 w-4 h-4 rounded-full bg-background-neutral-00 transition-transform" />
  </button>
);

// ---------------------------------------------------------------------------
// Vertical
// ---------------------------------------------------------------------------

export const VerticalNoLabel: Story = {
  name: "Vertical — no label",
  render: () => (
    <div className="w-96">
      <Vertical title="Team Name" description="Your organization's name.">
        <MockInput placeholder="Acme Corp" />
      </Vertical>
    </div>
  ),
};

export const VerticalWithLabel: Story = {
  name: "Vertical — implicit label",
  render: () => (
    <div className="w-96">
      <Vertical
        withLabel
        title="Team Name"
        description="Clicking anywhere on this row focuses the input."
      >
        <MockInput placeholder="Acme Corp" />
      </Vertical>
    </div>
  ),
};

export const VerticalWithFieldName: Story = {
  name: "Vertical — field name (Formik)",
  render: () => (
    <Formik initialValues={{ email: "" }} onSubmit={() => {}}>
      <Form className="w-96">
        <Vertical
          withLabel="email"
          title="Email"
          description="We'll never share your email."
          subDescription="Used for account recovery."
        >
          <MockInput name="email" id="email" placeholder="you@example.com" />
        </Vertical>
      </Form>
    </Formik>
  ),
};

export const VerticalDisabled: Story = {
  name: "Vertical — disabled",
  render: () => (
    <div className="w-96">
      <Vertical withLabel title="Email" disabled>
        <MockInput disabled placeholder="disabled" />
      </Vertical>
    </div>
  ),
};

// ---------------------------------------------------------------------------
// Horizontal
// ---------------------------------------------------------------------------

export const HorizontalNoLabel: Story = {
  name: "Horizontal — no label (button child)",
  render: () => (
    <div className="w-[32rem]">
      <Horizontal
        title="Delete This Item"
        description="This action cannot be undone."
        center
      >
        <Button variant="danger" prominence="secondary">
          Delete
        </Button>
      </Horizontal>
    </div>
  ),
};

export const HorizontalWithLabel: Story = {
  name: "Horizontal — implicit label (switch)",
  render: () => (
    <div className="w-[32rem]">
      <Horizontal
        withLabel
        title="Enable Notifications"
        description="Receive updates about your account."
      >
        <MockSwitch />
      </Horizontal>
    </div>
  ),
};

export const HorizontalCentered: Story = {
  name: "Horizontal — centered",
  render: () => (
    <div className="w-[32rem]">
      <Horizontal
        withLabel
        title="Dark Mode"
        description="Switch between light and dark themes."
        center
      >
        <MockSwitch />
      </Horizontal>
    </div>
  ),
};

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

export const DividerStory: Story = {
  name: "InputDivider",
  render: () => (
    <div className="w-96 flex flex-col gap-2">
      <Horizontal withLabel title="Setting A" description="First setting.">
        <MockSwitch />
      </Horizontal>
      <InputDivider />
      <Horizontal withLabel title="Setting B" description="Second setting.">
        <MockSwitch />
      </Horizontal>
    </div>
  ),
};

export const PadderStory: Story = {
  name: "InputPadder",
  render: () => (
    <div className="w-96 border rounded-12">
      <InputPadder>
        <Vertical withLabel title="Name" description="Your full name.">
          <MockInput placeholder="Jane Doe" />
        </Vertical>
      </InputPadder>
    </div>
  ),
};

export const ErrorTextStory: Story = {
  name: "InputErrorText",
  render: () => (
    <div className="w-96 flex flex-col gap-2">
      <InputErrorText type="error">This field is required.</InputErrorText>
      <InputErrorText type="warning">
        Consider using a stronger password.
      </InputErrorText>
    </div>
  ),
};

export const Comparison: Story = {
  name: "Comparison — all variants",
  render: () => (
    <div className="flex flex-col gap-6 w-[32rem]">
      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium">No label (button)</span>
        <Horizontal title="Delete Account" description="Permanent action.">
          <Button variant="danger" prominence="secondary">
            Delete
          </Button>
        </Horizontal>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium">Implicit label (switch)</span>
        <Horizontal
          withLabel
          title="Notifications"
          description="Click anywhere on this row."
        >
          <MockSwitch />
        </Horizontal>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-xs font-medium">
          Vertical with sub-description
        </span>
        <Vertical
          withLabel
          title="API Key"
          description="Paste your key."
          subDescription="Keys are stored encrypted."
        >
          <MockInput type="password" placeholder="sk-..." />
        </Vertical>
      </div>
    </div>
  ),
};
