import { act, render, screen, within } from "@tests/setup/test-utils";
import { PublishedFileCards } from "@/sections/chat/PublishedFileCards";
import { fetchChatFile } from "@/lib/chat/svc";

jest.mock("@/lib/chat/svc", () => ({
  ...jest.requireActual("@/lib/chat/svc"),
  fetchChatFile: jest.fn(),
}));

const HTML = "<h1>Quarterly report</h1>";

function htmlResponse(
  contentDisposition = 'attachment; filename="report.html"'
): Response {
  const headers: Record<string, string> = {
    "Content-Type": "text/html",
    "Content-Disposition": contentDisposition,
  };
  const response: Pick<Response, "headers" | "blob" | "body"> = {
    headers: { get: (name: string) => headers[name] ?? null } as Headers,
    blob: async () =>
      ({ text: async () => HTML, type: "text/html" }) as unknown as Blob,
    body: null,
  };
  return response as unknown as Response;
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

test("a card shows the title, type and size, and downloads the file", () => {
  render(
    <PublishedFileCards
      files={[
        {
          file_id: "file-1",
          name: "report.csv",
          title: "Q3 report",
          path: "/home/onyx/report.csv",
          size: 2048,
          mime_type: "text/csv",
          version: 1,
        },
        {
          file_id: "file-2",
          name: "report.csv",
          title: null,
          path: "/home/onyx/report.csv",
          size: 512,
          mime_type: "text/csv",
          version: 2,
        },
      ]}
    />
  );

  const cards = screen.getAllByRole("button", { name: "Preview report.csv" });
  expect(cards).toHaveLength(2);
  expect(within(cards[0]!).getByText("Q3 report")).toBeInTheDocument();
  expect(within(cards[0]!).getByText(/^CSV · 2/)).toBeInTheDocument();
  expect(within(cards[1]!).getByText("report.csv")).toBeInTheDocument();
  expect(
    within(cards[1]!).getByText(/^Updated version · CSV · 512/)
  ).toBeInTheDocument();

  const downloads = screen.getAllByRole("link", { name: "Download" });
  expect(downloads[0]).toHaveAttribute("href", "/api/chat/file/file-1");
  expect(downloads[0]).toHaveAttribute("download", "report.csv");
  expect(downloads[1]).toHaveAttribute("href", "/api/chat/file/file-2");
});

test("an HTML file previews as source, not as a rendered page", async () => {
  jest.mocked(fetchChatFile).mockResolvedValue(htmlResponse());
  const view = render(
    <PublishedFileCards
      files={[
        {
          file_id: "file-html",
          name: "report.html",
          title: null,
          path: "/home/onyx/report.html",
          size: HTML.length,
          mime_type: "text/html",
          version: 1,
        },
      ]}
    />
  );

  await act(async () => {
    screen.getByRole("button", { name: "Preview report.html" }).click();
  });

  const dialog = await screen.findByRole("dialog");
  expect(fetchChatFile).toHaveBeenCalledWith("file-html");
  // The code view shows the markup itself.
  expect(await within(dialog).findByText(/Quarterly report/)).toBeVisible();
  expect(dialog).toHaveTextContent(HTML);
  expect(view.container.ownerDocument.querySelector("iframe")).toBeNull();
});

test("a card and its preview show the name without its bidi controls", async () => {
  jest
    .mocked(fetchChatFile)
    .mockResolvedValue(
      htmlResponse("attachment; filename*=UTF-8''photo.%E2%80%AEgpj")
    );
  render(
    <PublishedFileCards
      files={[
        {
          file_id: "file-1",
          name: "photo.\u202Egpj",
          title: null,
          path: "/home/onyx/photo.gpj",
          size: 512,
          mime_type: "image/jpeg",
          version: 1,
        },
      ]}
    />
  );

  expect(screen.getByText(/^GPJ · 512/)).toBeInTheDocument();
  await act(async () => {
    screen.getByRole("button", { name: "Preview photo.gpj" }).click();
  });
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent("photo.gpj");
  expect(dialog.textContent).not.toContain("\u202E");
});
