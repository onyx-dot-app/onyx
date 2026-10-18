import { render, screen } from "@tests/setup/test-utils";
import Page from "@/app/craft/v1/plugins/page";

jest.mock("@/views/PluginsPage", () => ({
  __esModule: true,
  default: ({ surface }: { surface: string }) => (
    <div data-testid="directory" data-surface={surface} />
  ),
}));

test("Craft Plugins uses the shared member directory with Craft capabilities", () => {
  render(<Page />);
  expect(screen.getByTestId("directory")).toHaveAttribute(
    "data-surface",
    "craft"
  );
});
