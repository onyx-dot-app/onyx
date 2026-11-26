import {
  PacketType,
  type PublishedFile,
} from "@/app/app/services/streamingModels";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import {
  type BackendChatSession,
  ChatSessionSharedStatus,
  type Message,
} from "@/app/app/types";
import {
  loadOlderChatMessages,
  reloadChatPublishedFiles,
  reloadLatestChatPage,
} from "@/lib/chat/pagedSession";
import { chatPublishedFiles, startChatLoad } from "@/lib/chat/publishedFiles";
import { fetchSettledChatSession } from "@/lib/chat/sessionReadiness";

jest.mock("@/lib/chat/sessionReadiness", () => ({
  ...jest.requireActual("@/lib/chat/sessionReadiness"),
  fetchSettledChatSession: jest.fn(),
}));

const SESSION_ID = "session";

function published(fileId: string, version: number): PublishedFile {
  return {
    file_id: fileId,
    name: "report.md",
    title: null,
    path: "/outputs/report.md",
    display_path: "/outputs/report.md",
    size: 10,
    mime_type: "text/markdown",
    artifact_id: "artifact",
    version,
    thumbnail_file_id: null,
    chat_id: null,
  };
}

function page(files: PublishedFile[]): BackendChatSession {
  return {
    chat_session_id: SESSION_ID,
    description: "Chat",
    persona_id: 0,
    persona_name: "Assistant",
    messages: [],
    time_created: "2026-11-20T00:00:00Z",
    time_updated: "2026-11-20T00:00:00Z",
    shared_status: ChatSessionSharedStatus.Private,
    current_temperature_override: null,
    current_reasoning_effort_override: null,
    owner_name: null,
    packets: [],
    published_files: files,
    is_processing: false,
    current_stream: null,
  };
}

const listedIds = () =>
  useChatSessionStore
    .getState()
    .sessions.get(SESSION_ID)
    ?.loadedPublishedFiles.listed?.map((file) => file.file_id);

beforeEach(() => {
  useChatSessionStore.setState({ sessions: new Map() });
  useChatSessionStore.getState().createSession(SESSION_ID);
});

afterEach(() => {
  jest.restoreAllMocks();
});

test("a Files reload that ends after a newer chat load keeps the newer list", async () => {
  const stale = Promise.withResolvers<BackendChatSession>();
  jest.mocked(fetchSettledChatSession).mockReturnValue(stale.promise);
  const reload = reloadChatPublishedFiles(SESSION_ID);

  useChatSessionStore
    .getState()
    .applyLoadedSession(
      SESSION_ID,
      page([published("v2", 2)]),
      startChatLoad(undefined),
      {}
    );
  stale.resolve(page([published("v1", 1)]));
  await reload;

  expect(listedIds()).toEqual(["v2"]);
});

test("a chat load that ends after a newer Files reload keeps the newer list", async () => {
  const stale = Promise.withResolvers<Response>();
  jest.spyOn(global, "fetch").mockReturnValue(stale.promise);
  const load = reloadLatestChatPage(SESSION_ID);

  jest
    .mocked(fetchSettledChatSession)
    .mockResolvedValue(page([published("v2", 2)]));
  await reloadChatPublishedFiles(SESSION_ID);
  stale.resolve(new Response(JSON.stringify(page([published("v1", 1)]))));
  await load;

  expect(listedIds()).toEqual(["v2"]);
});

test("a Files reload whose page leaves out a live publish's message drops the file that its list leaves out", async () => {
  // A live answer published the file; a delete then removed it.
  const answer: Message = {
    nodeId: 5,
    messageId: 50,
    type: "assistant",
    message: "",
    files: [],
    toolCall: null,
    packets: [
      {
        placement: { turn_index: 0, tab_index: 0 },
        obj: {
          type: PacketType.PUBLISH_FILES_END,
          files: [published("deleted", 1)],
          error: null,
        },
      },
    ],
    parentNodeId: null,
  };
  useChatSessionStore
    .getState()
    .updateSessionMessageTree(SESSION_ID, new Map([[5, answer]]));
  jest.mocked(fetchSettledChatSession).mockResolvedValue(page([]));

  await reloadChatPublishedFiles(SESSION_ID);

  const session = useChatSessionStore.getState().sessions.get(SESSION_ID)!;
  expect(
    chatPublishedFiles(
      session.loadedPublishedFiles,
      session.messageTree,
      SESSION_ID
    )
  ).toEqual([]);
});

const oldest: Message = {
  nodeId: 1,
  messageId: 10,
  type: "user",
  message: "hi",
  files: [],
  toolCall: null,
  packets: [],
  parentNodeId: null,
  childrenNodeIds: [],
  latestChildNodeId: null,
};

test("an empty older page whose recovery fails stops loading older pages", async () => {
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  useChatSessionStore.getState().createSession("session", {
    hasOlderMessages: true,
    messageTree: new Map([[1, oldest]]),
  });
  // The older page is empty; reloading the latest page then fails.
  jest
    .spyOn(global, "fetch")
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ messages: [], packets: [] }), {
        status: 200,
      })
    )
    .mockResolvedValueOnce(new Response("", { status: 500 }));
  jest.spyOn(console, "error").mockImplementation(() => undefined);

  await loadOlderChatMessages("session");

  const session = useChatSessionStore.getState().sessions.get("session");
  expect(session?.hasOlderMessages).toBe(false);
  expect(session?.olderMessagesFailed).toBe(true);
  expect(session?.isLoadingOlderMessages).toBe(false);
});
