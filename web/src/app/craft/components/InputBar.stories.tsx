import { useRef, useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { SWRConfig } from "swr";
import { Button, Text } from "@opal/components";
import { cn } from "@opal/utils";
import { SvgArrowUp, SvgStop, SvgLoader } from "@opal/icons";
import IconButton from "@/refresh-components/buttons/IconButton";
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

/**
 * While a response streams (empty input): a red Stop control appears to the
 * left of the fixed send button, and the `esc esc to stop` hint sits next to
 * the paperclip. The send button is disabled until you type. Press Esc twice
 * (the first lights the first keycap) to interrupt.
 */
export const Running: Story = {
  args: {
    isRunning: true,
    onInterrupt: () => console.log("interrupt"),
    queuedMessages: [],
    onQueueMessage: (text: string) => console.log("queue", text),
    onRemoveQueuedMessage: (index: number) => console.log("remove", index),
  },
};

/**
 * The bridge state after an interrupt is requested: the Stop control shows a
 * spinner, the hint reads `Stopping…`, and the send button is disabled so a
 * queued send can't race the turn terminator.
 */
export const Interrupting: Story = {
  args: {
    isRunning: true,
    isInterrupting: true,
    onInterrupt: () => console.log("interrupt"),
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
        onInterrupt={() => setIsRunning(false)}
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

/**
 * Interactive interrupt flow. While "streaming", type to see the send button
 * turn into a Queue affordance alongside the red Stop control. Click Stop (or
 * press Esc twice — the first Esc lights the first keycap) to request an
 * interrupt: the control shows a brief `Stopping…` spinner, then the turn ends.
 * "Restart stream" begins a new turn.
 */
function InterruptDemo() {
  const [isRunning, setIsRunning] = useState(true);
  const [isInterrupting, setIsInterrupting] = useState(false);

  function handleInterrupt() {
    setIsInterrupting(true);
    // Simulate the backend turn-terminator arriving.
    setTimeout(() => {
      setIsInterrupting(false);
      setIsRunning(false);
    }, 900);
  }

  return (
    <div className="flex flex-col gap-3">
      <Button
        prominence="secondary"
        disabled={isRunning}
        onClick={() => setIsRunning(true)}
      >
        Restart stream
      </Button>
      <InputBar
        onSubmit={(message, files) =>
          console.log("onSubmit", { message, files })
        }
        isRunning={isRunning}
        isInterrupting={isInterrupting}
        onInterrupt={handleInterrupt}
        placeholder="Continue the conversation..."
        queuedMessages={[]}
        onQueueMessage={(text) => console.log("queue", text)}
        onRemoveQueuedMessage={(index) => console.log("remove", index)}
      />
    </div>
  );
}

export const Interrupt: Story = {
  render: () => <InterruptDemo />,
};

/**
 * The shipped Stop control next to the send button, across its states:
 * outlined + transparent with a neutral glyph (no red), a subtle neutral fill
 * when "armed" by the first Esc, and a spinner once an interrupt is requested.
 */
function StopButtonState({
  label,
  armed = false,
  stopping = false,
}: {
  label: string;
  armed?: boolean;
  stopping?: boolean;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Text font="secondary-body" color="text-03">
        {label}
      </Text>
      <div className="flex flex-row items-center gap-1 rounded-16 bg-background-neutral-00 shadow-01 p-1 w-fit">
        <IconButton
          main
          tertiary
          icon={stopping ? SvgLoader : SvgStop}
          iconClassName={stopping ? "animate-spin" : undefined}
          className={cn(
            "border-[1.5px] border-border-02",
            armed && "bg-background-tint-02!"
          )}
          disabled={stopping}
          tooltip="Stop · esc esc"
          aria-label="Stop generating"
        />
        <IconButton icon={SvgArrowUp} tooltip="Send" aria-label="Send" />
      </div>
    </div>
  );
}

export const StopButtonStyles: Story = {
  render: () => (
    <div className="flex flex-wrap gap-6">
      <StopButtonState label="Resting" />
      <StopButtonState label="Armed (first Esc)" armed />
      <StopButtonState label="Stopping" stopping />
    </div>
  ),
};
