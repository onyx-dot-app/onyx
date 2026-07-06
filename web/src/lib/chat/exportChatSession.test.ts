import {
  BackendChatSession,
  BackendMessage,
  ChatSessionSharedStatus,
} from "@/app/app/interfaces";
import { downloadFile } from "@/lib/download";
import { exportChatSession } from "./exportChatSession";

jest.mock("@/lib/download", () => ({
  downloadFile: jest.fn(),
}));

const mockedDownloadFile = downloadFile as jest.MockedFunction<
  typeof downloadFile
>;

function makeMessage(
  message_type: string,
  message: string,
  overrides: Partial<BackendMessage> = {}
): BackendMessage {
  return {
    message_id: 0,
    message_type,
    research_type: null,
    parent_message: null,
    latest_child_message: null,
    message,
    rephrased_query: null,
    context_docs: null,
    time_sent: "2026-01-01T00:00:00Z",
    overridden_model: "",
    alternate_assistant_id: null,
    chat_session_id: "session-1",
    citations: null,
    files: [],
    tool_call: null,
    current_feedback: null,
    sub_questions: [],
    comments: null,
    parentMessageId: null,
    refined_answer_improvement: null,
    is_agentic: null,
    preferred_response_id: null,
    model_display_name: null,
    error: null,
    ...overrides,
  };
}

function makeSession(messages: BackendMessage[]): BackendChatSession {
  return {
    chat_session_id: "session-1",
    description: "",
    persona_id: 0,
    persona_name: "",
    messages,
    time_created: "2026-01-01T00:00:00Z",
    time_updated: "2026-01-01T00:00:00Z",
    shared_status: ChatSessionSharedStatus.Private,
    current_temperature_override: null,
    owner_name: null,
    packets: [],
  };
}

function mockFetchOk(session: BackendChatSession): void {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => session,
  }) as unknown as typeof fetch;
}

/** Grab the `{ filename, content, mimeType }` of the single download call. */
function lastDownload(): {
  filename: string;
  content: string;
  mimeType?: string;
} {
  expect(mockedDownloadFile).toHaveBeenCalledTimes(1);
  const call = mockedDownloadFile.mock.calls[0];
  if (!call) {
    throw new Error("downloadFile was not called");
  }
  const [filename, opts] = call;
  if (!("content" in opts)) {
    throw new Error("expected content-based download");
  }
  return { filename, content: opts.content, mimeType: opts.mimeType };
}

beforeEach(() => {
  jest.clearAllMocks();
});

describe("exportChatSession", () => {
  const conversation = [
    makeMessage("user", "Hello there"),
    makeMessage("assistant", "Hi! How can I help?"),
  ];

  it("exports a plain-text transcript with a .txt filename", async () => {
    mockFetchOk(makeSession(conversation));

    await exportChatSession("session-1", "My Chat", "text");

    const { filename, content, mimeType } = lastDownload();
    expect(filename).toBe("My_Chat.txt");
    expect(mimeType).toBe("text/plain");
    expect(content).toBe(
      "My Chat\n\nUser:\nHello there\n\nAssistant:\nHi! How can I help?\n"
    );
  });

  it("exports a markdown transcript with a .md filename and headings", async () => {
    mockFetchOk(makeSession(conversation));

    await exportChatSession("session-1", "My Chat", "markdown");

    const { filename, content, mimeType } = lastDownload();
    expect(filename).toBe("My_Chat.md");
    expect(mimeType).toBe("text/markdown");
    expect(content).toBe(
      "# My Chat\n\n## User\n\nHello there\n\n## Assistant\n\nHi! How can I help?\n"
    );
  });

  it("omits system, tool-call, reminder, and empty messages", async () => {
    mockFetchOk(
      makeSession([
        makeMessage("system", "you are a helpful assistant"),
        makeMessage("user", "Question?"),
        makeMessage("tool_call_response", "{...}"),
        makeMessage("assistant", "Answer."),
        makeMessage("user_reminder", "reminder"),
        makeMessage("assistant", "   "),
      ])
    );

    await exportChatSession("session-1", "Chat", "text");

    const { content } = lastDownload();
    expect(content).toBe("Chat\n\nUser:\nQuestion?\n\nAssistant:\nAnswer.\n");
  });

  it("sanitizes unsafe characters in the filename", async () => {
    mockFetchOk(makeSession(conversation));

    await exportChatSession("session-1", "a/b: report? <v2>", "text");

    expect(lastDownload().filename).toBe("a_b__report___v2_.txt");
  });

  it("falls back to the default chat name when the name is blank", async () => {
    mockFetchOk(makeSession(conversation));

    await exportChatSession("session-1", "   ", "markdown");

    const { filename, content } = lastDownload();
    expect(filename).toBe("New_Chat.md");
    expect(content.startsWith("# New Chat\n")).toBe(true);
  });

  it("throws and does not download when the fetch fails", async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 404,
    }) as unknown as typeof fetch;

    await expect(exportChatSession("missing", "Chat", "text")).rejects.toThrow(
      "Failed to fetch chat session: 404"
    );
    expect(mockedDownloadFile).not.toHaveBeenCalled();
  });
});
