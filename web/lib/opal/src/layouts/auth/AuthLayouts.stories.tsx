import type { Meta, StoryObj } from "@storybook/react";
import * as AuthLayouts from "@opal/layouts/auth/components";
import { Button } from "@opal/components";
import { markdown } from "@opal/utils";

const meta: Meta = {
  title: "Layouts/Auth",
  tags: ["autodocs"],
  parameters: { layout: "fullscreen" },
};

export default meta;
type Story = StoryObj;

const FieldPlaceholder = ({ label }: { label: string }) => (
  <div className="flex flex-col gap-1">
    <div className="h-4 w-12 rounded-04 bg-background-neutral-02" />
    <div className="h-9 rounded-08 border border-border-02 bg-background-neutral-01" />
    <span className="sr-only">{label}</span>
  </div>
);

export const BasicLogin: Story = {
  render: () => (
    <AuthLayouts.Root>
      <AuthLayouts.Card
        title="Welcome to Onyx"
        description="Your open source AI platform for work"
        bottomPrompt={markdown(
          "New to Onyx? [Create an Account](/auth/signup)"
        )}
      >
        <AuthLayouts.FormFields>
          <FieldPlaceholder label="Email" />
          <FieldPlaceholder label="Password" />
        </AuthLayouts.FormFields>
        <AuthLayouts.Submit>Sign in</AuthLayouts.Submit>
      </AuthLayouts.Card>
    </AuthLayouts.Root>
  ),
};

export const WithSSOAndSeparator: Story = {
  render: () => (
    <AuthLayouts.Root>
      <AuthLayouts.Card
        title="Welcome to Onyx"
        description="Your open source AI platform for work"
        bottomPrompt={markdown(
          "New to Onyx? [Create an Account](/auth/signup)"
        )}
      >
        <Button width="full">Continue with Google</Button>
        <AuthLayouts.OrSeparator />
        <AuthLayouts.FormFields>
          <FieldPlaceholder label="Email" />
          <FieldPlaceholder label="Password" />
        </AuthLayouts.FormFields>
        <AuthLayouts.Submit>Sign in</AuthLayouts.Submit>
      </AuthLayouts.Card>
    </AuthLayouts.Root>
  ),
};

export const Signup: Story = {
  render: () => (
    <AuthLayouts.Root>
      <AuthLayouts.Card
        title="Create account"
        description="Get started with Onyx"
        bottomPrompt={markdown(
          "Already have an account? [Sign In](/auth/login?autoRedirectToSignup=false)"
        )}
      >
        <AuthLayouts.FormFields>
          <FieldPlaceholder label="Email" />
          <FieldPlaceholder label="Password" />
        </AuthLayouts.FormFields>
        <AuthLayouts.Submit>Create account</AuthLayouts.Submit>
      </AuthLayouts.Card>
    </AuthLayouts.Root>
  ),
};

export const ForgotPassword: Story = {
  render: () => (
    <AuthLayouts.Root>
      <AuthLayouts.Card
        title="Forgot Password"
        description="Enter your email address and we'll send you a reset link."
        bottomPrompt={markdown("[Back to Login](/auth/login)")}
      >
        <AuthLayouts.FormFields>
          <FieldPlaceholder label="Email" />
        </AuthLayouts.FormFields>
        <AuthLayouts.Submit>Reset Password</AuthLayouts.Submit>
      </AuthLayouts.Card>
    </AuthLayouts.Root>
  ),
};

export const DisabledSubmit: Story = {
  render: () => (
    <AuthLayouts.Root>
      <AuthLayouts.Card title="Sign in" description="Submitting…">
        <AuthLayouts.FormFields>
          <FieldPlaceholder label="Email" />
          <FieldPlaceholder label="Password" />
        </AuthLayouts.FormFields>
        <AuthLayouts.Submit disabled>Sign in</AuthLayouts.Submit>
      </AuthLayouts.Card>
    </AuthLayouts.Root>
  ),
};
