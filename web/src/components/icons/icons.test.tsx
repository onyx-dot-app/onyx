/**
 * Icon Component Tests
 *
 * Tests logo icons to ensure they render correctly with proper accessibility
 * and support various display sizes.
 */
import React from "react";
import { render } from "@tests/setup/test-utils";
import { GithubIcon, GitbookIcon, ConfluenceIcon } from "./icons";

describe("Logo Icons", () => {
  test("renders with alt text", () => {
    const { container } = render(<GithubIcon />);
    const image = container.querySelector("img");

    expect(image).toBeInTheDocument();
    expect(image).toHaveAttribute("alt");
  });

  test("applies custom size", () => {
    const { container } = render(<GithubIcon size={48} />);
    const image = container.querySelector("img");

    expect(image).toHaveStyle({ width: "48px", height: "48px" });
  });

  test("applies size adjustments", () => {
    // ConfluenceIcon has a +4px size adjustment
    const { container } = render(<ConfluenceIcon size={16} />);
    const image = container.querySelector("img");

    // Base 16 + adjustment 4 = 20
    expect(image).toHaveStyle({ width: "20px", height: "20px" });
  });

  // This test is for icons that have light and dark variants (e.g. GitbookIcon)
  // Both exist in the DOM, one is hidden via CSS.
  test("renders both light and dark variants", () => {
    const { container } = render(<GitbookIcon />);
    const images = container.querySelectorAll("img");

    // Should render both light and dark variants in the DOM (one hidden via CSS)
    expect(images).toHaveLength(2);
    images.forEach((img) => {
      expect(img).toHaveAttribute("alt");
    });
  });

  test("accepts className and size props", () => {
    expect(() => {
      render(<GithubIcon size={100} className="custom-class" />);
    }).not.toThrow();
  });
});
