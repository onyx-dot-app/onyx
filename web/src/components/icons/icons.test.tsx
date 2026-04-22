/**
 * Icon Component Tests
 *
 * Tests logo icons to ensure they render correctly with proper accessibility
 * and support various display sizes.
 */
import { SvgBifrost, SvgGithub } from "@opal/logos";
import { render } from "@tests/setup/test-utils";
import { GitbookIcon, ConfluenceIcon } from "./icons";

describe("Logo Icons", () => {
  test("renders as an SVG element", () => {
    const { container } = render(<SvgGithub />);
    const svg = container.querySelector("svg");

    expect(svg).toBeInTheDocument();
  });

  test("applies custom size", () => {
    const { container } = render(<SvgGithub size={48} />);
    const svg = container.querySelector("svg");

    expect(svg).toHaveAttribute("width", "48");
    expect(svg).toHaveAttribute("height", "48");
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
      render(<SvgGithub size={100} className="custom-class" />);
    }).not.toThrow();
  });

  test("renders the Bifrost icon with theme-aware colors", () => {
    const { container } = render(
      <SvgBifrost size={32} className="custom text-red-500 dark:text-black" />
    );
    const icon = container.querySelector("svg");

    expect(icon).toBeInTheDocument();
    expect(icon).toHaveClass(
      "custom",
      "text-red-500",
      "dark:text-black",
      "!text-[#33C19E]"
    );
  });
});
