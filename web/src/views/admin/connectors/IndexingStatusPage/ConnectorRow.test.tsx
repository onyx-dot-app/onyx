/** A connector row on LineLayout, with a size-20 spinner tag, text-02 access icon and the SvgDocFile View Logs. */
import { render, screen, setupUser } from "@tests/setup/test-utils";
import {
  SvgAlertTriangle,
  SvgDocFile,
  SvgFileText,
  SvgOrganization,
  SvgUsers,
  SvgUserSync,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import {
  ConnectorCredentialPairStatus,
  type IndexingConnectorRow,
} from "@/lib/connectors/types";
import { ValidSources } from "@/lib/connectors/types/source";
import ConnectorRow from "@/views/admin/connectors/IndexingStatusPage/ConnectorRow";
import englishMessages from "@/i18n/messages/en.json";

// A private pair's access line reads its visible group count.
const SHARED_LABEL = "Shared with 2 groups";

// A line under 620 px, which is a card under 640 px once its border and padding are taken off.
const BELOW_640 = String.raw`@max-\[(?:38\.75rem|620px)\]:`;

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
  group_count: 2,
  group_names: ["Sales", "Support"],
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
      onFocusError={jest.fn()}
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

/** The first svg inside the closest self-or-ancestor of `element` that holds one. */
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
    const d = part(screen.getByRole("link", { name: "Manage" }));

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
    const label = screen.getByText(SHARED_LABEL);
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

    const tag = screen.getByText("Indexing").closest(".opal-badge");
    expect(tag).toHaveAttribute("data-size", "5");
    expect(tag!.querySelector('svg[role="status"]')).not.toBeNull();
  });

  it("AC-5: colors the access icon text-02", () => {
    renderRow();

    expect(nearestIcon(screen.getByText(SHARED_LABEL))).toHaveClass(
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

// ── Rows on the status page: access line, counts, error button, actions ─────

/** The English message at `path`. A missing key fails the test. */
function copy(path: string): string {
  const raw = path
    .split(".")
    .reduce<unknown>(
      (node, key) =>
        node !== null && typeof node === "object"
          ? (node as Record<string, unknown>)[key]
          : undefined,
      englishMessages
    );
  expect({ key: path, type: typeof raw }).toEqual({
    key: path,
    type: "string",
  });
  return raw as string;
}

const LIST = "admin.indexing.list";
const KEYS = {
  public: `${LIST}.access.public`,
  sync: `${LIST}.access.sync`,
  syncRestricted: `${LIST}.access.sync_restricted`,
  shared: `${LIST}.access.private`,
  recentlyProcessed: `${LIST}.docs.processed`,
  viewErrors: `${LIST}.actions.viewErrors`,
  manage: `${LIST}.actions.manage`,
  expand: `${LIST}.actions.expand`,
};

// Opal's md button (28 px) sets this height on its interactive container.
const MD_HEIGHT = "h-(--height-line-h3-section)";

function makeRow(overrides: Partial<IndexingConnectorRow> = {}) {
  return { ...ROW, ...overrides } as IndexingConnectorRow;
}

/** An indexed row whose last run finished and processed 1,204 documents. */
function indexedRow(overrides: Partial<IndexingConnectorRow> = {}) {
  return makeRow({
    status: "indexed",
    latest_index_attempt: {
      ...ROW.latest_index_attempt!,
      status: "success",
      time_finished: NOW,
    },
    ...overrides,
  });
}

function renderStatusRow(
  row: IndexingConnectorRow,
  handlers: { onToggle?: jest.Mock; onFocusError?: jest.Mock } = {}
) {
  return render(
    <ConnectorRow
      row={row}
      expanded={false}
      onToggle={handlers.onToggle ?? jest.fn()}
      onViewLogs={jest.fn()}
      onFocusError={handlers.onFocusError ?? jest.fn()}
      dimmed={false}
      onFocusChange={jest.fn()}
    />
  );
}

/** The element Opal sizes: the control itself or the container inside it. */
function sizedBox(control: HTMLElement): HTMLElement {
  if (control.classList.contains("interactive-container")) return control;
  const inner = control.querySelector<HTMLElement>(".interactive-container");
  expect(inner).not.toBeNull();
  return inner!;
}

/** Opal marks a disabled control, or a wrapper around it, with aria-disabled. */
function isDisabled(control: HTMLElement): boolean {
  if (control.hasAttribute("disabled")) return true;
  return control.closest('[aria-disabled="true"]') !== null;
}

describe("ConnectorRow on the status page", () => {
  it.each([
    ["sync", KEYS.sync, "Auto-sync permissions", SvgUserSync],
    [
      "sync_restricted",
      KEYS.syncRestricted,
      "Auto-sync permissions",
      SvgUserSync,
    ],
    ["public", KEYS.public, "Public to your organization", SvgOrganization],
  ] as const)(
    "AC-1: a %s row reads its access line from the key with the matching icon",
    (accessType, key, english, Icon) => {
      expect(copy(key)).toBe(english);
      const reference = referencePaths(Icon);
      renderStatusRow(
        makeRow({ access_type: accessType, group_count: 0, group_names: [] })
      );

      expect(iconPaths(nearestIcon(screen.getByText(english)))).toEqual(
        reference
      );
    }
  );

  it("AC-1: a private row says how many groups it is shared with, with the users icon", () => {
    copy(KEYS.shared);
    const reference = referencePaths(SvgUsers);
    renderStatusRow(
      makeRow({
        access_type: "private",
        group_count: 3,
        group_names: ["Eng", "Sales", "Support"],
      })
    );

    const label = screen.getByText("Shared with 3 groups");
    expect(iconPaths(nearestIcon(label))).toEqual(reference);
    expect(screen.queryByText("Private")).not.toBeInTheDocument();
  });

  it("AC-1: shows no creator line", () => {
    renderStatusRow(
      makeRow({
        creator_name: "Dana Whitfield",
        creator_email: "dana@example.com",
      })
    );

    expect(screen.queryByText("Dana Whitfield")).not.toBeInTheDocument();
    expect(screen.queryByText("dana@example.com")).not.toBeInTheDocument();
  });

  it("AC-1: Manage and View Details are 28 px (md) buttons", () => {
    renderStatusRow(makeRow());

    const manage = screen.getByRole("link", { name: copy(KEYS.manage) });
    const expand = screen.getByRole("button", { name: copy(KEYS.expand) });
    expect(sizedBox(manage)).toHaveClass(MD_HEIGHT);
    expect(sizedBox(expand)).toHaveClass(MD_HEIGHT);
  });

  it("AC-2: the error count is a View Errors button that asks to focus the panel on the pair's errors", async () => {
    const viewErrors = copy(KEYS.viewErrors);
    // No open errors, no button.
    const { unmount } = renderStatusRow(indexedRow({ open_error_count: 0 }));
    expect(screen.getByText("42,918")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: viewErrors })
    ).not.toBeInTheDocument();
    unmount();

    const onFocusError = jest.fn();
    const onToggle = jest.fn();
    renderStatusRow(makeRow({ open_error_count: 3 }), {
      onFocusError,
      onToggle,
    });

    const button = screen.getByRole("button", { name: viewErrors });
    expect(button).toHaveTextContent("3");
    await setupUser().click(button);

    expect(onFocusError).toHaveBeenCalledTimes(1);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("AC-3: shows the last run's processed documents as recently processed under the value", () => {
    copy(KEYS.recentlyProcessed);
    renderStatusRow(indexedRow());

    expect(screen.getByText("1,204 recently processed")).toBeInTheDocument();
  });

  it("AC-3: hides recently processed at zero and while deleting", () => {
    copy(KEYS.recentlyProcessed);
    const { unmount } = renderStatusRow(
      indexedRow({
        latest_index_attempt: {
          ...ROW.latest_index_attempt!,
          status: "success",
          total_docs_indexed: 0,
          time_finished: NOW,
        },
      })
    );
    expect(screen.getByText("42,918")).toBeInTheDocument();
    expect(screen.queryByText(/processed/)).not.toBeInTheDocument();
    unmount();

    renderStatusRow(indexedRow({ status: "deleting" }));
    expect(screen.getByText("42,918")).toBeInTheDocument();
    expect(screen.queryByText(/processed/)).not.toBeInTheDocument();
  });

  it("AC-3: hides the document count at zero", () => {
    renderStatusRow(
      indexedRow({
        docs_indexed: 0,
        latest_index_attempt: {
          ...ROW.latest_index_attempt!,
          status: "success",
          total_docs_indexed: 0,
          time_finished: NOW,
        },
      })
    );

    expect(screen.getByText(ROW.name)).toBeInTheDocument();
    expect(
      screen.queryByText(copy(`${LIST}.docs.label`))
    ).not.toBeInTheDocument();
  });

  it("AC-8: without operate, Manage stays in place but is disabled while View Details still works", async () => {
    const onToggle = jest.fn();
    renderStatusRow(makeRow({ permissions: { operate: false } }), {
      onToggle,
    });

    const manage = screen.getByLabelText(copy(KEYS.manage));
    expect(isDisabled(manage)).toBe(true);
    const expand = screen.getByRole("button", { name: copy(KEYS.expand) });
    expect(isDisabled(expand)).toBe(false);
    await setupUser().click(expand);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
