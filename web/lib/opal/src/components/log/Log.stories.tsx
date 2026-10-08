import type { Meta, StoryObj } from "@storybook/react-vite";
import { Log, Tag } from "@opal/components";
import {
  SvgCheckCircle,
  SvgClock,
  SvgHourglass,
  SvgInfo,
  SvgMinusCircle,
  SvgAlertCircle,
  SvgXCircle,
} from "@opal/icons";
import { IconLoader } from "@opal/loaders";

const meta: Meta<typeof Log> = {
  title: "opal/components/Log",
  component: Log,
  tags: ["autodocs"],
  args: {
    variant: "success",
    icon: SvgCheckCircle,
    title: "Authenticate connection",
    details: "Signed in as service-account@acme.com",
  },
};

export default meta;
type Story = StoryObj<typeof Log>;

export const Default: Story = {};

// Every variant, as a list of checks. Hover a line to see its tint.
export const Variants: Story = {
  render: () => (
    <div style={{ width: 560, display: "flex", flexDirection: "column" }}>
      <Log
        variant="error"
        icon={SvgXCircle}
        title="Check attachment access"
        details="Attachment download timed out"
        rightChildren={<Tag title="Required" color="gray" />}
      />
      <Log
        variant="warning"
        icon={SvgAlertCircle}
        title="Check group membership"
        details="Could not be verified"
      />
      <Log
        variant="success"
        icon={SvgCheckCircle}
        title="Check connector scopes"
        details="42 spaces available"
      />
      <Log
        variant="info"
        icon={SvgInfo}
        title="Check rate limit"
        details="Shared with 3 other connectors"
      />
      <Log
        variant="default"
        icon={SvgMinusCircle}
        title="Check page restrictions"
        details="Skipped"
      />
      <Log
        variant="pending"
        icon={IconLoader}
        title="Check space permissions"
        details="Testing…"
      />
      <Log
        variant="pending"
        icon={SvgClock}
        title="Test permission syncing"
        details="Queued"
      />
      <Log
        variant="pending"
        icon={SvgHourglass}
        title="Test indexing documents"
        details="Waiting for user to select content to index"
      />
    </div>
  ),
};

// Long text is cut to one line; hover it to read it all.
export const LongText: Story = {
  render: () => (
    <div style={{ width: 420 }}>
      <Log
        variant="error"
        icon={SvgXCircle}
        title="A check whose name is far too long to fit"
        details="The token lacks the read:confluence-space.summary scope. Add it in the Atlassian developer console, then run the checks again."
        rightChildren={<Tag title="Required" color="gray" />}
      />
    </div>
  ),
};
