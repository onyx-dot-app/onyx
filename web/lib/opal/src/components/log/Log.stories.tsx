import type { Meta, StoryObj } from "@storybook/react-vite";
import { Log, Tag, Text } from "@opal/components";
import {
  SvgCheckCircle,
  SvgClock,
  SvgHourglass,
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
    variant: "success-light",
    icon: SvgCheckCircle,
    title: "Authenticate connection",
    centerChildren: (
      <Text font="main-ui-body" color="text-04" maxLines={1}>
        Signed in as service-account@acme.com
      </Text>
    ),
  },
};

export default meta;
type Story = StoryObj<typeof Log>;

export const Default: Story = {};

// The variants, as a list of checks. Heavy lines are tinted.
export const Variants: Story = {
  render: () => (
    <div style={{ width: 560, display: "flex", flexDirection: "column" }}>
      <Log
        variant="error-heavy"
        icon={SvgXCircle}
        title="Check attachment access"
        centerChildren={
          <Text font="main-ui-body" color="status-error-05" maxLines={1}>
            Attachment download timed out
          </Text>
        }
        rightChildren={<Tag title="Required" color="gray" />}
      />
      <Log
        variant="warning-light"
        icon={SvgAlertCircle}
        title="Check group membership"
        centerChildren={
          <Text font="main-ui-body" color="text-04" maxLines={1}>
            Could not be verified
          </Text>
        }
      />
      <Log
        variant="success-light"
        icon={SvgCheckCircle}
        title="Check connector scopes"
        centerChildren={
          <Text font="main-ui-body" color="text-04" maxLines={1}>
            42 spaces available
          </Text>
        }
      />
      <Log
        variant="error-light"
        icon={SvgXCircle}
        title="Check comments access"
        centerChildren={
          <Text font="main-ui-body" color="text-04" maxLines={1}>
            Optional check failed
          </Text>
        }
      />
      <Log
        variant="default"
        icon={SvgMinusCircle}
        title="Check page restrictions"
        centerChildren={
          <Text font="main-ui-body" color="text-04" maxLines={1}>
            Skipped
          </Text>
        }
      />
      <Log
        variant="default"
        icon={IconLoader}
        title="Check space permissions"
        centerChildren={
          <Text font="main-ui-body" color="text-04" maxLines={1}>
            Testing…
          </Text>
        }
      />
      <Log
        variant="default"
        icon={SvgClock}
        title="Test permission syncing"
        centerChildren={
          <Text font="main-ui-body" color="text-04" maxLines={1}>
            Queued
          </Text>
        }
      />
      <Log
        variant="default"
        icon={SvgHourglass}
        title="Test indexing documents"
        centerChildren={
          <Text font="main-ui-body" color="text-04" maxLines={1}>
            Waiting for user to select content to index
          </Text>
        }
      />
    </div>
  ),
};

// Long text is cut to one line; hover it to read it all.
export const LongText: Story = {
  render: () => (
    <div style={{ width: 420 }}>
      <Log
        variant="error-heavy"
        icon={SvgXCircle}
        title="A check whose name is far too long to fit"
        centerChildren={
          <Text font="main-ui-body" color="status-error-05" maxLines={1}>
            The token lacks the read:confluence-space.summary scope. Add it in
            the Atlassian developer console, then run the checks again.
          </Text>
        }
        rightChildren={<Tag title="Required" color="gray" />}
      />
    </div>
  ),
};
