import { fireEvent, render, screen } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { MarkdownImage } from "@/lib/timeline/chat/message/messageComponents/markdownUtils";

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
  });

  test("shows a fallback when the image fails to load", () => {
    render(<MarkdownImage src="https://example.com/missing.png" alt="Gone" />);

    fireEvent.error(screen.getByAltText("Gone"));

    expect(screen.getByText("Image unavailable")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
