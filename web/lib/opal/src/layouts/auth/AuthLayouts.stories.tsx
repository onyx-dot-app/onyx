import type { Meta, StoryObj } from "@storybook/react";
import * as AuthLayouts from "@opal/layouts/auth/components";
import { Button } from "@opal/components";
import SvgSparkle from "@opal/icons/sparkle";
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
        icon={SvgSparkle}
        title="Welcome back"
        description="Sign in to your account"
        bottomPrompt={markdown(
          "Don't have an account? [Create an Account](/auth/signup)"
        )}
      >
        <AuthLayouts.Fields>
          <FieldPlaceholder label="Email" />
          <FieldPlaceholder label="Password" />
        </AuthLayouts.Fields>
        <AuthLayouts.Submit label="submit" />
      </AuthLayouts.Card>
    </AuthLayouts.Root>
  ),
};

export const WithSSOAndSeparator: Story = {
  render: () => (
    <AuthLayouts.Root>
      <AuthLayouts.Card
        icon={SvgSparkle}
        title="Welcome back"
        description="Sign in to your account"
        bottomPrompt={markdown(
          "Don't have an account? [Create an Account](/auth/signup)"
        )}
      >
        <Button width="full">Continue with Google</Button>
        <AuthLayouts.OrSeparator />
        <AuthLayouts.Fields>
          <FieldPlaceholder label="Email" />
          <FieldPlaceholder label="Password" />
        </AuthLayouts.Fields>
        <AuthLayouts.Submit label="submit" />
      </AuthLayouts.Card>
    </AuthLayouts.Root>
  ),
};

export const Signup: Story = {
  render: () => (
    <AuthLayouts.Root>
      <AuthLayouts.Card
        icon={SvgSparkle}
        title="Create account"
        description="Get started"
        bottomPrompt={markdown(
          "Already have an account? [Sign In](/auth/login)"
        )}
      >
        <AuthLayouts.Fields>
          <FieldPlaceholder label="Email" />
          <FieldPlaceholder label="Password" />
        </AuthLayouts.Fields>
        <AuthLayouts.Submit label="create" />
      </AuthLayouts.Card>
    </AuthLayouts.Root>
  ),
};

export const ForgotPassword: Story = {
  render: () => (
    <AuthLayouts.Root>
      <AuthLayouts.Card
        icon={SvgSparkle}
        title="Forgot Password"
        description="Enter your email address and we'll send you a reset link."
        bottomPrompt={markdown("[Back to Login](/auth/login)")}
      >
        <AuthLayouts.Fields>
          <FieldPlaceholder label="Email" />
        </AuthLayouts.Fields>
        <AuthLayouts.Submit label="submit" />
      </AuthLayouts.Card>
    </AuthLayouts.Root>
  ),
};

export const DisabledSubmit: Story = {
  render: () => (
    <AuthLayouts.Root>
      <AuthLayouts.Card
        icon={SvgSparkle}
        title="Sign in"
        description="Submitting…"
      >
        <AuthLayouts.Fields>
          <FieldPlaceholder label="Email" />
          <FieldPlaceholder label="Password" />
        </AuthLayouts.Fields>
        <AuthLayouts.Submit label="submit" disabled />
      </AuthLayouts.Card>
    </AuthLayouts.Root>
  ),
};
