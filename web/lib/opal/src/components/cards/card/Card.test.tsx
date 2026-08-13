// A card owns how it looks, not what the surrounding app calls it. `data-*` is
// the app's namespace — test hooks and analytics markers — so the card forwards
// it rather than swallowing it.
//
// This is worth asserting because the failure mode is silent: a dropped
// attribute still type-checks and still renders, and only surfaces as an
// unrelated selector failure somewhere downstream.
import { render, screen } from "@tests/setup/test-utils";
import { Card } from "@opal/components";

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
      <Card background="heavy" data-background="spoofed">
        <p>Body</p>
      </Card>
    );

    // The card's own `data-background` is written after the spread, so a caller
    // cannot repurpose it to drive the stylesheet.
    expect(screen.getByText("Body").parentElement).toHaveAttribute(
      "data-background",
      "heavy"
    );
  });

  it("does not forward className or style", () => {
    render(
      // @ts-expect-error — WithoutStyles keeps these off the public API.
      <Card className="injected" style={{ padding: 999 }}>
        <p>Body</p>
      </Card>
    );

    const card = screen.getByText("Body").parentElement;
    expect(card).not.toHaveClass("injected");
    expect(card?.getAttribute("style")).not.toContain("999");
  });
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

  it("stacks with background and border rather than replacing them", () => {
    render(
      <Card disabled background="none" border="dashed">
        <p>Body</p>
      </Card>
    );
    const card = screen.getByText("Body").parentElement;
    expect(card).toHaveAttribute("data-disabled");
    expect(card).toHaveAttribute("data-background", "none");
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
