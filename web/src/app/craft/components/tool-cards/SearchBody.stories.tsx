import type { Meta, StoryObj } from "@storybook/react";
import SearchBody from "@/app/craft/components/tool-cards/SearchBody";
import type { ToolCallState } from "@/app/craft/types/displayTypes";

const meta: Meta<typeof SearchBody> = {
  title: "Apps/Craft/Tool Cards/Search Body",
  component: SearchBody,
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
type Story = StoryObj<typeof SearchBody>;

function search(overrides: Partial<ToolCallState>): ToolCallState {
  return {
    id: "search-1",
    kind: "search",
    toolName: "grep",
    title: "Searching content",
    description: "",
    command: "",
    status: "completed",
    rawOutput: "",
    ...overrides,
  };
}

export const GrepMultipleFiles: Story = {
  args: {
    toolCall: search({
      description: "interface .*Props",
      rawOutput: `web/src/app/craft/components/tool-cards/CraftToolCard.tsx:28:interface CraftToolCardProps {
web/src/app/craft/components/tool-cards/CraftToolGroup.tsx:20:interface CraftToolGroupProps {
web/src/app/craft/components/tool-cards/SkillBadge.tsx:6:interface SkillBadgeProps {
web/src/app/craft/components/approvals/ApprovalCard.tsx:27:interface ApprovalCardProps {
web/src/app/craft/components/approvals/PayloadView.tsx:8:interface PayloadViewProps {`,
    }),
  },
};

export const GrepDenseHits: Story = {
  args: {
    toolCall: search({
      description: "aboveInputSlot",
      rawOutput: `web/src/sections/input/BaseInputBar.tsx:68:  aboveInputSlot?: ReactNode;
web/src/sections/input/BaseInputBar.tsx:278:          {aboveInputSlot}
web/src/app/craft/components/CraftInputBar.tsx:60:  aboveInputSlot?: ReactNode;
web/src/app/craft/components/CraftInputBar.tsx:262:            aboveInputSlot={aboveInputSlot}
web/src/app/craft/components/ChatPanel.tsx:679:                    aboveInputSlot={`,
    }),
  },
};

export const GlobFileList: Story = {
  args: {
    toolCall: search({
      toolName: "glob",
      title: "Searching files",
      description: "**/*.stories.tsx",
      rawOutput: `web/src/app/craft/components/tool-cards/BashBody.stories.tsx
web/src/app/craft/components/tool-cards/CraftToolCard.stories.tsx
web/src/app/craft/components/tool-cards/CraftToolGroup.stories.tsx
web/src/app/craft/components/tool-cards/DiffBody.stories.tsx
web/src/app/craft/components/tool-cards/GenericBody.stories.tsx
web/src/app/craft/components/tool-cards/ReadBody.stories.tsx
web/src/app/craft/components/tool-cards/SearchBody.stories.tsx
web/src/app/craft/components/tool-cards/SkillBadge.stories.tsx
web/src/app/craft/components/tool-cards/TaskBody.stories.tsx
web/src/app/craft/components/tool-cards/WebFetchBody.stories.tsx
web/src/app/craft/components/tool-cards/WebSearchBody.stories.tsx`,
    }),
  },
};

export const NoResults: Story = {
  args: {
    toolCall: search({
      description: "xyzzy-no-such-symbol",
      rawOutput: "",
    }),
  },
};
