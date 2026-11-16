import { render, screen } from "@tests/setup/test-utils";
import { Badge, type BadgeSize } from "@opal/components";

describe("Badge", () => {
  it.each([4, 5, 6] as BadgeSize[])("renders size %s on the root", (size) => {
    render(
      <Badge title="Indexing" color="info" textColor="text-04" size={size} />
    );

    const root = screen.getByText("Indexing").closest(".opal-badge");
    expect(root).toHaveAttribute("data-size", String(size));
  });
});
