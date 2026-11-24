import { act, render, screen } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { MemoizedAnchor } from "@/lib/timeline/chat/message/MemoizedTextComponents";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import type { ChatArtifactFile } from "@/lib/chat/publishedFiles";
import { CHAT_FILES_PANEL } from "@/sections/chat/ChatRightPanel";
import { PublishedFilesPanelContext } from "@/sections/chat/PublishedFileCards";
import { OnyxDocument } from "@/lib/search/types";
import { ValidSources } from "@/lib/connectors/types/source";

const FILE_ID = "3f2a9c1e-0000-4000-8000-000000000000";
const FILE_URL = `https://onyx.example.com/api/chat/file/${FILE_ID}`;

const citedDoc: OnyxDocument = {
  document_id: "doc_abc",
  semantic_identifier: "Quarterly Report",
  link: "https://docs.example.com/report",
  source_type: ValidSources.Web,
  blurb: "",
  boost: 0,
  hidden: false,
  score: 1,
  chunk_ind: 0,
  match_highlights: [],
  metadata: {},
  updated_at: null,
  is_internet: false,
};

describe("MemoizedAnchor", () => {
  test("bold-labeled chat file link opens the file preview", async () => {
    const updatePresentingDocument = jest.fn();
    render(
      <MemoizedAnchor
        href={FILE_URL}
        updatePresentingDocument={updatePresentingDocument}
      >
        <strong>Download the Word document</strong>
      </MemoizedAnchor>
    );

    const button = screen.getByRole("button", {
      name: "Download the Word document",
    });
    expect(button.querySelector("strong")).not.toBeNull();

    await userEvent.click(button);
    expect(updatePresentingDocument).toHaveBeenCalledWith({
      document_id: FILE_ID,
      semantic_identifier: "Download the Word document",
    });
  });

  test("bold-labeled external link renders as a link", () => {
    render(
      <MemoizedAnchor
        href="https://example.com/page"
        updatePresentingDocument={jest.fn()}
      >
        {[<strong key="b">Example</strong>, " page"]}
      </MemoizedAnchor>
    );

    const link = screen.getByRole("link", { name: "Example page" });
    expect(link).toHaveAttribute("href", "https://example.com/page");
  });

  test("plain citation label still renders as a citation", () => {
    render(
      <MemoizedAnchor
        href={citedDoc.link}
        updatePresentingDocument={jest.fn()}
        docs={[citedDoc]}
        citations={{ 1: citedDoc.document_id }}
      >
        [1]
      </MemoizedAnchor>
    );

    expect(screen.getByText("Quarterly Report")).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });
});

const ARTIFACT_ID = "5b1d2c3e-0000-4000-8000-000000000000";

// Version 1 of the artifact, in chat "a", while the chat lists only version 1
const ARTIFACT_V1: ChatArtifactFile = {
  file_id: "report-v1",
  name: "report.md",
  title: null,
  path: "/outputs/report.md",
  display_path: "report.md",
  size: 1,
  mime_type: "text/markdown",
  artifact_id: ARTIFACT_ID,
  version: 1,
  thumbnail_file_id: null,
  chat_id: "a",
  access: "owner",
};

const ARTIFACT_V2: ChatArtifactFile = {
  ...ARTIFACT_V1,
  file_id: "report-v2",
  version: 2,
};

describe("artifact link", () => {
  // The pending metadata requests, oldest first
  let responders: ((file: ChatArtifactFile) => void)[] = [];
  const respond = (file: ChatArtifactFile) => responders[0]?.(file);

  beforeEach(() => {
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: "a",
    });
    useChatSessionStore.getState().createSession("a");
    useChatSessionStore.getState().createSession("b");
    responders = [];
    jest.spyOn(global, "fetch").mockImplementation(
      () =>
        new Promise((resolve) => {
          responders.push((file) =>
            resolve(new Response(JSON.stringify(file), { status: 200 }))
          );
        })
    );
  });

  afterEach(() => jest.restoreAllMocks());

  async function clickLink(href: string) {
    render(
      <PublishedFilesPanelContext.Provider value={CHAT_FILES_PANEL}>
        <MemoizedAnchor href={href} updatePresentingDocument={jest.fn()}>
          the report
        </MemoizedAnchor>
      </PublishedFilesPanelContext.Provider>
    );
    await userEvent.click(screen.getByRole("link", { name: "the report" }));
  }

  function fileTabs(sessionId: string) {
    return useChatSessionStore.getState().sessions.get(sessionId)?.rightPanel
      .fileTabs;
  }

  test("a link that names a version opens its tab pinned to it", async () => {
    await clickLink(`https://onyx.example.com/app/artifacts/${ARTIFACT_ID}/v1`);
    await act(async () => respond(ARTIFACT_V1));
    expect(fileTabs("a")).toEqual([{ file: ARTIFACT_V1, pinned: true }]);
  });

  test("a link that names no version follows the newest", async () => {
    await clickLink(`https://onyx.example.com/app/artifacts/${ARTIFACT_ID}`);
    await act(async () => respond(ARTIFACT_V1));
    expect(fileTabs("a")).toEqual([{ file: ARTIFACT_V1, pinned: false }]);
  });

  test("a response after a chat switch opens nothing", async () => {
    await clickLink(`https://onyx.example.com/app/artifacts/${ARTIFACT_ID}/v1`);
    act(() => useChatSessionStore.getState().setCurrentSession("b"));
    await act(async () => respond(ARTIFACT_V1));
    expect(fileTabs("a")).toEqual([]);
    expect(fileTabs("b")).toEqual([]);
  });

  test("a slower response to an earlier click does not replace a later click's file", async () => {
    render(
      <PublishedFilesPanelContext.Provider value={CHAT_FILES_PANEL}>
        <MemoizedAnchor
          href={`https://onyx.example.com/app/artifacts/${ARTIFACT_ID}/v1`}
          updatePresentingDocument={jest.fn()}
        >
          version 1
        </MemoizedAnchor>
        <MemoizedAnchor
          href={`https://onyx.example.com/app/artifacts/${ARTIFACT_ID}/v2`}
          updatePresentingDocument={jest.fn()}
        >
          version 2
        </MemoizedAnchor>
      </PublishedFilesPanelContext.Provider>
    );
    await userEvent.click(screen.getByRole("link", { name: "version 1" }));
    await userEvent.click(screen.getByRole("link", { name: "version 2" }));
    const [answerV1, answerV2] = responders;
    await act(async () => answerV2?.(ARTIFACT_V2));
    await act(async () => answerV1?.(ARTIFACT_V1));
    expect(fileTabs("a")).toEqual([{ file: ARTIFACT_V2, pinned: true }]);
  });
});
