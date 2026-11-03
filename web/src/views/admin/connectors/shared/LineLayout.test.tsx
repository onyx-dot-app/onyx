/** One flex line (A, B, a third column of C and a 64 px D) with per-variant minimums below 640 px, pinned by class since jsdom has no layout. */
import { render, screen } from "@tests/setup/test-utils";
import LineLayout from "@/views/admin/connectors/shared/LineLayout";

// A line under 620 px, which is a card under 640 px once its border and padding are taken off.
const BELOW_640 = String.raw`@max-\[(?:38\.75rem|620px)\]:`;

function hasClass(element: Element, pattern: string): boolean {
  const re = new RegExp(`^${pattern}$`);
  return Array.from(element.classList).some((name) => re.test(name));
}

function renderLine(variant: "row" | "run") {
  const view = render(
    <LineLayout
      variant={variant}
      a={<span>part-a</span>}
      b={<span>part-b</span>}
      c={<span>part-c</span>}
      d={<span>part-d</span>}
    />
  );
  // Each part is the marker's ancestor that is a direct child of the root or the third column.
  const d = screen.getByText("part-d").closest(".w-16");
  expect(d).not.toBeNull();
  const third = d!.parentElement!;
  const root = third.parentElement!;
  function part(marker: string): HTMLElement {
    let element: HTMLElement = screen.getByText(marker);
    while (element.parentElement !== root && element.parentElement !== third) {
      element = element.parentElement!;
    }
    return element;
  }
  return {
    ...view,
    root,
    third,
    a: part("part-a"),
    b: part("part-b"),
    c: part("part-c"),
    d: d as HTMLElement,
  };
}

describe("LineLayout", () => {
  it("AC-1: lays A, B and the third column out in one flex row", () => {
    const { root, third, a, b, c, d } = renderLine("row");

    expect(root).toHaveClass("flex", "flex-row");
    expect(a.parentElement).toBe(root);
    expect(b.parentElement).toBe(root);
    expect(third.parentElement).toBe(root);
    expect(c.parentElement).toBe(third);
    expect(d.parentElement).toBe(third);
    expect(new Set([a, b, c, d]).size).toBe(4);
  });

  it("AC-1: A and B share the width equally", () => {
    const { a, b } = renderLine("row");

    expect(a).toHaveClass("flex-1", "min-w-0");
    expect(b).toHaveClass("flex-1", "min-w-0");
  });

  it("AC-1: the third column is a third of the line, capped at 208 px, and holds C and a 64 px D", () => {
    const { third, c, d } = renderLine("row");

    // Pinned as basis-1/3 shrink-0: flex-none would reset the basis to auto, and tailwind-merge drops basis-1/3 after it.
    expect(third).toHaveClass("basis-1/3", "shrink-0");
    expect(third).not.toHaveClass("flex-1");
    expect(third).not.toHaveClass("grow");
    expect(hasClass(third, String.raw`max-w-\[(?:208px|13rem)\]`)).toBe(true);
    expect(c).toHaveClass("flex-1", "min-w-0");
    expect(d).toHaveClass("w-16", "shrink-0");
  });

  it("AC-1: A, B and C pad 8 px so content starts 16 px from the card edge", () => {
    const { a, b, c } = renderLine("row");

    for (const element of [a, b, c]) {
      expect(element).toHaveStyle({ padding: "0.5rem" });
    }
  });

  it("D-1: uses no CSS grid anywhere", () => {
    const { container } = renderLine("row");

    const all = [container, ...Array.from(container.querySelectorAll("*"))];
    const gridClasses = all.flatMap((element) =>
      Array.from(element.classList).filter((name) =>
        /(^|:)(inline-)?grid($|-)/.test(name)
      )
    );
    expect(gridClasses).toEqual([]);
  });

  it("AC-2: wraps below 640 px", () => {
    const { root } = renderLine("row");

    expect(hasClass(root, `(?:${BELOW_640})?flex-wrap`)).toBe(true);
  });

  it("AC-2: a row's name takes at least 280 px and its status and counts at least 188 px, counts at most 280 px, below 640", () => {
    const { a, b, c } = renderLine("row");

    expect(hasClass(a, `${BELOW_640}min-w-\\[(?:280px|17\\.5rem)\\]`)).toBe(
      true
    );
    expect(hasClass(b, `${BELOW_640}min-w-\\[(?:188px|11\\.75rem)\\]`)).toBe(
      true
    );
    expect(hasClass(c, `${BELOW_640}min-w-\\[(?:188px|11\\.75rem)\\]`)).toBe(
      true
    );
    expect(hasClass(c, `${BELOW_640}max-w-\\[(?:280px|17\\.5rem)\\]`)).toBe(
      true
    );
  });

  it("AC-2: a run line's actions take at least 90 px and its status and counts at least 188 px below 640", () => {
    const { a, b, c, d } = renderLine("run");

    expect(hasClass(d, `${BELOW_640}min-w-\\[(?:90px|5\\.625rem)\\]`)).toBe(
      true
    );
    expect(hasClass(b, `${BELOW_640}min-w-\\[(?:188px|11\\.75rem)\\]`)).toBe(
      true
    );
    expect(hasClass(c, `${BELOW_640}min-w-\\[(?:188px|11\\.75rem)\\]`)).toBe(
      true
    );
    // A run line's first part splits into time and type, so it has no 280 px floor.
    expect(hasClass(a, `${BELOW_640}min-w-\\[(?:280px|17\\.5rem)\\]`)).toBe(
      false
    );
  });

  it.each(["row", "run"] as const)(
    "AC-2: a %s puts A and D on line 1 and B and C on line 2 below 640",
    (variant) => {
      const { third, a, b, c, d } = renderLine(variant);

      // The third column dissolves so D and C wrap as root items, ordered A, D, B, C.
      expect(hasClass(third, `${BELOW_640}contents`)).toBe(true);
      expect(hasClass(a, `${BELOW_640}order-1`)).toBe(true);
      expect(hasClass(d, `${BELOW_640}order-2`)).toBe(true);
      expect(hasClass(b, `${BELOW_640}order-3`)).toBe(true);
      expect(hasClass(c, `${BELOW_640}order-4`)).toBe(true);
      // A takes all of line 1 but D's width, so B cannot fit beside them.
      expect(
        hasClass(a, `${BELOW_640}basis-\\[calc\\(100%-[^\\]]+\\)\\]`)
      ).toBe(true);
    }
  );
});
