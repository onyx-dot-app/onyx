import { act, render, screen, waitFor, within } from "@tests/setup/test-utils";
import type { PublishedFile } from "@/app/app/services/streamingModels";
import {
  PublishedFilePreview,
  PublishedFilesGrid,
} from "@/sections/chat/PublishedFileViews";
import { fetchChatFile } from "@/lib/chat/svc";

jest.mock("@/lib/chat/svc", () => ({
  ...jest.requireActual("@/lib/chat/svc"),
  fetchChatFile: jest.fn(),
}));

const HTML = "<h1>Quarterly report</h1>";

function htmlResponse(): Response {
  const headers: Record<string, string> = {
    "Content-Type": "text/html",
    "Content-Disposition": 'attachment; filename="report.html"',
  };
  const response: Pick<Response, "headers" | "blob" | "body"> = {
    headers: { get: (name: string) => headers[name] ?? null } as Headers,
    blob: async () =>
      ({ text: async () => HTML, type: "text/html" }) as unknown as Blob,
    body: null,
  };
  return response as unknown as Response;
}

const createObjectURL = jest.fn(() => "blob:report");

beforeAll(() => {
  Object.defineProperty(window.URL, "createObjectURL", {
    configurable: true,
    value: createObjectURL,
  });
  Object.defineProperty(window.URL, "revokeObjectURL", {
    configurable: true,
    value: () => undefined,
  });
});

function file(
  fileId: string,
  name: string,
  title: string | null
): PublishedFile {
  return {
    file_id: fileId,
    name,
    title,
    path: `/home/onyx/${name}`,
    display_path: name,
    size: 2048,
    mime_type: "text/html",
  };
}

test("the Files list shows a tile for each file, with its title, else its name", () => {
  const onOpen = jest.fn();
  const files = [
    file("file-2", "report.html", "Q3 report"),
    file("file-3", "chart.png", null),
    { ...file("file-4", "notes.md", null), display_path: "drafts/notes.md" },
    { ...file("file-5", "notes.md", null), display_path: "final/notes.md" },
  ];
  render(
    <PublishedFilesGrid files={files} unseenFileIds={[]} onOpen={onOpen} />
  );

  const tiles = screen.getAllByRole("button", { name: /^Open / });
  expect(tiles.map((tile) => tile.textContent)).toEqual([
    "Q3 report",
    "chart.png",
    "drafts/notes.md",
    "final/notes.md",
  ]);
  // Names show in their own direction
  expect(within(tiles[0]!).getByText("Q3 report")).toHaveAttribute(
    "dir",
    "auto"
  );
  // An image shows a lazy thumbnail, and its icon when the image fails.
  const thumbnail = document.querySelector("img");
  expect(thumbnail).toHaveAttribute("src", "/api/chat/file/file-3");
  expect(thumbnail).toHaveAttribute("loading", "lazy");
  act(() => {
    thumbnail?.dispatchEvent(new Event("error"));
  });
  expect(document.querySelector("img")).toBeNull();

  act(() => {
    screen.getByRole("button", { name: "Open Q3 report" }).click();
  });
  expect(onOpen).toHaveBeenCalledWith(files[0]);
});

test("a file's preview shows HTML as source, with a download", async () => {
  jest.mocked(fetchChatFile).mockResolvedValue(htmlResponse());
  const view = render(
    <PublishedFilePreview file={file("file-2", "report.html", "Q3 report")} />
  );

  const preview = screen.getByRole("region", { name: "Preview of Q3 report" });
  // HTML shows as source, never as a rendered page.
  await waitFor(() => expect(preview).toHaveTextContent(HTML));
  expect(view.container.querySelector("iframe")).toBeNull();
  expect(fetchChatFile).toHaveBeenCalledWith("file-2");
  expect(
    within(preview).getByRole("link", { name: "Download" })
  ).toHaveAttribute("download", "report.html");
});

test("a preview that closes while its file loads makes no object URL", async () => {
  let respond: (response: Response) => void = () => undefined;
  jest.mocked(fetchChatFile).mockReturnValue(
    new Promise((resolve) => {
      respond = resolve;
    })
  );
  createObjectURL.mockClear();
  const view = render(
    <PublishedFilePreview file={file("file-2", "report.html", "Q3 report")} />
  );
  view.unmount();

  await act(async () => respond(htmlResponse()));
  expect(createObjectURL).not.toHaveBeenCalled();
});
