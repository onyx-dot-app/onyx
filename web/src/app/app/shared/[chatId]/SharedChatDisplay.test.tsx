import { createRef } from "react";
import { act, render, screen } from "@tests/setup/test-utils";
import {
  PacketType,
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
      ],
    ],
    published_files: publishedFiles,
  };
}

// The shared chat in the app chrome's workspace, which the panel needs
function renderSharedChat(chatSession: BackendChatSession) {
  const elements = {
    workspace: createRef<HTMLDivElement>(),
    page: createRef<HTMLDivElement>(),
  };
  render(
    <AppWorkspaceElementsContext.Provider value={elements}>
      <SharedChatDisplay chatSession={chatSession} persona={{} as Agent} />
    </AppWorkspaceElementsContext.Provider>
  );
}

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

  const filesButton = await screen.findByRole("button", { name: "Files" });
  expect(filesButton).toHaveAttribute("aria-pressed", "false");

  await act(async () => {
    screen.getByRole("button", { name: "Preview report.md" }).click();
  });
  expect(
    await screen.findByRole("region", { name: "Preview of Q3 report" })
  ).toBeVisible();
  expect(filesButton).toHaveAttribute("aria-pressed", "true");
  // No Sources tab: a shared chat shows only its files
  expect(screen.queryByRole("tab", { name: "Sources" })).toBeNull();

  act(() => filesButton.click());
  expect(filesButton).toHaveAttribute("aria-pressed", "false");
});

test("a shared chat's card opens its file when the chat lists no files", async () => {
  jest.mocked(fetchChatFile).mockResolvedValue(
    new Response("Revenue grew.", {
      headers: { "Content-Type": "text/markdown" },
    })
  );
  // A published file without a path: its card shows, but the load lists no
  // files
  renderSharedChat(sharedChat([]));
  await screen.findByRole("button", { name: "Preview report.md" });
  expect(screen.queryByRole("button", { name: "Files" })).toBeNull();

  await act(async () => {
    screen.getByRole("button", { name: "Preview report.md" }).click();
  });
  expect(
    await screen.findByRole("region", { name: "Preview of Q3 report" })
  ).toBeVisible();
});
