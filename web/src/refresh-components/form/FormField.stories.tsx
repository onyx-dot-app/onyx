import type { Meta, StoryObj } from "@storybook/react";
import { FormField } from "./FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";

const meta: Meta<typeof FormField> = {
  title: "refresh-components/form/FormField",
  component: FormField,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof FormField>;

export const Default: Story = {
  render: () => (
    <FormField state="idle" name="email">
      <FormField.Label>Email Address</FormField.Label>
      <FormField.Description>
        We will never share your email with anyone.
      </FormField.Description>
      <FormField.Control>
        <InputTypeIn placeholder="you@example.com" />
      </FormField.Control>
    </FormField>
  ),
};

export const Required: Story = {
  render: () => (
    <FormField state="idle" name="name" required>
      <FormField.Label required>Full Name</FormField.Label>
      <FormField.Control>
        <InputTypeIn placeholder="Jane Doe" />
      </FormField.Control>
    </FormField>
  ),
};

export const Optional: Story = {
  render: () => (
    <FormField state="idle" name="nickname">
      <FormField.Label optional>Nickname</FormField.Label>
      <FormField.Control>
        <InputTypeIn placeholder="Optional nickname" />
      </FormField.Control>
    </FormField>
  ),
};

export const ErrorState: Story = {
  render: () => (
    <FormField state="error" name="username">
      <FormField.Label>Username</FormField.Label>
      <FormField.Control>
        <InputTypeIn placeholder="Choose a username" variant="error" />
      </FormField.Control>
      <FormField.Message
        messages={{ error: "This username is already taken." }}
      />
    </FormField>
  ),
};

export const SuccessState: Story = {
  render: () => (
    <FormField state="success" name="username">
      <FormField.Label>Username</FormField.Label>
      <FormField.Control>
        <InputTypeIn placeholder="Choose a username" />
      </FormField.Control>
      <FormField.Message messages={{ success: "Username is available!" }} />
    </FormField>
  ),
};

export const WithAPIMessage: Story = {
  render: () => (
    <FormField state="idle" name="domain">
      <FormField.Label>Custom Domain</FormField.Label>
      <FormField.Control>
        <InputTypeIn placeholder="your-domain.com" />
      </FormField.Control>
      <FormField.APIMessage
        state="loading"
        messages={{ loading: "Verifying DNS records..." }}
      />
    </FormField>
  ),
};
