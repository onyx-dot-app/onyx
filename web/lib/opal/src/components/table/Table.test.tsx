import { render, screen } from "@tests/setup/test-utils";
import { Table, type TableColumn } from "@opal/components";

interface Row {
  id: string;
  name: string;
}

const ROWS: Row[] = ["a", "b", "c"].map((id) => ({ id, name: `Row ${id}` }));
const COLUMNS: TableColumn<Row>[] = [
  { kind: "data", field: "name", title: "Name" },
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
