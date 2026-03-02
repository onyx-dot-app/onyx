"use client";
"use no memo";

import { useState } from "react";
import { createColumnHelper, flexRender } from "@tanstack/react-table";
import useDataTable, { toOnyxSortDirection } from "@/hooks/useDataTable";
import useDraggableRows from "@/hooks/useDraggableRows";
import { ColumnVisibilityPopover } from "@/refresh-components/table/ColumnVisibilityPopover";
import { SortingPopover } from "@/refresh-components/table/SortingPopover";
import Text from "@/refresh-components/texts/Text";
import { Content } from "@opal/layouts";
import Table from "@/refresh-components/table/Table";
import TableHeader from "@/refresh-components/table/TableHeader";
import TableBody from "@/refresh-components/table/TableBody";
import TableRow from "@/refresh-components/table/TableRow";
import TableHead from "@/refresh-components/table/TableHead";
import TableCell from "@/refresh-components/table/TableCell";
import TableQualifier from "@/refresh-components/table/TableQualifier";
import DragOverlayRow from "@/refresh-components/table/DragOverlayRow";
import Footer from "@/refresh-components/table/Footer";
import { SvgCheckCircle, SvgClock, SvgAlertCircle } from "@opal/icons";

// ---------------------------------------------------------------------------
// Types & mock data
// ---------------------------------------------------------------------------

interface TeamMember {
  id: string;
  name: string;
  initials: string;
  email: string;
  role: string;
  department: string;
  status: "active" | "pending" | "inactive";
  joinDate: string;
}

const DATA: TeamMember[] = [
  {
    id: "1",
    name: "Alice Johnson",
    initials: "AJ",
    email: "alice.johnson@onyx.app",
    role: "Engineer",
    department: "Engineering",
    status: "active",
    joinDate: "2023-01-15",
  },
  {
    id: "2",
    name: "Bob Smith",
    initials: "BS",
    email: "bob.smith@onyx.app",
    role: "Designer",
    department: "Design",
    status: "active",
    joinDate: "2023-02-20",
  },
  {
    id: "3",
    name: "Carol Lee",
    initials: "CL",
    email: "carol.lee@onyx.app",
    role: "PM",
    department: "Product",
    status: "pending",
    joinDate: "2023-03-10",
  },
  {
    id: "4",
    name: "David Chen",
    initials: "DC",
    email: "david.chen@onyx.app",
    role: "Engineer",
    department: "Engineering",
    status: "active",
    joinDate: "2023-04-05",
  },
  {
    id: "5",
    name: "Eva Martinez",
    initials: "EM",
    email: "eva.martinez@onyx.app",
    role: "Analyst",
    department: "Data",
    status: "active",
    joinDate: "2023-05-18",
  },
  {
    id: "6",
    name: "Frank Kim",
    initials: "FK",
    email: "frank.kim@onyx.app",
    role: "Designer",
    department: "Design",
    status: "inactive",
    joinDate: "2023-06-22",
  },
  {
    id: "7",
    name: "Grace Wang",
    initials: "GW",
    email: "grace.wang@onyx.app",
    role: "Engineer",
    department: "Engineering",
    status: "active",
    joinDate: "2023-07-01",
  },
  {
    id: "8",
    name: "Henry Patel",
    initials: "HP",
    email: "henry.patel@onyx.app",
    role: "PM",
    department: "Product",
    status: "active",
    joinDate: "2023-07-15",
  },
  {
    id: "9",
    name: "Ivy Nguyen",
    initials: "IN",
    email: "ivy.nguyen@onyx.app",
    role: "Engineer",
    department: "Engineering",
    status: "pending",
    joinDate: "2023-08-03",
  },
  {
    id: "10",
    name: "Jack Brown",
    initials: "JB",
    email: "jack.brown@onyx.app",
    role: "Analyst",
    department: "Data",
    status: "active",
    joinDate: "2023-08-20",
  },
  {
    id: "11",
    name: "Karen Davis",
    initials: "KD",
    email: "karen.davis@onyx.app",
    role: "Designer",
    department: "Design",
    status: "active",
    joinDate: "2023-09-11",
  },
  {
    id: "12",
    name: "Leo Garcia",
    initials: "LG",
    email: "leo.garcia@onyx.app",
    role: "Engineer",
    department: "Engineering",
    status: "active",
    joinDate: "2023-09-25",
  },
  {
    id: "13",
    name: "Mia Thompson",
    initials: "MT",
    email: "mia.thompson@onyx.app",
    role: "PM",
    department: "Product",
    status: "inactive",
    joinDate: "2023-10-08",
  },
  {
    id: "14",
    name: "Noah Wilson",
    initials: "NW",
    email: "noah.wilson@onyx.app",
    role: "Engineer",
    department: "Engineering",
    status: "active",
    joinDate: "2023-10-19",
  },
  {
    id: "15",
    name: "Olivia Taylor",
    initials: "OT",
    email: "olivia.taylor@onyx.app",
    role: "Analyst",
    department: "Data",
    status: "active",
    joinDate: "2023-11-02",
  },
  {
    id: "16",
    name: "Paul Anderson",
    initials: "PA",
    email: "paul.anderson@onyx.app",
    role: "Designer",
    department: "Design",
    status: "pending",
    joinDate: "2023-11-14",
  },
  {
    id: "17",
    name: "Quinn Harris",
    initials: "QH",
    email: "quinn.harris@onyx.app",
    role: "Engineer",
    department: "Engineering",
    status: "active",
    joinDate: "2023-11-28",
  },
  {
    id: "18",
    name: "Rachel Clark",
    initials: "RC",
    email: "rachel.clark@onyx.app",
    role: "PM",
    department: "Product",
    status: "active",
    joinDate: "2023-12-05",
  },
  {
    id: "19",
    name: "Sam Robinson",
    initials: "SR",
    email: "sam.robinson@onyx.app",
    role: "Engineer",
    department: "Engineering",
    status: "active",
    joinDate: "2024-01-10",
  },
  {
    id: "20",
    name: "Tina Lewis",
    initials: "TL",
    email: "tina.lewis@onyx.app",
    role: "Analyst",
    department: "Data",
    status: "inactive",
    joinDate: "2024-01-22",
  },
  {
    id: "21",
    name: "Uma Walker",
    initials: "UW",
    email: "uma.walker@onyx.app",
    role: "Designer",
    department: "Design",
    status: "active",
    joinDate: "2024-02-03",
  },
  {
    id: "22",
    name: "Victor Hall",
    initials: "VH",
    email: "victor.hall@onyx.app",
    role: "Engineer",
    department: "Engineering",
    status: "active",
    joinDate: "2024-02-15",
  },
  {
    id: "23",
    name: "Wendy Young",
    initials: "WY",
    email: "wendy.young@onyx.app",
    role: "PM",
    department: "Product",
    status: "pending",
    joinDate: "2024-03-01",
  },
  {
    id: "24",
    name: "Xander King",
    initials: "XK",
    email: "xander.king@onyx.app",
    role: "Engineer",
    department: "Engineering",
    status: "active",
    joinDate: "2024-03-18",
  },
  {
    id: "25",
    name: "Yara Scott",
    initials: "YS",
    email: "yara.scott@onyx.app",
    role: "Analyst",
    department: "Data",
    status: "active",
    joinDate: "2024-04-02",
  },
];

const STATUS_CONFIG = {
  active: { icon: SvgCheckCircle },
  pending: { icon: SvgClock },
  inactive: { icon: SvgAlertCircle },
} as const;

// ---------------------------------------------------------------------------
// Column definitions
// ---------------------------------------------------------------------------

const columnHelper = createColumnHelper<TeamMember>();

const columns = [
  columnHelper.display({
    id: "qualifier",
    size: 56,
    enableResizing: false,
    enableSorting: false,
    enableHiding: false,
    cell: ({ row }) => (
      <TableQualifier
        content="avatar-user"
        initials={row.original.initials}
        selectable
        selected={row.getIsSelected()}
        onSelectChange={(checked) => {
          row.toggleSelected(checked);
        }}
      />
    ),
  }),
  columnHelper.accessor("name", {
    header: "Name",
    size: 200,
    enableSorting: true,
    enableResizing: true,
    cell: (info) => (
      <Content sizePreset="main-ui" variant="body" title={info.getValue()} />
    ),
  }),
  columnHelper.accessor("email", {
    header: "Email",
    size: 240,
    enableSorting: true,
    enableResizing: true,
    cell: (info) => (
      <Content
        sizePreset="main-ui"
        variant="body"
        title={info.getValue()}
        prominence="muted"
      />
    ),
  }),
  columnHelper.accessor("role", {
    header: "Role",
    size: 140,
    enableSorting: true,
    enableResizing: true,
    cell: (info) => (
      <Content sizePreset="main-ui" variant="body" title={info.getValue()} />
    ),
  }),
  columnHelper.accessor("department", {
    header: "Department",
    size: 160,
    enableSorting: true,
    enableResizing: true,
    cell: (info) => (
      <Content sizePreset="main-ui" variant="body" title={info.getValue()} />
    ),
  }),
  columnHelper.accessor("status", {
    header: "Status",
    size: 120,
    enableSorting: true,
    enableResizing: false,
    cell: (info) => {
      const status = info.getValue();
      const { icon } = STATUS_CONFIG[status];
      return (
        <Content
          sizePreset="main-ui"
          variant="body"
          icon={icon}
          title={status.charAt(0).toUpperCase() + status.slice(1)}
        />
      );
    },
  }),
  columnHelper.display({
    id: "__actions",
    size: 88,
    enableHiding: false,
    enableSorting: false,
    enableResizing: false,
    header: ({ table }) => (
      <div className="flex flex-row items-center">
        <ColumnVisibilityPopover
          table={table}
          columnVisibility={table.getState().columnVisibility}
        />
        <SortingPopover
          table={table}
          sorting={table.getState().sorting}
          footerText="Everyone in your organization will see the explore agents list in this order."
        />
      </div>
    ),
    cell: () => null,
  }),
];

// ---------------------------------------------------------------------------
// Small column definitions
// ---------------------------------------------------------------------------

const smallColumns = [
  columnHelper.display({
    id: "qualifier",
    size: 40,
    enableResizing: false,
    enableSorting: false,
    enableHiding: false,
    cell: ({ row }) => (
      <TableQualifier
        content="avatar-user"
        initials={row.original.initials}
        selectable
        selected={row.getIsSelected()}
        onSelectChange={(checked) => {
          row.toggleSelected(checked);
        }}
        size="small"
      />
    ),
  }),
  columnHelper.accessor("name", {
    header: "Name",
    size: 200,
    enableSorting: true,
    enableResizing: true,
    cell: (info) => (
      <Content sizePreset="secondary" variant="body" title={info.getValue()} />
    ),
  }),
  columnHelper.accessor("email", {
    header: "Email",
    size: 240,
    enableSorting: true,
    enableResizing: true,
    cell: (info) => (
      <Content
        sizePreset="secondary"
        variant="body"
        title={info.getValue()}
        prominence="muted"
      />
    ),
  }),
  columnHelper.accessor("role", {
    header: "Role",
    size: 140,
    enableSorting: true,
    enableResizing: true,
    cell: (info) => (
      <Content sizePreset="secondary" variant="body" title={info.getValue()} />
    ),
  }),
  columnHelper.accessor("department", {
    header: "Department",
    size: 160,
    enableSorting: true,
    enableResizing: true,
    cell: (info) => (
      <Content sizePreset="secondary" variant="body" title={info.getValue()} />
    ),
  }),
  columnHelper.accessor("status", {
    header: "Status",
    size: 120,
    enableSorting: true,
    enableResizing: false,
    cell: (info) => {
      const status = info.getValue();
      const { icon } = STATUS_CONFIG[status];
      return (
        <Content
          sizePreset="secondary"
          variant="body"
          icon={icon}
          title={status.charAt(0).toUpperCase() + status.slice(1)}
        />
      );
    },
  }),
  columnHelper.display({
    id: "__actions",
    size: 88,
    enableHiding: false,
    enableSorting: false,
    enableResizing: false,
    header: ({ table }) => (
      <div className="flex flex-row items-center">
        <SortingPopover
          table={table}
          sorting={table.getState().sorting}
          size="small"
        />
        <ColumnVisibilityPopover
          table={table}
          columnVisibility={table.getState().columnVisibility}
          size="small"
        />
      </div>
    ),
    cell: () => null,
  }),
];

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

const PAGE_SIZE = 10;

export default function DataTableDemoPage() {
  const [items, setItems] = useState(DATA);

  const {
    table,
    currentPage,
    totalPages,
    totalItems,
    setPage,
    pageSize,
    selectionState,
    selectedCount,
    clearSelection,
    toggleAllPageRowsSelected,
    isAllPageRowsSelected,
  } = useDataTable({
    data: items,
    columns,
    pageSize: PAGE_SIZE,
    initialColumnVisibility: { department: false },
  });

  const draggable = useDraggableRows({
    data: items,
    getRowId: (row) => row.id,
    enabled: table.getState().sorting.length === 0,
    onReorder: (ids, changedOrders) => {
      setItems(ids.map((id) => items.find((r) => r.id === id)!));
      console.log("Changed sort orders:", changedOrders);
    },
  });

  const {
    table: smallTable,
    currentPage: smallCurrentPage,
    totalPages: smallTotalPages,
    totalItems: smallTotalItems,
    setPage: smallSetPage,
    pageSize: smallPageSize,
    selectionState: smallSelectionState,
    selectedCount: smallSelectedCount,
    clearSelection: smallClearSelection,
    toggleAllPageRowsSelected: smallToggleAllPageRowsSelected,
    isAllPageRowsSelected: smallIsAllPageRowsSelected,
  } = useDataTable({
    data: DATA,
    columns: smallColumns,
    pageSize: PAGE_SIZE,
    initialColumnVisibility: { department: false },
  });

  return (
    <div className="p-6 space-y-8">
      <div className="space-y-4">
        <Text headingH2>Data Table Demo</Text>
        <Text mainContentMuted text03>
          Demonstrates Onyx table primitives wired to TanStack Table with
          sorting, column resizing, row selection, and pagination.
        </Text>
      </div>

      <div className="border border-border-01 rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => {
                    const canSort = header.column.getCanSort();
                    const canResize = header.column.getCanResize();
                    const sortDir = header.column.getIsSorted();

                    if (header.id === "qualifier") {
                      return (
                        <TableHead key={header.id} width={header.getSize()}>
                          <TableQualifier
                            content="simple"
                            selectable
                            selected={isAllPageRowsSelected}
                            onSelectChange={(checked) =>
                              toggleAllPageRowsSelected(checked)
                            }
                          />
                        </TableHead>
                      );
                    }

                    if (header.id === "__actions") {
                      return (
                        <TableHead key={header.id} width={header.getSize()}>
                          {flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                        </TableHead>
                      );
                    }

                    return (
                      <TableHead
                        key={header.id}
                        width={header.getSize()}
                        sorted={
                          canSort ? toOnyxSortDirection(sortDir) : undefined
                        }
                        onSort={
                          canSort
                            ? () => header.column.toggleSorting()
                            : undefined
                        }
                        resizable={canResize}
                        onResizeStart={
                          canResize ? header.getResizeHandler() : undefined
                        }
                      >
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                      </TableHead>
                    );
                  })}
                </TableRow>
              ))}
            </TableHeader>

            <TableBody
              dndSortable={draggable}
              renderDragOverlay={(activeId) => {
                const row = table
                  .getRowModel()
                  .rows.find((r) => r.original.id === activeId);
                if (!row) return null;
                return <DragOverlayRow row={row} />;
              }}
            >
              {table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  sortableId={row.original.id}
                  selected={row.getIsSelected()}
                  onClick={() => row.toggleSelected()}
                >
                  {row.getVisibleCells().map((cell) => {
                    if (cell.column.id === "qualifier") {
                      return (
                        <TableCell
                          key={cell.id}
                          onClick={(e) => e.stopPropagation()}
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </TableCell>
                      );
                    }

                    return (
                      <TableCell key={cell.id}>
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext()
                        )}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <Footer
          mode="selection"
          multiSelect
          selectionState={selectionState}
          selectedCount={selectedCount}
          showQualifier
          qualifierChecked={isAllPageRowsSelected}
          onQualifierChange={(checked) => toggleAllPageRowsSelected(checked)}
          onClear={clearSelection}
          pageSize={pageSize}
          totalItems={totalItems}
          currentPage={currentPage}
          totalPages={totalPages}
          onPageChange={setPage}
        />
      </div>

      <div className="space-y-4">
        <Text headingH3>Small Variant</Text>
        <Text mainContentMuted text03>
          Same table rendered with the small size variant for denser layouts.
        </Text>
      </div>

      <div className="border border-border-01 rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              {smallTable.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => {
                    const canSort = header.column.getCanSort();
                    const canResize = header.column.getCanResize();
                    const sortDir = header.column.getIsSorted();

                    if (header.id === "qualifier") {
                      return (
                        <TableHead
                          key={header.id}
                          width={header.getSize()}
                          size="small"
                        >
                          <TableQualifier
                            content="simple"
                            selectable
                            selected={smallIsAllPageRowsSelected}
                            onSelectChange={(checked) =>
                              smallToggleAllPageRowsSelected(checked)
                            }
                            size="small"
                          />
                        </TableHead>
                      );
                    }

                    if (header.id === "__actions") {
                      return (
                        <th
                          key={header.id}
                          style={{ width: header.getSize() }}
                          className="px-1"
                        >
                          {flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                        </th>
                      );
                    }

                    return (
                      <TableHead
                        key={header.id}
                        width={header.getSize()}
                        size="small"
                        sorted={
                          canSort ? toOnyxSortDirection(sortDir) : undefined
                        }
                        onSort={
                          canSort
                            ? () => header.column.toggleSorting()
                            : undefined
                        }
                        resizable={canResize}
                        onResizeStart={
                          canResize ? header.getResizeHandler() : undefined
                        }
                      >
                        {flexRender(
                          header.column.columnDef.header,
                          header.getContext()
                        )}
                      </TableHead>
                    );
                  })}
                </TableRow>
              ))}
            </TableHeader>

            <TableBody>
              {smallTable.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  selected={row.getIsSelected()}
                  onClick={() => row.toggleSelected()}
                >
                  {row.getVisibleCells().map((cell) => {
                    if (cell.column.id === "qualifier") {
                      return (
                        <TableCell
                          key={cell.id}
                          size="small"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </TableCell>
                      );
                    }

                    if (cell.column.id === "__actions") {
                      return <td key={cell.id} />;
                    }

                    return (
                      <TableCell key={cell.id} size="small">
                        {flexRender(
                          cell.column.columnDef.cell,
                          cell.getContext()
                        )}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>

        <Footer
          mode="selection"
          multiSelect
          selectionState={smallSelectionState}
          selectedCount={smallSelectedCount}
          showQualifier
          qualifierChecked={smallIsAllPageRowsSelected}
          onQualifierChange={(checked) =>
            smallToggleAllPageRowsSelected(checked)
          }
          onClear={smallClearSelection}
          pageSize={smallPageSize}
          totalItems={smallTotalItems}
          currentPage={smallCurrentPage}
          totalPages={smallTotalPages}
          onPageChange={smallSetPage}
        />
      </div>
    </div>
  );
}
