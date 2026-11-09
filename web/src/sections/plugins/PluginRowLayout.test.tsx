import { render, screen } from "@tests/setup/test-utils";
import { SvgPlug } from "@opal/icons";
import PluginRowLayout from "@/sections/plugins/PluginRowLayout";

describe("PluginRowLayout", () => {
  test("omits the description line when a plugin has no description", () => {
    const { container } = render(
      <PluginRowLayout
        icon={SvgPlug}
        title="Metadata API"
        description=""
        action={null}
      />
    );
    expect(screen.getByText("Metadata API")).toBeInTheDocument();
    expect(container.querySelectorAll(".truncate")).toHaveLength(1);
  });

  test("shows the description under the title", () => {
    render(
      <PluginRowLayout
        icon={SvgPlug}
        title="Wiki MCP"
        description="Internal wiki search"
        action={null}
      />
    );
    expect(screen.getByText("Internal wiki search")).toBeInTheDocument();
  });
});
