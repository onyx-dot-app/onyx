import { render } from "@tests/setup/test-utils";
import { SvgGmail, SvgGoogleDrive } from "@opal/logos";

describe.each([
  ["SvgGmail", SvgGmail],
  ["SvgGoogleDrive", SvgGoogleDrive],
])("%s", (_name, Logo) => {
  it("renders the 16px gradient mark", () => {
    const { container } = render(<Logo size={16} />);

    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("viewBox", "0 0 16 16");
    expect(svg).toHaveAttribute("width", "16");
    expect(svg?.querySelector("linearGradient")).not.toBeNull();
  });

  it("gives each instance its own gradient ids", () => {
    const { container } = render(
      <>
        <Logo size={16} />
        <Logo size={12} />
      </>
    );

    const ids: string[] = Array.from(
      container.querySelectorAll("linearGradient")
    ).map((gradient) => gradient.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const path of Array.from(container.querySelectorAll("path"))) {
      const fill = path.getAttribute("fill") ?? "";
      if (!fill.startsWith("url(")) continue;
      expect(ids).toContain(fill.slice("url(#".length, -1));
    }
  });
});
