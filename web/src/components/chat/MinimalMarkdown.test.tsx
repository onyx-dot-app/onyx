import { render, screen } from "@testing-library/react";
import MinimalMarkdown from "./MinimalMarkdown";

describe("MinimalMarkdown link handling", () => {
  it("converts bare email markdown links to mailto links", () => {
    render(
      <MinimalMarkdown content="[support@anthropic.com](support@anthropic.com)" />
    );

    const link = screen.getByText("support@anthropic.com").closest("a");
    expect(link).toHaveAttribute("href", "mailto:support@anthropic.com");
  });

  it("preserves explicit mailto links", () => {
    render(
      <MinimalMarkdown content="[support@anthropic.com](mailto:support@anthropic.com)" />
    );

    const link = screen.getByText("support@anthropic.com").closest("a");
    expect(link).toHaveAttribute("href", "mailto:support@anthropic.com");
  });

  it("does not restore hrefs removed by url sanitization", () => {
    render(<MinimalMarkdown content="[click](javascript:alert(1))" />);

    const link = screen.getByText("click").closest("a");
    expect(link).not.toHaveAttribute("href");
  });
});
