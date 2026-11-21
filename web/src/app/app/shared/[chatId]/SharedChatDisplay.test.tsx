import { useMemo, useRef, useState } from "react";
import { act, render, screen } from "@tests/setup/test-utils";
import {
  PacketType,
  StopReason,
  type PublishedFile,
} from "@/app/app/services/streamingModels";
import {
  ChatSessionSharedStatus,
  type BackendChatSession,
  type BackendMessage,
} from "@/app/app/types";
import type { Agent } from "@/lib/agents/types";
import { fetchChatFile } from "@/lib/chat/svc";
import SharedChatDisplay from "@/app/app/shared/[chatId]/SharedChatDisplay";
import { AppWorkspaceElementsContext } from "@/layouts/chromes/AppWorkspace";

jest.mock("@/lib/chat/svc", () => ({
  ...jest.requireActual("@/lib/chat/svc"),
  fetchChatFile: jest.fn(),
}));
jest.mock("@/lib/languageModels/hooks", () => ({
  useLanguageModels: () => ({ llmProviders: [] }),
}));
jest.mock("@/lib/navigation/hooks", () => ({
  useAppPosition: () => ({ linkToNewSession: () => ({}) }),
}));
jest.mock("@/sections/input/SharedAppInputBar", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/providers/VoiceModeProvider", () => ({
  useVoiceMode: () => ({
    resetTTS: jest.fn(),
    streamTTS: jest.fn(),
    stopTTS: jest.fn(),
    revealedCharCount: 0,
    autoPlayback: false,
    isAudioSyncActive: false,
    activeMessageNodeId: null,
    isAwaitingAutoPlaybackStart: false,
  }),
}));
jest.mock("@/app/app/message/HumanMessage", () => ({
  __esModule: true,
  default: () => null,
}));

const REPORT: PublishedFile = {
  file_id: "file-1",
  name: "report.md",
  title: "Q3 report",
  path: "/home/onyx/report.md",
  display_path: "report.md",
  size: 10,
  mime_type: "text/markdown",
  artifact_id: "artifact-report",
  version: 1,
  thumbnail_file_id: null,
};

function message(
  id: number,
  type: "user" | "assistant",
  parent: number | null,
  child: number | null
): BackendMessage {
  return {
    message_id: id,
    message_type: type,
    parent_message: parent,
    latest_child_message: child,
    message: "",
    files: [],
    time_sent: new Date().toISOString(),
    citations: null,
    context_docs: null,
    tool_call: null,
  } as unknown as BackendMessage;
}

function sharedChat(
  publishedFiles: PublishedFile[] = [REPORT]
): BackendChatSession {
  return {
    chat_session_id: "shared",
    description: "Shared chat",
    persona_id: 0,
    persona_name: "Assistant",
    messages: [message(1, "user", null, 2), message(2, "assistant", 1, null)],
    time_created: new Date().toISOString(),
    time_updated: new Date().toISOString(),
    shared_status: ChatSessionSharedStatus.Public,
    current_temperature_override: null,
    current_reasoning_effort_override: null,
    owner_name: null,
    packets: [
      [
        {
          placement: { turn_index: 0, tab_index: 0 },
          obj: {
            type: PacketType.PUBLISH_FILES_END,
            files: [REPORT],
            error: null,
          },
        },
        // A saved reply's replay ends with its stop
        {
          placement: { turn_index: 0, tab_index: 0 },
          obj: { type: PacketType.STOP, stop_reason: StopReason.FINISHED },
        },
      ],
    ],
    published_files: publishedFiles,
  };
}

// The shared chat in the app chrome's workspace, which the panel needs
function SharedChatInWorkspace({
  chatSession,
}: {
  chatSession: BackendChatSession;
}) {
  const workspace = useRef<HTMLDivElement>(null);
  const page = useRef<HTMLDivElement>(null);
  const [panelToggleSlot, setPanelToggleSlot] = useState<HTMLElement | null>(
    null
  );
  const elements = useMemo(
    () => ({ workspace, page, panelToggleSlot }),
    [panelToggleSlot]
  );
  return (
    <AppWorkspaceElementsContext.Provider value={elements}>
      <div ref={workspace}>
        <div ref={setPanelToggleSlot} />
        <SharedChatDisplay chatSession={chatSession} persona={{} as Agent} />
      </div>
    </AppWorkspaceElementsContext.Provider>
  );
}

function renderSharedChat(chatSession: BackendChatSession) {
  render(<SharedChatInWorkspace chatSession={chatSession} />);
}

const panelToggle = () => screen.getByRole("button", { name: "Toggle panel" });

beforeAll(() => {
  Object.defineProperty(window.URL, "createObjectURL", {
    configurable: true,
    value: () => "blob:report",
  });
  Object.defineProperty(window.URL, "revokeObjectURL", {
    configurable: true,
    value: () => undefined,
  });
});

test("a shared chat's card opens its file in the Files panel, read-only", async () => {
  jest.mocked(fetchChatFile).mockResolvedValue(
    new Response("Revenue grew.", {
      headers: { "Content-Type": "text/markdown" },
    })
  );
  renderSharedChat(sharedChat());

  await screen.findByRole("button", { name: "Preview report.md" });
  expect(panelToggle()).toHaveAttribute("aria-expanded", "false");

  await act(async () => {
    screen.getByRole("button", { name: "Preview report.md" }).click();
  });
  expect(
    await screen.findByRole("region", { name: "Preview of Q3 report" })
  ).toBeVisible();
  expect(panelToggle()).toHaveAttribute("aria-expanded", "true");
  // No Sources tab: a shared chat shows only its files
  expect(screen.queryByRole("tab", { name: "Sources" })).toBeNull();

  act(() => panelToggle().click());
  expect(panelToggle()).toHaveAttribute("aria-expanded", "false");
});

test("a shared chat's card opens its file when the chat lists no files", async () => {
  jest.mocked(fetchChatFile).mockResolvedValue(
    new Response("Revenue grew.", {
      headers: { "Content-Type": "text/markdown" },
    })
  );
  // A published file whose object is missing: its card shows, but the load
  // lists no files
  renderSharedChat(sharedChat([]));
  await screen.findByRole("button", { name: "Preview report.md" });
  // The panel toggle shows also when the chat lists no files
  expect(panelToggle()).toBeVisible();

  await act(async () => {
    screen.getByRole("button", { name: "Preview report.md" }).click();
  });
  expect(
    await screen.findByRole("region", { name: "Preview of Q3 report" })
  ).toBeVisible();
});

test("a shared chat's card of an older version opens that version, labelled", async () => {
  jest.mocked(fetchChatFile).mockResolvedValue(
    new Response("Revenue grew.", {
      headers: { "Content-Type": "text/markdown" },
    })
  );
  // A background subagent published a newer version, which only the list
  // holds
  renderSharedChat(
    sharedChat([
      { ...REPORT, file_id: "file-2", title: "Q4 report", version: 2 },
    ])
  );

  await act(async () => {
    screen.getByRole("button", { name: "Preview report.md" }).click();
  });
  expect(
    await screen.findByRole("region", { name: "Preview of Q3 report" })
  ).toBeVisible();
  expect(fetchChatFile).toHaveBeenLastCalledWith(
    "file-1",
    false,
    expect.any(AbortSignal)
  );
  expect(
    screen.getByRole("tab", { name: "Q3 report (v1 of 2)" })
  ).toBeVisible();
});

test("a shared chat's reload reads the shared chat's latest page for a newer list", async () => {
  renderSharedChat(sharedChat());
  await screen.findByRole("button", { name: "Preview report.md" });
  act(() => panelToggle().click());
  expect(screen.queryByRole("button", { name: "Open Chart" })).toBeNull();

  const chart: PublishedFile = {
    ...REPORT,
    file_id: "file-2",
    name: "chart.md",
    title: "Chart",
    path: "/home/onyx/chart.md",
    display_path: "chart.md",
    artifact_id: "artifact-chart",
  };
  const fetchPage = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(
      new Response(JSON.stringify(sharedChat([chart, REPORT])))
    );
  await act(async () =>
    screen.getByRole("button", { name: "Refresh files" }).click()
  );
  expect(fetchPage).toHaveBeenCalledWith(
    expect.stringMatching(
      /^\/api\/chat\/get-chat-session\/shared\?.*is_shared=true/
    ),
    expect.objectContaining({ cache: "no-store" })
  );
  expect(screen.getByRole("button", { name: "Open Chart" })).toBeVisible();
  fetchPage.mockRestore();
});
