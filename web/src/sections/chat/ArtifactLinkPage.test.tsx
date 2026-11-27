import { act, render, waitFor } from "@tests/setup/test-utils";
import { SWRConfig } from "swr";
import ArtifactLinkPage from "@/sections/chat/ArtifactLinkPage";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { ChatArtifactFile } from "@/lib/chat/publishedFiles";

const ARTIFACT_ID = "5b1d2c3e-0000-4000-8000-000000000000";
const LINK = `/app/artifacts/${ARTIFACT_ID}/v1`;

const mockGo = jest.fn();
const mockNavigation = { go: mockGo };
const UNAVAILABLE = "This file is not available";
let mockPathname = LINK;

jest.mock("@opal/navigation", () => ({
  ...jest.requireActual<typeof import("@opal/navigation")>("@opal/navigation"),
  useNavigation: () => mockNavigation,
  usePathname: () => mockPathname,
}));

const FILE: ChatArtifactFile = {
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
  chat_id: "chat-1",
  access: "owner",
};

describe("ArtifactLinkPage", () => {
  let respond: (file: ChatArtifactFile) => void = () => undefined;
  let fail: () => void = () => undefined;

  beforeEach(() => {
    mockGo.mockClear();
    mockPathname = LINK;
    jest.spyOn(global, "fetch").mockReturnValue(
      new Promise((resolve) => {
        respond = (file) =>
          resolve(new Response(JSON.stringify(file), { status: 200 }));
        fail = () =>
          resolve(
            new Response(JSON.stringify({ detail: "" }), { status: 404 })
          );
      })
    );
  });

  afterEach(() => jest.restoreAllMocks());

  function renderPage() {
    return render(<ArtifactLinkPage artifactId={ARTIFACT_ID} version={1} />);
  }

  test("the owner goes to the owning chat with the version", async () => {
    renderPage();
    await act(async () => respond(FILE));
    expect(mockGo).toHaveBeenCalledTimes(1);
    expect(mockGo.mock.calls[0]?.[0]).toContain("chat-1");
  });

  test("a cached response of an earlier visit waits for the fresh one", async () => {
    const cache = new Map([
      [
        SWR_KEYS.chatArtifact(ARTIFACT_ID, 1),
        { data: { ...FILE, chat_id: "old" } },
      ],
    ]);
    render(
      <SWRConfig value={{ provider: () => cache }}>
        <ArtifactLinkPage artifactId={ARTIFACT_ID} version={1} />
      </SWRConfig>
    );
    await act(async () => {});
    expect(mockGo).not.toHaveBeenCalled();
    // SWR revalidates a cached key on the next animation frame
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    await act(async () => respond(FILE));
    expect(mockGo).toHaveBeenCalledTimes(1);
    expect(mockGo.mock.calls[0]?.[0]).toContain("chat-1");
  });

  test("a response after the user left the link sends the user nowhere", async () => {
    const { rerender } = renderPage();
    mockPathname = "/app/agents";
    rerender(<ArtifactLinkPage artifactId={ARTIFACT_ID} version={1} />);
    await act(async () => respond(FILE));
    expect(mockGo).not.toHaveBeenCalled();
  });

  test("a link the user may not open shows the unavailable page", async () => {
    const { findByText } = renderPage();
    await act(async () => fail());
    expect(await findByText(UNAVAILABLE)).toBeInTheDocument();
  });

  test("a cached error waits for the fresh response", async () => {
    const cache = new Map([
      [
        SWR_KEYS.chatArtifact(ARTIFACT_ID, 1),
        { error: new Error("not found") },
      ],
    ]);
    const { findByTestId, queryByText } = render(
      <SWRConfig value={{ provider: () => cache }}>
        <ArtifactLinkPage artifactId={ARTIFACT_ID} version={1} />
      </SWRConfig>
    );
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    await act(async () => respond({ ...FILE, access: "file_only" }));
    expect(await findByTestId("artifact-link-header")).toHaveTextContent(
      "report.md"
    );
    expect(queryByText(UNAVAILABLE)).toBeNull();
  });

  test("an error after the user left the link shows no unavailable page", async () => {
    const { rerender, queryByText } = renderPage();
    mockPathname = "/app/agents";
    rerender(<ArtifactLinkPage artifactId={ARTIFACT_ID} version={1} />);
    await act(async () => fail());
    expect(queryByText(UNAVAILABLE)).toBeNull();
  });
});
