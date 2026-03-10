import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import MinimalMarkdown from "./MinimalMarkdown";

describe("MinimalMarkdown", () => {
  describe("Link handling", () => {
    test("converts bare email markdown links to mailto links", () => {
      render(
        <MinimalMarkdown content="[support@anthropic.com](support@anthropic.com)" />
      );

      const link = screen.getByText("support@anthropic.com").closest("a");
      expect(link).toHaveAttribute("href", "mailto:support@anthropic.com");
    });

    test("preserves explicit mailto links", () => {
      render(
        <MinimalMarkdown content="[support@anthropic.com](mailto:support@anthropic.com)" />
      );

      const link = screen.getByText("support@anthropic.com").closest("a");
      expect(link).toHaveAttribute("href", "mailto:support@anthropic.com");
    });

    test("does not restore hrefs removed by url sanitization", () => {
      render(<MinimalMarkdown content="[click](javascript:alert(1))" />);

      const link = screen.getByText("click").closest("a");
      expect(link).not.toHaveAttribute("href");
    });
  });
});
