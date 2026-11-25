import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import {
  MarkdownImage,
  MarkdownLinkContent,
} from "@/lib/timeline/chat/message/messageComponents/markdownUtils";

jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }: { children?: string }) => children ?? null,
}));

describe("MarkdownImage", () => {
  test("loads lazily and opens the full image on click", async () => {
    render(<MarkdownImage src="https://example.com/chart.png" alt="Chart" />);

    expect(screen.getByAltText("Chart")).toHaveAttribute("loading", "lazy");

    await userEvent.click(screen.getByRole("button", { name: "Chart" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Chart" })).toHaveFocus()
    );
  });

  test("keeps the link as the only control for a linked image", () => {
    render(
      <a href="https://example.com/report">
        <MarkdownLinkContent>
          <MarkdownImage src="https://example.com/chart.png" alt="Chart" />
        </MarkdownLinkContent>
      </a>
    );
    expect(screen.getByRole("link", { name: "Chart" })).toHaveAttribute(
      "href",
      "https://example.com/report"
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  test("shows a fallback when the image fails and loads a replacement URL", () => {
    const { rerender } = render(
      <MarkdownImage src="https://example.com/missing.png" alt="Gone" />
    );

    fireEvent.error(screen.getByAltText("Gone"));

    expect(screen.getByText("Gone · Image unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    rerender(<MarkdownImage src="https://example.com/chart.png" alt="Chart" />);
    expect(screen.getByAltText("Chart")).toBeInTheDocument();
  });
});
