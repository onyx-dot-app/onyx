import { render, screen, setupUser } from "@tests/setup/test-utils";
import { Card } from "@opal/components";
import { Interactive } from "@opal/core";

describe("Card data attributes", () => {
  it("forwards data-* to the root", () => {
    render(
      <Card data-card data-label="group-card">
        <p>Body</p>
      </Card>
    );

    const card = screen.getByText("Body").parentElement;
    expect(card).toHaveAttribute("data-card");
    expect(card).toHaveAttribute("data-label", "group-card");
  });

  it("forwards data-* in expandable mode", () => {
    render(
      <Card expandable expandedContent={<p>More</p>} data-label="expandable">
        <p>Header</p>
      </Card>
    );

    expect(
      document.querySelector('[data-label="expandable"]')
    ).toBeInTheDocument();
  });

  it("keeps its own styling attributes authoritative", () => {
    render(
      <Card color="background-tint-01" data-color="spoofed">
        <p>Body</p>
      </Card>
    );

    // The card's own `data-color` is written after the spread, so a caller
    // cannot repurpose it to drive the stylesheet.
    expect(screen.getByText("Body").parentElement).toHaveAttribute(
      "data-color",
      "background-tint-01"
    );
  });

  it.each([false, true])(
    "forwards interaction props and merges classes (expandable: %s)",
    async (expandable) => {
      const user = setupUser();
      const onClick = jest.fn();
      const onKeyDown = jest.fn();
      const mode = expandable
        ? { expandable: true as const, expandedContent: <p>More</p> }
        : { expandable: false as const };
      render(
        <Interactive.Simple
          onClick={onClick}
          onKeyDown={onKeyDown}
          role="button"
          tabIndex={0}
          aria-label="Preview skill"
          group="group/SkillCard"
        >
          <Card {...mode} className="custom-card">
            Body
          </Card>
        </Interactive.Simple>
      );

      const card = screen.getByRole("button", { name: "Preview skill" });
      expect(card).toHaveClass(
        expandable ? "opal-card-expandable" : "opal-card",
        "custom-card",
        "group/SkillCard"
      );
      await user.click(card);
      expect(onClick).toHaveBeenCalledTimes(1);
      card.focus();
      await user.keyboard("{Enter}");
      expect(onKeyDown).toHaveBeenCalledWith(
        expect.objectContaining({ key: "Enter" })
      );
      expect(card).not.toHaveAttribute("expandable");
      expect(card).not.toHaveAttribute("expandedContent");
    }
  );
});

describe("Card disabled", () => {
  it("marks the root when disabled", () => {
    render(
      <Card disabled>
        <p>Body</p>
      </Card>
    );
    expect(screen.getByText("Body").parentElement).toHaveAttribute(
      "data-disabled"
    );
  });

  it("omits the attribute entirely when not disabled", () => {
    render(
      <Card>
        <p>Body</p>
      </Card>
    );
    // Absent rather than data-disabled="false", so a bare [data-disabled]
    // selector works.
    expect(screen.getByText("Body").parentElement).not.toHaveAttribute(
      "data-disabled"
    );
  });

  it("stacks with color and border rather than replacing them", () => {
    render(
      <Card disabled color="transparent" border="dashed">
        <p>Body</p>
      </Card>
    );
    const card = screen.getByText("Body").parentElement;
    expect(card).toHaveAttribute("data-disabled");
    expect(card).toHaveAttribute("data-color", "transparent");
    expect(card).toHaveAttribute("data-border", "dashed");
  });

  it("dims the whole card in expandable mode, not just the header", () => {
    render(
      <Card expandable expandedContent={<p>More</p>} disabled>
        <p>Header</p>
      </Card>
    );
    // On the outer wrapper, so the expanded body dims with the header rather
    // than staying fully opaque beside it.
    expect(
      document.querySelector(".opal-card-expandable[data-disabled]")
    ).toBeInTheDocument();
    expect(
      document.querySelector(".opal-card-expandable-header[data-disabled]")
    ).not.toBeInTheDocument();
  });
});
