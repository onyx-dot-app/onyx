import { render, screen } from "@testing-library/react";

import { FilePreviewContent } from "@/app/craft/components/output-panel/FilePreviewContent";

jest.mock("@/app/craft/components/output-panel/PptxPreview", () => ({
  __esModule: true,
  default: ({ filePath }: { filePath: string }) => (
    <div>{`PowerPoint preview: ${filePath}`}</div>
  ),
}));

describe("FilePreviewContent", () => {
  test.each(["outputs/presentation.ppt", "outputs/presentation.pptx"])(
    "routes %s to the PowerPoint preview",
    (filePath) => {
      render(<FilePreviewContent sessionId="session-1" filePath={filePath} />);

      expect(
        screen.getByText(`PowerPoint preview: ${filePath}`)
      ).toBeInTheDocument();
    }
  );
});
