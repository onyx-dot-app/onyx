/** FE-1: a run line on LineLayout, with a size-20 spinner tag, text-02 run-type icon and the SvgDocFile View Logs. */
import { render, screen } from "@tests/setup/test-utils";
import { SvgAlertTriangle, SvgDocFile, SvgFileText } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import type { CCPairRun } from "@/lib/connectors/types";
import RunRow from "@/views/admin/connectors/ConnectorDetailPage/RunRow";

const BELOW_640 = String.raw`@max-\[(?:39\.9rem|639px)\]:`;

const NOW = new Date().toISOString();

// A running index attempt that already logged an error, so Cancel and View Logs both show.
const RUN: CCPairRun = {
  kind: "indexing",
  time_created: NOW,
  resolved_at: null,
  superseded: false,
  attempt: {
    id: 21,
    status: "in_progress",
    from_beginning: false,
    new_docs_indexed: 100,
    docs_removed_from_index: 0,
    total_docs_indexed: 125,
    error_msg: "Connector timed out",
    error_count: 0,
    open_error_count: 0,
    open_doc_error_count: 0,
    full_exception_trace: null,
    time_started: NOW,
    time_updated: NOW,
    time_finished: null,
    is_new_model: false,
    is_backfill: false,
  },
};

function renderRun() {
  return render(
    <RunRow
      run={RUN}
      canCancel
      onCancel={jest.fn()}
      onViewLogs={jest.fn()}
      open={false}
      onOpenChange={jest.fn()}
      dimmed={false}
    />
  );
}

function hasClass(element: Element, pattern: string): boolean {
  const re = new RegExp(`^${pattern}$`);
  return Array.from(element.classList).some((name) => re.test(name));
}

/** Classes that would lay the subtree out as a CSS grid. */
function gridClasses(root: Element): string[] {
  return [root, ...Array.from(root.querySelectorAll("*"))]
    .flatMap((element) => Array.from(element.classList))
    .filter((name) => /(^|:)(inline-)?grid($|-)/.test(name));
}

function iconPaths(svg: Element): string[] {
  return Array.from(svg.querySelectorAll("path")).map(
    (path) => path.getAttribute("d") ?? ""
  );
}

function referencePaths(Icon: IconFunctionComponent): string[] {
  const { container, unmount } = render(<Icon size={16} />);
  const paths = iconPaths(container.querySelector("svg")!);
  unmount();
  return paths;
}

/** The nearest svg at or above `element`'s nearest ancestor that holds one. */
function nearestIcon(element: HTMLElement): SVGElement {
  let current: HTMLElement | null = element;
  while (current !== null && current.querySelector("svg") === null) {
    current = current.parentElement;
  }
  return current!.querySelector("svg")!;
}

function lineParts(container: HTMLElement) {
  const third = container.querySelector<HTMLElement>(".basis-1\\/3");
  expect(third).not.toBeNull();
  const root = third!.parentElement!;
  function part(element: HTMLElement): HTMLElement {
    let current = element;
    while (current.parentElement !== root && current.parentElement !== third) {
      if (current.parentElement === null) {
        throw new Error("element sits outside the line");
      }
      current = current.parentElement;
    }
    return current;
  }
  return { root, third: third!, part };
}

describe("RunRow on LineLayout", () => {
  it("AC-1, D-1: puts the type in A, the status in B, the counts in C and the actions in D, with no grid", () => {
    const { container } = renderRun();
    const { root, third, part } = lineParts(container);

    const a = part(screen.getByText("Document Index"));
    const b = part(screen.getByText("Indexing"));
    const c = part(screen.getByText("indexed"));
    const d = part(screen.getByRole("button", { name: "View Logs" }));

    expect(a.parentElement).toBe(root);
    expect(a).toHaveClass("flex-1", "min-w-0");
    expect(b.parentElement).toBe(root);
    expect(b).toHaveClass("flex-1", "min-w-0");
    expect(a).not.toBe(b);
    expect(c.parentElement).toBe(third);
    expect(c).toHaveClass("flex-1", "min-w-0");
    expect(d.parentElement).toBe(third);
    expect(d).toHaveClass("w-16", "shrink-0");
    expect(part(screen.getByRole("button", { name: "Cancel" }))).toBe(d);
    expect(gridClasses(container)).toEqual([]);
  });

  it("AC-2: gives a run line's actions the 90 px floor below 640 px", () => {
    const { container } = renderRun();
    const { part } = lineParts(container);

    const d = part(screen.getByRole("button", { name: "View Logs" }));
    expect(hasClass(d, `${BELOW_640}min-w-\\[(?:90px|5\\.625rem)\\]`)).toBe(
      true
    );
  });

  it("AC-1: sits under a container query root inside the run line", () => {
    const { container } = renderRun();
    const { root } = lineParts(container);

    const queryRoot = root.closest('[class~="@container"]');
    expect(queryRoot).not.toBeNull();
    expect(container.contains(queryRoot)).toBe(true);
  });

  it("AC-3: View Logs uses SvgDocFile, not SvgAlertTriangle or SvgFileText", () => {
    const docFile = referencePaths(SvgDocFile);
    const alert = referencePaths(SvgAlertTriangle);
    const fileText = referencePaths(SvgFileText);
    renderRun();

    const button = screen.getByRole("button", { name: "View Logs" });
    const glyph = iconPaths(button.querySelector("svg")!);
    expect(glyph).toEqual(docFile);
    expect(glyph).not.toEqual(alert);
    expect(glyph).not.toEqual(fileText);
  });

  it("AC-4, AC-5: tags a running run at size 20 with the Opal spinner", () => {
    renderRun();

    const tag = screen.getByText("Indexing").closest(".opal-auxiliary-tag");
    expect(tag).toHaveAttribute("data-size", "20");
    expect(tag!.querySelector('svg[role="status"]')).not.toBeNull();
  });

  it("AC-5: colors the run-type icon text-02", () => {
    renderRun();

    expect(nearestIcon(screen.getByText("Document Index"))).toHaveClass(
      "stroke-text-02"
    );
  });
});
