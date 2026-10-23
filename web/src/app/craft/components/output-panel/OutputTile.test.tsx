import { fireEvent, render, screen, setupUser } from "@tests/setup/test-utils";
import { OutputTile } from "@/app/craft/components/output-panel/OutputTile";
import { useFilePreview } from "@/lib/build/hooks";
import {
  downloadArtifactFile,
  fetchOutputThumbnail,
} from "@/app/craft/services/apiServices";

jest.mock("motion/react", () => ({ useInView: () => true }));
jest.mock("@/lib/build/hooks", () => ({ useFilePreview: jest.fn() }));
jest.mock("@/app/craft/services/apiServices", () => ({
  downloadArtifactFile: jest.fn(),
  fetchFileContent: jest.fn(),
  fetchOutputThumbnail: jest.fn(),
}));
const preview = jest.mocked(useFilePreview);
const file = { path: "outputs/summary.md", revision: "1", size: 10 };
const props = {
  sessionId: "session",
  file,
  isActive: true,
  onFileOpen: jest.fn(),
};

beforeEach(() => {
  jest.clearAllMocks();
  preview.mockReturnValue({
    data: undefined,
    error: undefined,
    isLoading: false,
  });
});

test("downloads without opening the output card", async () => {
  render(<OutputTile {...props} />);
  await setupUser().click(screen.getByRole("button", { name: "Download" }));
  expect(downloadArtifactFile).toHaveBeenCalledWith("session", file.path);
  expect(props.onFileOpen).not.toHaveBeenCalled();
});

test("shows plain text without rendering sandbox HTML", () => {
  preview.mockReturnValue({
    data: { content: "<script>alert(1)</script>", mimeType: "text/html" },
    error: undefined,
    isLoading: false,
  });
  const { container } = render(
    <OutputTile {...props} file={{ ...file, path: "outputs/example.html" }} />
  );
  expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
  expect(container.querySelector("script")).toBeNull();
});

test("renders markdown as a clipped document instead of raw syntax", () => {
  preview.mockReturnValue({
    data: {
      content: "# Results\n\n- First finding",
      mimeType: "text/markdown",
    },
    error: undefined,
    isLoading: false,
  });
  const { container } = render(<OutputTile {...props} />);
  expect(
    screen.getByRole("heading", { hidden: true, name: "Results" })
  ).toBeInTheDocument();
  expect(container.querySelector("li")).toHaveTextContent("First finding");
  expect(container.querySelector("[inert]")).toBeInTheDocument();
});

test("renders an image thumbnail on a contrasting background", () => {
  preview.mockReturnValue({
    data: {
      content: "data:image/png;base64,cG5n",
      mimeType: "image/png",
      isImage: true,
    },
    error: undefined,
    isLoading: false,
  });
  const { container } = render(
    <OutputTile {...props} file={{ ...file, path: "outputs/logo.png" }} />
  );
  const image = container.querySelector("img");
  expect(image).toHaveAttribute("src", "data:image/png;base64,cG5n");
  expect(image?.parentElement).toHaveClass("bg-background-neutral-03");
  expect(image).not.toHaveClass("opacity-0");
  if (!image) throw new Error("Missing image thumbnail");
  fireEvent.error(image);
  expect(container.querySelector("img")).toBeNull();
});

test("requests a lightweight first-page thumbnail for a PDF", async () => {
  jest
    .mocked(fetchOutputThumbnail)
    .mockResolvedValue("data:image/jpeg;base64,cGRm");
  render(
    <OutputTile {...props} file={{ ...file, path: "outputs/report.pdf" }} />
  );
  const loader = preview.mock.calls.at(-1)?.[1];
  expect(loader).toBeDefined();
  await expect(loader?.()).resolves.toEqual({
    content: "data:image/jpeg;base64,cGRm",
    mimeType: "image/jpeg",
    isImage: true,
  });
  expect(fetchOutputThumbnail).toHaveBeenCalledWith(
    "session",
    "outputs/report.pdf"
  );
});

test("does not fetch previews while inactive or for oversized files", () => {
  const { rerender } = render(<OutputTile {...props} isActive={false} />);
  expect(preview).toHaveBeenLastCalledWith(
    expect.any(String),
    expect.any(Function),
    expect.objectContaining({ isActive: false })
  );
  rerender(<OutputTile {...props} file={{ ...file, size: 1024 * 1024 }} />);
  expect(preview).toHaveBeenLastCalledWith(
    expect.any(String),
    expect.any(Function),
    expect.objectContaining({ isActive: false })
  );
});

test("shows filenames in folders and relative paths only when requested", () => {
  const nestedFile = { ...file, path: "outputs/reports/summary.md" };
  const { rerender } = render(<OutputTile {...props} file={nestedFile} />);
  expect(screen.getByText("summary.md")).toBeInTheDocument();
  expect(screen.queryByText("reports/summary.md")).not.toBeInTheDocument();
  rerender(<OutputTile {...props} file={nestedFile} showPath />);
  expect(screen.getByText("reports/summary.md")).toBeInTheDocument();
});
