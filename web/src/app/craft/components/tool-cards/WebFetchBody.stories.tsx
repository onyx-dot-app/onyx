import type { Meta, StoryObj } from "@storybook/react";
import WebFetchBody from "@/app/craft/components/tool-cards/WebFetchBody";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

const meta: Meta<typeof WebFetchBody> = {
  title: "Apps/Craft/Tool Cards/Web Fetch Body",
  component: WebFetchBody,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <div className="w-[640px]">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof WebFetchBody>;

function webfetch(overrides: Partial<ToolCallState>): ToolCallState {
  return {
    id: "webfetch-1",
    kind: "other",
    toolName: "webfetch",
    title: "Fetching",
    description: "",
    command: "",
    status: "completed",
    rawOutput: "",
    ...overrides,
  };
}

export const JsonResponse: Story = {
  args: {
    toolCall: webfetch({
      description: "https://api.github.com/repos/onyx-dot-app/onyx",
      rawOutput: `{
  "id": 758315521,
  "name": "onyx",
  "full_name": "onyx-dot-app/onyx",
  "private": false,
  "html_url": "https://github.com/onyx-dot-app/onyx",
  "description": "Gen-AI Chat for Teams",
  "language": "Python",
  "stargazers_count": 12450,
  "watchers_count": 12450,
  "forks_count": 1620,
  "open_issues_count": 287,
  "default_branch": "main"
}`,
    }),
  },
};

export const HtmlResponse: Story = {
  args: {
    toolCall: webfetch({
      description: "https://example.com",
      rawOutput: `<!doctype html>
<html>
<head>
  <title>Example Domain</title>
</head>
<body>
  <h1>Example Domain</h1>
  <p>This domain is for use in illustrative examples in documents.</p>
</body>
</html>`,
    }),
  },
};

export const EmptyBody: Story = {
  args: {
    toolCall: webfetch({
      description: "https://example.com/204",
      rawOutput: "",
    }),
  },
};
