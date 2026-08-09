import { render, screen } from "@testing-library/react";

import { FilePreviewContent } from "@/app/craft/components/output-panel/FilePreviewContent";
import { fetchFileContent } from "@/app/craft/services/apiServices";

jest.mock("@/app/craft/services/apiServices", () => ({
  ...jest.requireActual("@/app/craft/services/apiServices"),
  fetchFileContent: jest.fn(),
}));

jest.mock("@/app/craft/components/output-panel/PptxPreview", () => ({
  __esModule: true,
  default: ({
    sessionId,
    filePath,
  }: {
    sessionId: string;
    filePath: string;
  }) => (
    <div>{`PowerPoint preview for ${filePath} in session ${sessionId}`}</div>
  ),
}));

describe("FilePreviewContent", () => {
  beforeEach(() => {
    jest.mocked(fetchFileContent).mockReset();
  });

  it("routes a legacy .ppt file directly to the presentation renderer", () => {
    const filePath = "outputs/quarterly review.ppt";

    render(<FilePreviewContent sessionId="session-1" filePath={filePath} />);

    expect(
      screen.getByText(
        `PowerPoint preview for ${filePath} in session session-1`
      )
    ).toBeInTheDocument();
    expect(fetchFileContent).not.toHaveBeenCalled();
  });

  it("does not mistake a compound extension for a presentation", async () => {
    jest.mocked(fetchFileContent).mockResolvedValue({
      content: "plain text",
      mimeType: "text/plain",
      isImage: false,
    });

    render(
      <FilePreviewContent
        sessionId="session-1"
        filePath="outputs/notes.ppt.txt"
      />
    );

    expect(await screen.findByText("plain text")).toBeInTheDocument();
    expect(fetchFileContent).toHaveBeenCalledWith(
      "session-1",
      "outputs/notes.ppt.txt"
    );
  });
});
