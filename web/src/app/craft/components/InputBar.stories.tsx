import { useRef, useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { SWRConfig } from "swr";
import { Button } from "@opal/components";
import InputBar from "@/app/craft/components/InputBar";
import {
  UploadFilesProvider,
  BuildFile,
} from "@/app/craft/contexts/UploadFilesContext";
import { UserProvider } from "@/providers/UserProvider";
import { QueuedMessage } from "@/app/app/interfaces";

// InputBar mounts UserProvider/UploadFilesContext and calls useUserSkills,
// which fetch /api/me, /api/auth/type and /api/skills. There's no backend in
// standalone Storybook, so disable SWR revalidation (with an isolated cache) to
// keep the stories self-contained — hooks fall back to their empty defaults.
const SWR_NO_FETCH = {
  provider: () => new Map(),
  revalidateOnMount: false,
  revalidateIfStale: false,
  revalidateOnFocus: false,
  revalidateOnReconnect: false,
};

const meta: Meta<typeof InputBar> = {
  title: "Apps/Craft/Input Bar",
  component: InputBar,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <SWRConfig value={SWR_NO_FETCH}>
        <UserProvider>
          <UploadFilesProvider>
            <div className="w-[640px]">
              <Story />
            </div>
          </UploadFilesProvider>
        </UserProvider>
      </SWRConfig>
    ),
  ],
  args: {
    onSubmit: (message: string, files: BuildFile[]) =>
      console.log("onSubmit", { message, files }),
    isRunning: false,
    placeholder: "Continue the conversation...",
  },
};

export default meta;
type Story = StoryObj<typeof InputBar>;

/** Idle input — typing + Enter (or the send button) submits immediately. */
export const Default: Story = {};

/** While a response streams, the send button is disabled and nothing submits. */
export const Running: Story = {
  args: {
    isRunning: true,
  },
};

export const Disabled: Story = {
  args: {
    disabled: true,
  },
};

/** Shows the loading send button used while the sandbox spins up. */
export const SandboxInitializing: Story = {
  args: {
    sandboxInitializing: true,
  },
};

/** Used when the input sits flush against a panel below it. */
export const NoBottomRounding: Story = {
  args: {
    noBottomRounding: true,
  },
};

/**
 * Interactive demo of the queued-message flow. Typing while "running" enqueues
 * the message (rendered as pills above the input) instead of submitting. Click
 * a pill (or press ↑ from an empty input) to highlight it, then Enter to edit,
 * Delete/Backspace to remove. "Finish run" simulates a completed response,
 * which dequeues and submits the next message FIFO — mirroring the auto-send
 * effect in BuildChatPanel.
 */
function QueuedMessagesDemo() {
  const [isRunning, setIsRunning] = useState(true);
  const [queued, setQueued] = useState<QueuedMessage[]>([
    { id: 1, text: "Add a dark mode toggle to the settings page" },
    { id: 2, text: "Then write tests for it" },
  ]);
  const nextIdRef = useRef(3);

  function enqueue(text: string) {
    setQueued((prev) => [...prev, { id: nextIdRef.current++, text }]);
  }

  function removeAt(index: number) {
    setQueued((prev) => prev.filter((_, i) => i !== index));
  }

  // Simulate a run completing: send the head of the queue, then keep
  // "running" while messages remain (each completion drains one).
  function finishRun() {
    setQueued((prev) => {
      const [head, ...rest] = prev;
      if (head) console.log("auto-sent", head.text);
      setIsRunning(rest.length > 0);
      return rest;
    });
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-2">
        <Button
          prominence="secondary"
          onClick={() => setIsRunning((prev) => !prev)}
        >
          {`${isRunning ? "Streaming…" : "Idle"} — toggle`}
        </Button>
        <Button
          prominence="secondary"
          disabled={queued.length === 0}
          onClick={finishRun}
        >
          Finish run (auto-send next)
        </Button>
      </div>
      <InputBar
        onSubmit={(message, files) =>
          console.log("onSubmit", { message, files })
        }
        isRunning={isRunning}
        placeholder="Continue the conversation..."
        queuedMessages={queued}
        onQueueMessage={enqueue}
        onRemoveQueuedMessage={removeAt}
      />
    </div>
  );
}

export const QueuedMessages: Story = {
  render: () => <QueuedMessagesDemo />,
};
