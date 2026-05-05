/**
 * Icon Component Tests
 *
 * Tests logo icons to ensure they render correctly with proper accessibility
 * and support various display sizes.
 */
import { SvgBifrost, SvgConfluence, SvgGitbook, SvgGithub } from "@opal/logos";
import { render } from "@tests/setup/test-utils";
import { GoogleStorageIcon } from "./icons";

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

  test("renders opal SVG logo at correct size", () => {
    const { container } = render(<SvgConfluence size={24} />);
    const svg = container.querySelector("svg");

    expect(svg).toHaveAttribute("width", "24");
    expect(svg).toHaveAttribute("height", "24");
  });

  test("applies size adjustments", () => {
    // GoogleStorageIcon has a +4px size adjustment
    const { container } = render(<GoogleStorageIcon size={16} />);
    const image = container.querySelector("img");

    // Base 16 + adjustment 4 = 20
    expect(image).toHaveStyle({ width: "20px", height: "20px" });
  });

  test("renders opal SVG logo as single element", () => {
    const { container } = render(<SvgGitbook size={32} />);
    const svg = container.querySelector("svg");

    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("width", "32");
    expect(svg).toHaveAttribute("height", "32");
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
