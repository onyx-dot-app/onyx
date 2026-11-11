import { render, screen, setupUser } from "@tests/setup/test-utils";
import { BadgeButton } from "@opal/components";

/** The badge title's colour override: Content sets --content-title-color inline on its wrapper. */
function titleColorOf(button: HTMLElement): string {
  const wrapper = button.querySelector<HTMLElement>(
    "[data-opal-content]"
  )?.parentElement;
  return wrapper?.style.getPropertyValue("--content-title-color") ?? "";
}

describe("BadgeButton", () => {
  it("is a button named by its tooltip around a static Badge", async () => {
    const onClick = jest.fn();
    render(
      <BadgeButton
        title="3"
        color="warning"
        titleColor="text-04"
        tooltip="View Errors"
        onClick={onClick}
      />
    );

    const button = screen.getByRole("button", { name: "View Errors" });
    expect(button).toHaveTextContent("3");
    expect(button).not.toHaveAttribute("aria-pressed");
    expect(titleColorOf(button)).toBe("var(--text-04)");
    await setupUser().click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it.each([true, false])(
    "toggles as a filter with aria-pressed=%s, its title in the badge's colour while pressed",
    (pressed) => {
      render(
        <BadgeButton
          title="4"
          color="error"
          titleColor="text-04"
          size={6}
          tooltip="4 failed"
          pressed={pressed}
          onClick={jest.fn()}
        />
      );

      const button = screen.getByRole("button", { name: "4 failed" });
      expect(button).toHaveAttribute("aria-pressed", String(pressed));
      const root = button.querySelector(".opal-badge");
      expect(root).toHaveAttribute("data-size", "6");
      expect(titleColorOf(button)).toBe(pressed ? "" : "var(--text-04)");
    }
  );
});
