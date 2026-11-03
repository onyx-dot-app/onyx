import { render, screen, setupUser } from "@tests/setup/test-utils";
import { Badge, type BadgeSize } from "@opal/components";

describe("Badge", () => {
  it.each([4, 5, 6] as BadgeSize[])("renders size %s on the root", (size) => {
    render(
      <Badge title="Indexing" color="info" textColor="text-04" size={size} />
    );

    const root = screen.getByText("Indexing").closest(".opal-badge");
    expect(root).toHaveAttribute("data-size", String(size));
  });

  it("is a button named by its tooltip when it takes a click", async () => {
    const onClick = jest.fn();
    render(
      <Badge
        title="3"
        color="warning"
        textColor="text-04"
        tooltip="View Errors"
        onClick={onClick}
      />
    );

    const button = screen.getByRole("button", { name: "View Errors" });
    expect(button).toHaveTextContent("3");
    expect(button).not.toHaveAttribute("aria-pressed");
    await setupUser().click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it.each([true, false])(
    "toggles as a filter with aria-pressed=%s",
    (pressed) => {
      render(
        <Badge
          title="4"
          color="error"
          textColor="text-04"
          size={6}
          tooltip="4 failed"
          aria-pressed={pressed}
          onClick={jest.fn()}
        />
      );

      const button = screen.getByRole("button", { name: "4 failed" });
      expect(button).toHaveAttribute("aria-pressed", String(pressed));
      const root = button.querySelector(".opal-badge");
      expect(root).toHaveAttribute("data-size", "6");
      expect(root?.hasAttribute("data-pressed")).toBe(pressed);
    }
  );
});
