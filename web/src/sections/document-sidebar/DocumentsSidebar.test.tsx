import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import { Message, ResearchType } from "@/app/app/interfaces";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { Packet, StopReason } from "@/app/app/services/streamingModels";
import { OnyxDocument } from "@/lib/search/interfaces";
import { ValidSources } from "@/lib/types";
import DocumentsSidebar from "@/sections/document-sidebar/DocumentsSidebar";

function document(id: string, title: string, link = ""): OnyxDocument {
  return {
    document_id: id,
    semantic_identifier: title,
    link,
    source_type: ValidSources.Web,
    blurb: "",
    boost: 0,
    hidden: false,
    score: 1,
    chunk_ind: 0,
    match_highlights: [],
    metadata: {},
    updated_at: null,
    is_internet: true,
  };
}

function packet(obj: Packet["obj"]): Packet {
  return { placement: { turn_index: 0, tab_index: 0 }, obj };
}

function message(overrides: Partial<Message> = {}): Message {
  return {
    nodeId: 1,
    type: "assistant",
    message: "",
    files: [],
    toolCall: null,
    parentNodeId: null,
    packets: [
      packet({
        type: "message_start",
        id: "answer",
        content: "<think>Private reasoning</think>Check the runbook [1].",
        final_documents: null,
      }),
      packet({
        type: "message_delta",
        content: "\n\n| Check | Owner |\n| --- | --- |\n| Deploy | Alex |",
      }),
      packet({
        type: "citation_info",
        citation_number: 1,
        document_id: "runbook",
      }),
      packet({
        type: "citation_info",
        citation_number: 2,
        document_id: "checklist",
      }),
      packet({
        type: "citation_info",
        citation_number: 3,
        document_id: "runbook",
      }),
      packet({ type: "stop", stop_reason: StopReason.FINISHED }),
    ],
    documents: [
      document("uncited", "Uncited source", "https://example.com/uncited"),
      document("checklist", "Release checklist"),
      document("runbook", "Deployment runbook", "https://example.com/runbook"),
    ],
    ...overrides,
  };
}

function selectMessage(selected: Message) {
  const store = useChatSessionStore.getState();
  store.updateSessionMessageTree(
    "references",
    new Map([[selected.nodeId, selected]])
  );
  store.updateSelectedNodeForDocDisplay("references", selected.nodeId);
}

function renderSidebar(selected: Message) {
  selectMessage(selected);
  return render(
    <DocumentsSidebar
      closeSidebar={jest.fn()}
      selectedDocuments={null}
      modal={false}
      setPresentingDocument={jest.fn()}
    />
  );
}

beforeEach(() => {
  useChatSessionStore.setState({ sessions: new Map(), currentSessionId: null });
  const store = useChatSessionStore.getState();
  store.createSession("references");
  store.setCurrentSession("references");
});

afterEach(() => jest.restoreAllMocks());

test("copies the answer with cited sources in citation order, once each", async () => {
  const user = setupUser();
  const write = jest.spyOn(navigator.clipboard, "writeText");
  renderSidebar(message());

  expect(screen.getByText("Cited Sources")).toBeInTheDocument();
  expect(screen.getByText("More")).toBeInTheDocument();

  await user.click(
    screen.getByRole("button", { name: "Copy with references" })
  );

  expect(write).toHaveBeenCalledWith(
    "Check the runbook [1].\n\n| Check | Owner |\n| --- | --- |\n| Deploy | Alex |\n\n## Cited Sources\n\n- [Deployment runbook](<https://example.com/runbook>)\n- Release checklist"
  );
});

test("copies the newly selected answer and its sources", async () => {
  const user = setupUser();
  const write = jest.spyOn(navigator.clipboard, "writeText");
  renderSidebar(message());

  act(() =>
    selectMessage(
      message({
        nodeId: 2,
        packets: [
          packet({
            type: "message_start",
            id: "second",
            content: "Second answer.",
            final_documents: null,
          }),
          packet({
            type: "citation_info",
            citation_number: 1,
            document_id: "second",
          }),
          packet({ type: "stop" }),
        ],
        documents: [
          document("second", "Second source", "https://example.com/second"),
        ],
      })
    )
  );
  await user.click(
    screen.getByRole("button", { name: "Copy with references" })
  );
  expect(write).toHaveBeenCalledWith(
    "Second answer.\n\n## Cited Sources\n\n- [Second source](<https://example.com/second>)"
  );
});

test.each([
  { name: "no documents", documents: [] },
  {
    name: "only uncited documents",
    documents: [document("uncited", "Uncited source")],
  },
])(
  "copies missing references with $name without an empty cited section",
  async ({ documents }) => {
    const user = setupUser();
    const write = jest.spyOn(navigator.clipboard, "writeText");
    renderSidebar(message({ documents }));
    expect(screen.queryByText("Cited Sources")).not.toBeInTheDocument();
    expect(screen.queryByText("More")).not.toBeInTheDocument();
    if (documents.length > 0) {
      expect(screen.getByText("Found Sources")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "Uncited source" })
      ).toBeInTheDocument();
    }
    await user.click(
      screen.getByRole("button", { name: "Copy with references" })
    );
    expect(write).toHaveBeenCalledWith(
      expect.stringContaining(
        "## Cited Sources\n\n- Source details unavailable\n- Source details unavailable"
      )
    );
  }
);

test.each([
  ["generating", message({ is_generating: true })],
  ["streaming", message({ packets: message().packets.slice(0, -1) })],
  [
    "uncited",
    message({
      packets: message().packets.filter(
        (item) => item.obj.type !== "citation_info"
      ),
    }),
  ],
  ["deep research", message({ researchType: ResearchType.Deep })],
  [
    "cancelled",
    message({
      packets: [
        ...message().packets.slice(0, -1),
        packet({ type: "stop", stop_reason: StopReason.USER_CANCELLED }),
      ],
    }),
  ],
  [
    "failed",
    message({
      packets: [
        ...message().packets,
        packet({ type: "error", message: "Failed" }),
      ],
    }),
  ],
])("does not offer reference copying for %s answers", (_name, selected) => {
  renderSidebar(selected);
  expect(
    screen.queryByRole("button", { name: "Copy with references" })
  ).not.toBeInTheDocument();
});

test("allows retrying after the clipboard rejects a write", async () => {
  const user = setupUser();
  const write = jest
    .spyOn(navigator.clipboard, "writeText")
    .mockRejectedValueOnce(new Error("Clipboard blocked"));
  jest.spyOn(console, "error").mockImplementation(() => {});
  renderSidebar(message());
  const copyButton = screen.getByRole("button", {
    name: "Copy with references",
  });
  await user.click(copyButton);
  await waitFor(() =>
    expect(console.error).toHaveBeenCalledWith(
      "Failed to copy:",
      expect.any(Error)
    )
  );
  await user.click(copyButton);
  expect(write).toHaveBeenCalledTimes(2);
});
