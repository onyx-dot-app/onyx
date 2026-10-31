/**
 * Icon Component Tests
 *
 * Tests logo icons to ensure they render correctly with proper accessibility
 * and support various display sizes.
 */
import { SvgBifrost, SvgConfluence, SvgGitBook, SvgGitHub } from "@opal/logos";
import { render } from "@tests/setup/test-utils";

describe("Logo Icons", () => {
  test("renders as an SVG element", () => {
    const { container } = render(<SvgGitHub />);
    const svg = container.querySelector("svg");

    expect(svg).toBeInTheDocument();
  });

  test("applies custom size", () => {
    const { container } = render(<SvgGitHub size={48} />);
    const svg = container.querySelector("svg");

    expect(svg).toHaveAttribute("width", "48");
    expect(svg).toHaveAttribute("height", "48");
  });

  test("renders opal SVG logo at correct size", () => {
    const { container } = render(<SvgConfluence size={24} />);
    const svg = container.querySelector("svg");

    expect(svg).toHaveAttribute("width", "24");
    expect(svg).toHaveAttribute("height", "24");
  });

  test("renders opal SVG logo as single element", () => {
    const { container } = render(<SvgGitBook size={32} />);
    const svg = container.querySelector("svg");

    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("width", "32");
    expect(svg).toHaveAttribute("height", "32");
  });

  test("accepts className and size props", () => {
    expect(() => {
      render(<SvgGitHub size={100} className="custom-class" />);
    }).not.toThrow();
  });

  test("renders the Bifrost icon with theme-aware colors", () => {
    const { container } = render(
      <SvgBifrost size={32} className="custom dark:text-black" />
    );
    const icon = container.querySelector("svg");

    expect(icon).toBeInTheDocument();
    expect(icon).toHaveClass("custom", "dark:text-black", "text-[#33C19E]!");
  });
});
