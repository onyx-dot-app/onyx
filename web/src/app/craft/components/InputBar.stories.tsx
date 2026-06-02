import { useEffect, useRef, useState } from "react";
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
import {
  createRichInputTileNode,
  getPasteTilePreview,
  getPasteTileMeta,
} from "@/lib/richInputTile";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  appFixture,
  builtinFixture as builtin,
  customFixture as custom,
} from "@/lib/skills/__fixtures__/picker";
import type { SkillsList } from "@/refresh-pages/admin/SkillsPage/interfaces";
import type { ExternalAppUserResponse } from "@/app/craft/v1/apps/registry";

// No backend in Storybook — isolate the SWR cache and skip revalidation so
// hooks fall back to empty defaults or the per-story `fallback` seed.
const SWR_NO_FETCH = {
  provider: () => new Map(),
  revalidateOnMount: false,
  revalidateIfStale: false,
  revalidateOnFocus: false,
  revalidateOnReconnect: false,
};

interface SkillPickerFixture {
  skills?: SkillsList;
  apps?: ExternalAppUserResponse[];
}

function fixtureToFallback(
  fixture: SkillPickerFixture
): Record<string, unknown> {
  const fallback: Record<string, unknown> = {};
  if (fixture.skills !== undefined) {
    fallback[SWR_KEYS.userSkills] = fixture.skills;
  }
  if (fixture.apps !== undefined) {
    fallback[SWR_KEYS.buildExternalApps] = fixture.apps;
  }
  return fallback;
}

const meta: Meta<typeof InputBar> = {
  title: "Apps/Craft/Input Bar/Input Bar",
  component: InputBar,
  tags: ["autodocs"],
  decorators: [
    (Story, context) => {
      const fixture = context.parameters?.skillPicker as
        | SkillPickerFixture
        | undefined;
      const fallback = fixture ? fixtureToFallback(fixture) : {};
      return (
        <SWRConfig value={{ ...SWR_NO_FETCH, fallback }}>
          <UserProvider>
            <UploadFilesProvider>
              <div className="w-[640px]">
                <Story />
              </div>
            </UploadFilesProvider>
          </UserProvider>
        </SWRConfig>
      );
    },
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

const TILE_PASTE_TEXT = `def fibonacci(n: int) -> int:
    if n < 2:
        return n
    a, b = 0, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return b`;

/**
 * Shows the inline rich tiles inside the input: a blue skill tile (from the
 * slash-skill picker) and a gray paste tile (from collapsing a large paste). The
 * tiles are real DOM nodes built by `createRichInputTileNode` — the same path
 * the live input uses — injected into the contentEditable and synced via an
 * `input` event so the placeholder clears and the message serializes correctly.
 */
function TilesDemo() {
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const editable =
      wrapperRef.current?.querySelector<HTMLDivElement>('[role="textbox"]');
    if (!editable || editable.childNodes.length > 0) return;

    editable.appendChild(document.createTextNode("Refactor "));
    editable.appendChild(
      createRichInputTileNode({
        type: "skill",
        text: "/deep-research ",
        preview: "Skill: deep-research",
        meta: "",
        skillSlug: "deep-research",
      })
    );
    editable.appendChild(document.createTextNode(" using this snippet "));
    editable.appendChild(
      createRichInputTileNode({
        type: "paste",
        text: TILE_PASTE_TEXT,
        preview: getPasteTilePreview(TILE_PASTE_TEXT),
        meta: getPasteTileMeta(TILE_PASTE_TEXT),
      })
    );
    editable.appendChild(document.createTextNode(" "));

    // Mirror the live paths: fire an input event so the hook syncs state from
    // the DOM (clears the placeholder, serializes tile text into the message).
    editable.dispatchEvent(new InputEvent("input", { bubbles: true }));
  }, []);

  return (
    <div ref={wrapperRef}>
      <InputBar
        onSubmit={(message, files) =>
          console.log("onSubmit", { message, files })
        }
        isRunning={false}
        placeholder="Continue the conversation..."
      />
    </div>
  );
}

export const Tiles: Story = {
  render: () => <TilesDemo />,
};

const SLASH_PICKER_DESCRIPTION =
  "Type `/` in the input below to open the skill picker.";

export const SlashPickerSkillsOnly: Story = {
  parameters: {
    docs: { description: { story: SLASH_PICKER_DESCRIPTION } },
    skillPicker: {
      skills: {
        builtins: [
          builtin({ slug: "pptx", name: "PPTX" }),
          builtin({
            slug: "image-generation",
            name: "Image Generation",
            description: "Generate images from a prompt.",
          }),
          builtin({
            slug: "company-search",
            name: "Company Search",
            description: "Search the company knowledge base.",
          }),
        ],
        customs: [custom()],
      },
      apps: [],
    } satisfies SkillPickerFixture,
  },
};

export const SlashPickerAppsOnly: Story = {
  parameters: {
    docs: { description: { story: SLASH_PICKER_DESCRIPTION } },
    skillPicker: {
      skills: { builtins: [], customs: [] },
      apps: [
        appFixture({
          slug: "slack",
          name: "Slack",
          description: "Search Slack messages.",
          app_type: "SLACK",
          authenticated: true,
        }),
        appFixture({
          slug: "gmail",
          name: "Gmail",
          description: "Search Gmail threads.",
          app_type: "GMAIL",
          authenticated: false,
        }),
      ],
    } satisfies SkillPickerFixture,
  },
};

export const SlashPickerSkillsAndApps: Story = {
  parameters: {
    docs: { description: { story: SLASH_PICKER_DESCRIPTION } },
    skillPicker: {
      skills: {
        builtins: [
          builtin({ slug: "pptx", name: "PPTX" }),
          builtin({
            slug: "image-generation",
            name: "Image Generation",
            description: "Generate images from a prompt.",
          }),
          builtin({
            slug: "company-search",
            name: "Company Search",
            description: "Search the company knowledge base.",
          }),
        ],
        customs: [custom()],
      },
      apps: [
        appFixture({
          slug: "slack",
          name: "Slack",
          description: "Search Slack messages.",
          app_type: "SLACK",
          authenticated: true,
        }),
        appFixture({
          slug: "gmail",
          name: "Gmail",
          description: "Search Gmail threads.",
          app_type: "GMAIL",
          authenticated: false,
        }),
        appFixture({
          slug: "linear",
          name: "Linear",
          description: "Read & comment on Linear issues.",
          app_type: "LINEAR",
          authenticated: true,
        }),
      ],
    } satisfies SkillPickerFixture,
  },
};

export const SlashPickerEmpty: Story = {
  parameters: {
    docs: { description: { story: SLASH_PICKER_DESCRIPTION } },
    skillPicker: {
      skills: { builtins: [], customs: [] },
      apps: [],
    } satisfies SkillPickerFixture,
  },
};
