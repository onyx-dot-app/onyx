import { act, render, screen, waitFor } from "@tests/setup/test-utils";
import BuildOutputPanel from "@/app/craft/components/OutputPanel";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import {
  fetchOutputInventory,
  fetchPptxPreview,
} from "@/app/craft/services/apiServices";
import type { OutputInventory } from "@/app/craft/types/streamingTypes";

jest.mock("@/app/craft/services/apiServices", () => ({
  ...jest.requireActual("@/app/craft/services/apiServices"),
  fetchOutputInventory: jest.fn(),
  fetchPptxPreview: jest.fn(),
  fetchArtifacts: jest.fn().mockResolvedValue([]),
  fetchWebappInfo: jest.fn().mockResolvedValue({
    has_webapp: false,
    ready: false,
  }),
}));
jest.mock("@/app/craft/components/output-panel/UrlBar", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/app/craft/components/output-panel/FilesTab", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/app/craft/components/output-panel/ArtifactsTab", () => ({
  __esModule: true,
  default: () => null,
}));

const sessionId = "preview-inventory";
const store = () => useBuildSessionStore.getState();
const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;
const originalScrollIntoView = Element.prototype.scrollIntoView;

async function refreshInventory(files: OutputInventory["files"]) {
  jest.mocked(fetchOutputInventory).mockResolvedValue({
    files,
    complete: true,
  });
  await act(async () => store().refreshOutputInventory(sessionId));
}

beforeEach(() => {
  jest.clearAllMocks();
  let nextObjectUrl = 0;
  URL.createObjectURL = jest.fn(() => `blob:preview-${++nextObjectUrl}`);
  URL.revokeObjectURL = jest.fn();
  Element.prototype.scrollIntoView = jest.fn();
  useBuildSessionStore.setState({
    currentSessionId: null,
    sessions: new Map(),
    preProvisioning: { status: "idle" },
    noSessionOutputPanelOpen: false,
    noSessionActiveOutputTab: "files",
  });
  store().createSession(sessionId, { status: "running" });
  store().setCurrentSession(sessionId);
});

afterEach(() => {
  jest.useRealTimers();
  URL.createObjectURL = originalCreateObjectURL;
  URL.revokeObjectURL = originalRevokeObjectURL;
  Element.prototype.scrollIntoView = originalScrollIntoView;
  jest.restoreAllMocks();
});

it("refreshes an open PowerPoint through inventory updates and reuses unchanged conversions", async () => {
  const path = "outputs/deck.pptx";
  jest.mocked(fetchPptxPreview).mockResolvedValue({
    slide_count: 1,
    slide_paths: ["outputs/.pptx-preview/deck/slide-1.jpg"],
    cached: false,
  });
  await refreshInventory([{ path, revision: "100:1000", size: 1000 }]);
  expect(store().sessions.get(sessionId)).toMatchObject({
    outputPanelOpen: false,
    panelTabs: [],
  });
  render(<BuildOutputPanel isOpen />);
  act(() => store().openFilePreview(sessionId, path, "deck.pptx"));
  const originalUrl = (await screen.findByRole("img")).getAttribute("src");
  expect(fetchPptxPreview).toHaveBeenCalledTimes(1);
  expect(fetchPptxPreview).toHaveBeenLastCalledWith(sessionId, path);

  await refreshInventory([{ path, revision: "200:1000", size: 1000 }]);
  await waitFor(() => expect(fetchPptxPreview).toHaveBeenCalledTimes(2));
  const updatedImage = await screen.findByRole("img");
  const updatedUrl = updatedImage.getAttribute("src");
  expect(updatedUrl).not.toBe(originalUrl);
  expect(updatedImage).toHaveAttribute("alt", "Slide 1 of 1");

  act(() => store().closePanelTab(sessionId, `file:${path}`));
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  act(() => store().openFilePreview(sessionId, path, "deck.pptx"));
  expect(await screen.findByRole("img")).not.toHaveAttribute("src", updatedUrl);
  expect(fetchPptxPreview).toHaveBeenCalledTimes(3);
});

function isReportFrame(title: string, element: Element | null): boolean {
  return title === "report.pdf" && element?.tagName === "IFRAME";
}

it("refreshes an open PDF through inventory updates and reuses unchanged bytes", async () => {
  const path = "outputs/report.pdf";
  const fetch = jest
    .spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response("original PDF bytes"))
    .mockImplementation(async () => new Response("updated PDF bytes"));
  await refreshInventory([{ path, revision: "100:1000", size: 1000 }]);
  expect(store().sessions.get(sessionId)).toMatchObject({
    outputPanelOpen: false,
    panelTabs: [],
  });
  render(<BuildOutputPanel isOpen />);
  act(() => store().openFilePreview(sessionId, path, "report.pdf"));
  const originalUrl = (await screen.findByTitle(isReportFrame)).getAttribute(
    "src"
  );
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenLastCalledWith(
    `/api/build/sessions/${sessionId}/artifacts/outputs/report.pdf`,
    { cache: "no-store" }
  );

  await refreshInventory([{ path, revision: "200:1000", size: 1000 }]);
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(await screen.findByTitle(isReportFrame)).not.toHaveAttribute(
    "src",
    originalUrl
  );
  expect(URL.revokeObjectURL).toHaveBeenCalledWith(originalUrl);
  const updatedBlob = jest.mocked(URL.createObjectURL).mock.calls.at(-1)?.[0];
  act(() => store().closePanelTab(sessionId, `file:${path}`));
  expect(screen.queryByTitle(isReportFrame)).not.toBeInTheDocument();
  act(() => store().openFilePreview(sessionId, path, "report.pdf"));
  await screen.findByTitle(isReportFrame);
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(jest.mocked(URL.createObjectURL).mock.calls.at(-1)?.[0]).not.toBe(
    updatedBlob
  );
});
