/** FE-1: a connector row on LineLayout, with a size-20 spinner tag, text-02 access icon and the SvgDocFile View Logs. */
import { render, screen } from "@tests/setup/test-utils";
import { SvgAlertTriangle, SvgDocFile, SvgFileText } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import {
  ConnectorCredentialPairStatus,
  type IndexingConnectorRow,
} from "@/lib/connectors/types";
import { ValidSources } from "@/lib/connectors/types/source";
import ConnectorRow from "@/views/admin/connectors/IndexingStatusPage/ConnectorRow";

const BELOW_640 = String.raw`@max-\[(?:39\.9rem|639px)\]:`;

const NOW = new Date().toISOString();

const ROW: IndexingConnectorRow = {
  cc_pair_id: 7,
  name: "Sales Mailbox",
  source: ValidSources.Gmail,
  access_type: "private",
  cc_pair_status: ConnectorCredentialPairStatus.ACTIVE,
  status: "indexing",
  creator_email: null,
  creator_name: null,
  docs_indexed: 42918,
  last_success: NOW,
  latest_index_attempt: {
    id: 11,
    status: "in_progress",
    from_beginning: false,
    new_docs_indexed: 3,
    docs_removed_from_index: 0,
    total_docs_indexed: 1204,
    error_msg: null,
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
  open_error_count: 0,
  queue_position: null,
  permissions: { operate: true },
};

function renderRow(expanded = false) {
  return render(
    <ConnectorRow
      row={ROW}
      expanded={expanded}
      onToggle={jest.fn()}
      onViewLogs={jest.fn()}
      dimmed={false}
      onFocusChange={jest.fn()}
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

function lineParts() {
  const card = screen.getByTestId("indexing-connector-7");
  const third = card.querySelector<HTMLElement>(".basis-1\\/3");
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
  return { card, root, third: third!, part };
}

describe("ConnectorRow on LineLayout", () => {
  it("AC-1, D-1: puts the name in A, the status in B, the counts in C and the actions in D, with no grid", () => {
    renderRow();
    const { card, root, third, part } = lineParts();

    const a = part(screen.getByText(ROW.name));
    const b = part(screen.getByText("Indexing"));
    const c = part(screen.getByText("42,918"));
    const d = part(screen.getByRole("button", { name: "Manage" }));

    expect(a.parentElement).toBe(root);
    expect(a).toHaveClass("flex-1", "min-w-0");
    expect(b.parentElement).toBe(root);
    expect(b).toHaveClass("flex-1", "min-w-0");
    expect(a).not.toBe(b);
    expect(c.parentElement).toBe(third);
    expect(c).toHaveClass("flex-1", "min-w-0");
    expect(d.parentElement).toBe(third);
    expect(d).toHaveClass("w-16", "shrink-0");
    expect(part(screen.getByRole("button", { name: "View Details" }))).toBe(d);
    expect(gridClasses(card)).toEqual([]);
  });

  it("AC-1: sits under a container query root inside the row", () => {
    const { container } = renderRow();
    const { root } = lineParts();

    const queryRoot = root.closest('[class~="@container"]');
    expect(queryRoot).not.toBeNull();
    expect(container.contains(queryRoot)).toBe(true);
  });

  it("AC-2: drops the access line below 640 px", () => {
    renderRow();
    const { part } = lineParts();
    const label = screen.getByText("Private");
    const a = part(label);

    let hidden = false;
    for (
      let current: HTMLElement | null = label;
      current !== null && current !== a.parentElement;
      current = current.parentElement
    ) {
      hidden ||= hasClass(current, `${BELOW_640}hidden`);
    }
    expect(hidden).toBe(true);
  });

  it("AC-4, AC-5: tags a running row at size 20 with the Opal spinner", () => {
    renderRow();

    const tag = screen.getByText("Indexing").closest(".opal-auxiliary-tag");
    expect(tag).toHaveAttribute("data-size", "20");
    expect(tag!.querySelector('svg[role="status"]')).not.toBeNull();
  });

  it("AC-5: colors the access icon text-02", () => {
    renderRow();

    expect(nearestIcon(screen.getByText("Private"))).toHaveClass(
      "stroke-text-02"
    );
  });

  describe("expanded", () => {
    const realFetch = global.fetch;
    beforeEach(() => {
      // The run list stays loading. Only the row's own actions are under test.
      global.fetch = jest.fn(() => new Promise<Response>(() => {}));
    });
    afterEach(() => {
      global.fetch = realFetch;
    });

    it("AC-3: View Logs uses SvgDocFile, not SvgAlertTriangle or SvgFileText", () => {
      const docFile = referencePaths(SvgDocFile);
      const alert = referencePaths(SvgAlertTriangle);
      const fileText = referencePaths(SvgFileText);
      renderRow(true);

      const button = screen.getByRole("button", { name: "View Logs" });
      const glyph = iconPaths(button.querySelector("svg")!);
      expect(glyph).toEqual(docFile);
      expect(glyph).not.toEqual(alert);
      expect(glyph).not.toEqual(fileText);
    });
  });
});
