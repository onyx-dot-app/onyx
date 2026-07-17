import type { Meta, StoryObj } from "@storybook/react";
import SetupCard from "@/app/craft/components/setup-requests/SetupCard";
import type { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";

const meta: Meta<typeof SetupCard> = {
  title: "Apps/Craft/Setup Requests/Setup Card",
  component: SetupCard,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div className="w-[480px]">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof SetupCard>;

function userApp(
  overrides: Partial<ExternalAppUserResponse> = {}
): ExternalAppUserResponse {
  return {
    id: 1,
    name: "Slack",
    description: "Post messages and read channels.",
    slug: "slack",
    app_type: "SLACK",
    credential_keys: [],
    credential_values: {},
    authenticated: false,
    supports_oauth: true,
    ...overrides,
  };
}

// Resolved OAuth app, pending decision — the agent gave a reason.
export const Default: Story = {
  args: {
    requestId: "req-01HX3K9M4Q7W2",
    appSlug: "slack",
    reason: "I need Slack to post the release notes to #eng-craft.",
    userApp: userApp(),
  },
};

// No reason from the agent — the card falls back to a generic description.
export const WithoutReason: Story = {
  args: {
    requestId: "req-01HX3K9M4Q7W2",
    appSlug: "linear",
    reason: null,
    userApp: userApp({
      id: 2,
      name: "Linear",
      slug: "linear",
      app_type: "LINEAR",
    }),
  },
};

// Token app (no OAuth) — "Connect" opens the credential form instead of a popup.
export const TokenApp: Story = {
  args: {
    requestId: "req-01HX3K9M4Q7W2",
    appSlug: "hubspot",
    reason: "I need HubSpot to look up the customer record.",
    userApp: userApp({
      id: 3,
      name: "HubSpot",
      slug: "hubspot",
      app_type: "HUBSPOT",
      supports_oauth: false,
    }),
  },
};

// App row still loading from the registry — the connect button is disabled.
export const Loading: Story = {
  args: {
    requestId: "req-01HX3K9M4Q7W2",
    appSlug: "slack",
    reason: "I need Slack to post the release notes to #eng-craft.",
    userApp: undefined,
  },
};

// Durable connected state — `authenticated` keeps the card settled after a
// navigate-away-and-back.
export const Connected: Story = {
  args: {
    requestId: "req-01HX3K9M4Q7W2",
    appSlug: "slack",
    reason: "I need Slack to post the release notes to #eng-craft.",
    userApp: userApp({ authenticated: true }),
  },
};
