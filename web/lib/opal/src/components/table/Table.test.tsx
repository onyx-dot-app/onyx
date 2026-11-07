import { render, screen, setupUser } from "@tests/setup/test-utils";
import { Table, type TableColumn } from "@opal/components";

interface Row {
  id: string;
  name: string;
}

const ROWS: Row[] = ["a", "b", "c"].map((id) => ({ id, name: `Row ${id}` }));
const COLUMNS: TableColumn<Row>[] = [
  { kind: "data", field: "name", title: "Name", sortable: false },
];

function renderTable(props: Partial<Parameters<typeof Table<Row>>[0]>) {
  const { container } = render(
    <Table
      items={ROWS}
      columns={COLUMNS}
      getRowId={(row) => row.id}
      {...props}
    />
  );
  return {
    footer: container.querySelector(".table-footer"),
    header: container.querySelector("thead"),
  };
}

describe("Table header, footer and paging", () => {
  it("shows every row and no footer by default", () => {
    const { footer } = renderTable({});
    expect(screen.getAllByText(/^Row /)).toHaveLength(3);
    expect(footer).toBeNull();
  });

  it("brings the footer when the rows fill more than one page", () => {
    const { footer } = renderTable({ pageSize: 2 });
    expect(screen.getAllByText(/^Row /)).toHaveLength(2);
    expect(footer).not.toBeNull();
  });

  it("shows every row with pageSize false, even with a footer", () => {
    renderTable({ pageSize: false, footer: true });
    expect(screen.getAllByText(/^Row /)).toHaveLength(3);
  });

  it("shows the default footer with footer true", () => {
    const { footer } = renderTable({ footer: true });
    expect(footer).not.toBeNull();
  });

  it("hides the header row with header false", () => {
    expect(renderTable({}).header?.querySelector("tr")).not.toBeNull();
    expect(
      renderTable({ header: false }).header?.querySelector("tr") ?? null
    ).toBeNull();
  });
});

describe("Table selection", () => {
  const columns: TableColumn<Row>[] = [
    { kind: "qualifier", content: "checkbox" },
    ...COLUMNS,
  ];

  it("labels selection across pages without calling off-page rows visible", async () => {
    const items = Array.from({ length: 12 }, (_, index) => ({
      id: String(index),
      name: `Row ${index}`,
    }));
    const onSelectionChange = jest.fn();
    renderTable({
      items,
      columns,
      pageSize: 10,
      selectionBehavior: "multi-select",
      onSelectionChange,
    });
    expect(screen.getAllByText(/^Row /)).toHaveLength(10);
    await setupUser().click(
      screen.getByRole("checkbox", { name: "Select all rows" })
    );
    expect(onSelectionChange).toHaveBeenLastCalledWith(
      new Set(items.map((row) => row.id))
    );
  });

  it("selects all filtered rows, completes partial selection and clears it", async () => {
    renderTable({ columns, selectionBehavior: "multi-select", query: "Row a" });
    const user = setupUser();
    const all = screen.getByRole("checkbox", {
      name: "Select all rows",
    });
    await user.click(all);
    expect(screen.getByRole("checkbox", { name: "Select a" })).toBeChecked();
    expect(all).toBeChecked();
    await user.click(all);
    expect(all).not.toBeChecked();
  });

  it("keeps keyboard focus, selection and row activation separate", async () => {
    const onRowClick = jest.fn();
    renderTable({
      columns,
      selectionBehavior: "multi-select",
      onRowClick,
      getRowLabel: (row) => row.name,
    });
    const user = setupUser();
    const checkbox = screen.getByRole("checkbox", { name: "Select Row a" });
    await user.tab();
    expect(
      screen.getByRole("checkbox", { name: "Select all rows" })
    ).toHaveFocus();
    await user.tab();
    const row = screen.getByRole("row", { name: "Row a" });
    expect(row).toHaveFocus();
    expect(checkbox).not.toBeChecked();
    await user.tab();
    expect(checkbox).toHaveFocus();
    expect(checkbox).not.toBeChecked();
    await user.keyboard(" ");
    expect(checkbox).toBeChecked();
    expect(onRowClick).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");
    expect(checkbox).not.toBeChecked();
    expect(onRowClick).not.toHaveBeenCalled();
    await user.tab({ shift: true });
    await user.keyboard("{Enter}");
    expect(onRowClick).toHaveBeenCalledWith(ROWS[0]);
  });

  it("uses the whole checkbox label as a target without opening the row", async () => {
    const onRowClick = jest.fn();
    renderTable({ columns, selectionBehavior: "multi-select", onRowClick });
    const user = setupUser();
    const checkbox = screen.getByRole("checkbox", { name: "Select a" });
    const label = checkbox.closest("label");
    expect(label).not.toBeNull();
    if (!label) throw new Error("Missing checkbox label");
    await user.click(label);
    expect(checkbox).toBeChecked();
    expect(onRowClick).not.toHaveBeenCalled();
    await user.click(screen.getByRole("checkbox", { name: "Select all rows" }));
    for (const name of ["a", "b", "c"]) {
      expect(
        screen.getByRole("checkbox", { name: `Select ${name}` })
      ).toBeChecked();
    }
  });

  it("locks selection and clear while preserving checked state and row actions", async () => {
    const onSelectionChange = jest.fn();
    const onRowClick = jest.fn();
    renderTable({
      columns,
      selectionBehavior: "multi-select",
      selectionDisabled: true,
      values: new Set(["a"]),
      onSelectionChange,
      onRowClick,
      footer: true,
    });
    const user = setupUser();
    const all = screen.getByRole("checkbox", {
      name: "Select all rows",
    });
    expect(all).toBePartiallyChecked();
    for (const checkbox of screen.getAllByRole("checkbox")) {
      expect(checkbox).toHaveAttribute("tabindex", "-1");
      await user.click(checkbox);
      const label = checkbox.closest("label");
      if (label) await user.click(label);
    }
    expect(screen.getByRole("button", { name: "Deselect all" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Select a" })).toBeChecked();
    await user.click(screen.getByText("Row a"));
    expect(onRowClick).toHaveBeenCalledWith(ROWS[0]);
    expect(onSelectionChange).not.toHaveBeenCalled();
  });
});
