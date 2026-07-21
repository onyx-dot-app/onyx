import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "@opal/components";
import { ToastProvider, toast } from "@opal/layouts";

// Each story needs a mounted ToastProvider for fired toasts to render. The
// decorator supplies it and forwards the story-level errorAppendix parameter.
const meta: Meta<typeof ToastProvider> = {
  title: "opal/layouts/Toast",
  component: ToastProvider,
  tags: ["autodocs"],
  decorators: [
    (Story, ctx) => (
      <ToastProvider errorAppendix={ctx.parameters.errorAppendix}>
        <Story />
      </ToastProvider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ToastProvider>;

export const Levels: Story = {
  render: () => (
    <div className="flex flex-col items-start gap-2">
      <Button onClick={() => toast.success("Document saved")}>Success</Button>
      <Button onClick={() => toast.error("Failed to save document")}>
        Error
      </Button>
      <Button onClick={() => toast.warning("Connection is unstable")}>
        Warning
      </Button>
      <Button
        onClick={() =>
          toast.info("Sync started", { description: "This can take a bit." })
        }
      >
        Info with description
      </Button>
    </div>
  ),
};

export const ErrorAppendix: Story = {
  parameters: { errorAppendix: "Need help? Contact support@onyx.app." },
  render: () => (
    <Button onClick={() => toast.error("Indexing failed")}>
      Error with appendix
    </Button>
  ),
};

export const LongMessageExpands: Story = {
  render: () => (
    <Button
      onClick={() =>
        toast.error(
          "Request failed with status 500. ".repeat(12) +
            "Full payload preserved for debugging.",
          { duration: Infinity }
        )
      }
    >
      Fire long toast
    </Button>
  ),
};

export const Persistent: Story = {
  render: () => (
    <Button
      onClick={() =>
        toast.warning("Reindexing in progress", { duration: Infinity })
      }
    >
      Fire persistent toast
    </Button>
  ),
};
