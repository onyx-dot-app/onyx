import { act, render, screen, within } from "@tests/setup/test-utils";
import {
  PublishedFileCards,
  PublishedFilesPanelContext,
} from "@/sections/chat/PublishedFileCards";
import { fetchChatFile } from "@/lib/chat/svc";

jest.mock("@/lib/chat/svc", () => ({
  ...jest.requireActual("@/lib/chat/svc"),
  fetchChatFile: jest.fn(),
}));

test("a card shows the title, type and size, and downloads the file", () => {
  render(
    <PublishedFileCards
      files={[
        {
          file_id: "file-1",
          name: "report.csv",
          title: "Q3 report",
          path: "/home/onyx/report.csv",
          display_path: "/home/onyx/report.csv",
          size: 2048,
          mime_type: "text/csv",
          artifact_id: "artifact-report",
          version: 1,
          thumbnail_file_id: null,
        },
        {
          file_id: "file-2",
          name: "report.csv",
          title: null,
          path: "/home/onyx/report.csv",
          display_path: "/home/onyx/report.csv",
          size: 512,
          mime_type: "text/csv",
          artifact_id: "artifact-report",
          version: 2,
          thumbnail_file_id: null,
        },
      ]}
    />
  );

  const cards = screen.getAllByRole("button", { name: "Preview report.csv" });
  expect(cards).toHaveLength(2);
  expect(within(cards[0]!).getByText("Q3 report")).toBeInTheDocument();
  expect(within(cards[0]!).getByText(/^CSV · 2/)).toBeInTheDocument();
  expect(within(cards[1]!).getByText("report.csv")).toBeInTheDocument();
  expect(within(cards[1]!).getByText(/^CSV · 512/)).toBeInTheDocument();

  const downloads = screen.getAllByRole("link", { name: "Download" });
  expect(downloads[0]).toHaveAttribute("href", "/api/chat/file/file-1");
  expect(downloads[0]).toHaveAttribute("download", "report.csv");
  expect(downloads[1]).toHaveAttribute("href", "/api/chat/file/file-2");
  for (const download of downloads) {
    expect(within(download).queryByRole("button")).toBeNull();
  }
});

test("files that show one name also show their path in the chat's folder", () => {
  // The backend sends the path to show: relative to the chat's working
  // directory, or the whole path outside it. The card shows it as sent and
  // knows nothing of the VM's layout.
  const csv = (
    fileId: string,
    displayPath: string,
    title: string | null = null
  ) => ({
    file_id: fileId,
    name: displayPath.split("/").pop() ?? displayPath,
    title,
    path: displayPath.startsWith("/")
      ? displayPath
      : `/vm/sessions/chat/${displayPath}`,
    display_path: displayPath,
    size: 512,
    mime_type: "text/csv",
    artifact_id: null,
    version: null,
    thumbnail_file_id: null,
  });
  render(
    <PublishedFileCards
      files={[
        csv("drafts", "drafts/summary.csv"),
        csv("final", "final/summary.csv"),
        csv("outside", "/tmp/onyx/summary.csv"),
        csv("unique", "drafts/report.csv"),
        // Only a title shares a name with nothing: it shows no path.
        csv("titled", "other/summary.csv", "Summary"),
      ]}
    />
  );

  const cards = screen.getAllByRole("button", { name: /^Preview / });
  ["drafts/summary.csv", "final/summary.csv", "/tmp/onyx/summary.csv"].forEach(
    (path, index) => {
      // Under the title, before the type and size
      const shownPath = within(cards[index]!).getByText(path);
      expect(shownPath.parentElement?.textContent).toMatch(
        new RegExp(`^${path} · CSV · 512`)
      );
    }
  );
  const text = cards.map((card) => card.textContent);
  // Not the whole VM path inside the working directory
  expect(text.slice(0, 2).join()).not.toContain("/vm/");
  expect(text[3]).not.toContain("drafts/");
  expect(text[4]).not.toContain("other/");
});

test("a path or name that the model chose cannot reorder the type and size", () => {
  // U+202E reverses the text after it, up to the end of its element
  const path = "drafts/\u202Eodaerp.csv";
  const file = {
    file_id: "override",
    name: "report.\u202Evsc",
    title: "\u202EReport",
    path: `/vm/sessions/chat/${path}`,
    display_path: path,
    size: 512,
    mime_type: "text/csv",
    artifact_id: null,
    version: null,
    thumbnail_file_id: null,
  };
  render(
    <PublishedFileCards
      files={[file, { ...file, file_id: "copy", display_path: "copy.csv" }]}
    />
  );

  const card = screen.getAllByRole("button", { name: /^Preview / })[0]!;
  expect(within(card).getByText("Report")).toBeInTheDocument();
  // The path shows in its own direction, before the type and size, without
  // controls
  const shownPath = within(card).getByText("drafts/odaerp.csv");
  expect(shownPath).toHaveAttribute("dir", "ltr");
  expect(shownPath.parentElement?.textContent).toMatch(
    /^drafts\/odaerp\.csv · VSC · 512/
  );
  expect(card.textContent).not.toMatch(/[\u202A-\u202E\u2066-\u2069]/);
});

test("a click opens the file in the Files panel, not in a modal", () => {
  const open = jest.fn();
  const file = {
    file_id: "file-html",
    name: "report.html",
    title: null,
    path: "/home/onyx/report.html",
    display_path: "report.html",
    size: 10,
    mime_type: "text/html",
    artifact_id: null,
    version: null,
    thumbnail_file_id: null,
  };
  render(
    <PublishedFilesPanelContext.Provider
      value={{ openFile: open, showFiles: jest.fn() }}
    >
      <PublishedFileCards files={[file]} />
    </PublishedFilesPanelContext.Provider>
  );

  act(() => {
    screen.getByRole("button", { name: "Preview report.html" }).click();
  });

  expect(open).toHaveBeenCalledWith(file);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(fetchChatFile).not.toHaveBeenCalled();
});

test("without a Files panel, every file shows as a card", () => {
  const files = Array.from({ length: 7 }, (_, index) => ({
    file_id: `file-${index}`,
    name: `report-${index}.md`,
    title: null,
    path: `/home/onyx/report-${index}.md`,
    display_path: `report-${index}.md`,
    size: 8,
    mime_type: "text/markdown",
    artifact_id: null,
    version: null,
    thumbnail_file_id: null,
  }));
  render(<PublishedFileCards files={files} />);

  expect(screen.getAllByRole("button", { name: /^Preview / })).toHaveLength(7);
  expect(screen.queryByRole("button", { name: /^View all/ })).toBeNull();
});

test("without a Files panel, a click previews the file in a modal", async () => {
  jest.mocked(fetchChatFile).mockResolvedValue(
    new Response("# Report", {
      headers: { "Content-Type": "text/markdown" },
    })
  );
  render(
    <PublishedFileCards
      files={[
        {
          file_id: "file-md",
          name: "report.md",
          title: null,
          path: "/home/onyx/report.md",
          display_path: "report.md",
          size: 8,
          mime_type: "text/markdown",
          artifact_id: null,
          version: null,
          thumbnail_file_id: null,
        },
      ]}
    />
  );

  await act(async () => {
    screen.getByRole("button", { name: "Preview report.md" }).click();
  });

  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(fetchChatFile).toHaveBeenCalledWith(
    "file-md",
    false,
    expect.any(AbortSignal)
  );
});

test("a card and its preview show the name without its bidi controls", async () => {
  jest.mocked(fetchChatFile).mockResolvedValue(
    new Response("<h1>Photo</h1>", {
      headers: {
        "Content-Type": "text/html",
        "Content-Disposition":
          "attachment; filename*=UTF-8''photo.%E2%80%AEgpj",
      },
    })
  );
  render(
    <PublishedFileCards
      files={[
        {
          file_id: "file-1",
          name: "photo.\u202Egpj",
          title: null,
          path: "/home/onyx/photo.gpj",
          display_path: "photo.gpj",
          size: 512,
          mime_type: "image/jpeg",
          artifact_id: null,
          version: null,
          thumbnail_file_id: null,
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
