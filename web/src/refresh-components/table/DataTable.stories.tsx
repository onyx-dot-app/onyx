import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import DataTable from "./DataTable";
import { createTableColumns } from "./columns";
import type { OnyxColumnDef } from "./types";
import Text from "@/refresh-components/texts/Text";

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

interface TeamMember {
  id: string;
  name: string;
  email: string;
  role: string;
  status: "active" | "invited" | "deactivated";
  lastActive: string;
}

const MOCK_MEMBERS: TeamMember[] = [
  {
    id: "1",
    name: "Alice Johnson",
    email: "alice@acme.com",
    role: "Admin",
    status: "active",
    lastActive: "2 hours ago",
  },
  {
    id: "2",
    name: "Bob Martinez",
    email: "bob@acme.com",
    role: "Editor",
    status: "active",
    lastActive: "5 minutes ago",
  },
  {
    id: "3",
    name: "Charlie Kim",
    email: "charlie@acme.com",
    role: "Viewer",
    status: "invited",
    lastActive: "Never",
  },
  {
    id: "4",
    name: "Diana Patel",
    email: "diana@acme.com",
    role: "Admin",
    status: "active",
    lastActive: "1 day ago",
  },
  {
    id: "5",
    name: "Ethan Lee",
    email: "ethan@acme.com",
    role: "Editor",
    status: "deactivated",
    lastActive: "3 weeks ago",
  },
  {
    id: "6",
    name: "Fiona Chen",
    email: "fiona@acme.com",
    role: "Viewer",
    status: "active",
    lastActive: "10 minutes ago",
  },
  {
    id: "7",
    name: "George Wu",
    email: "george@acme.com",
    role: "Editor",
    status: "active",
    lastActive: "1 hour ago",
  },
  {
    id: "8",
    name: "Hannah Davis",
    email: "hannah@acme.com",
    role: "Viewer",
    status: "invited",
    lastActive: "Never",
  },
  {
    id: "9",
    name: "Ivan Torres",
    email: "ivan@acme.com",
    role: "Admin",
    status: "active",
    lastActive: "30 minutes ago",
  },
  {
    id: "10",
    name: "Julia Nguyen",
    email: "julia@acme.com",
    role: "Editor",
    status: "active",
    lastActive: "3 hours ago",
  },
  {
    id: "11",
    name: "Kevin Brown",
    email: "kevin@acme.com",
    role: "Viewer",
    status: "active",
    lastActive: "Yesterday",
  },
  {
    id: "12",
    name: "Laura Smith",
    email: "laura@acme.com",
    role: "Editor",
    status: "deactivated",
    lastActive: "2 months ago",
  },
  {
    id: "13",
    name: "Mike Wilson",
    email: "mike@acme.com",
    role: "Viewer",
    status: "active",
    lastActive: "4 hours ago",
  },
  {
    id: "14",
    name: "Nina Garcia",
    email: "nina@acme.com",
    role: "Admin",
    status: "active",
    lastActive: "Just now",
  },
  {
    id: "15",
    name: "Oscar Ramirez",
    email: "oscar@acme.com",
    role: "Editor",
    status: "invited",
    lastActive: "Never",
  },
];

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

function getInitials(member: TeamMember): string {
  return member.name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase();
}

const tc = createTableColumns<TeamMember>();

const defaultColumns: OnyxColumnDef<TeamMember>[] = [
  tc.qualifier({
    content: "avatar-user",
    getInitials,
    selectable: true,
  }),
  tc.column("name", { header: "Name", weight: 22, minWidth: 120 }),
  tc.column("email", { header: "Email", weight: 28, minWidth: 150 }),
  tc.column("role", { header: "Role", weight: 15, minWidth: 80 }),
  tc.column("status", {
    header: "Status",
    weight: 15,
    minWidth: 80,
    cell: (value) => {
      const colors: Record<string, string> = {
        active: "text-status-success-02",
        invited: "text-status-warning-02",
        deactivated: "text-status-error-02",
      };
      return (
        <Text mainUiBody className={colors[value]}>
          {value.charAt(0).toUpperCase() + value.slice(1)}
        </Text>
      );
    },
  }),
  tc.column("lastActive", {
    header: "Last Active",
    weight: 20,
    minWidth: 100,
    enableSorting: false,
  }),
  tc.actions(),
];

const columnsWithoutActions: OnyxColumnDef<TeamMember>[] = defaultColumns.slice(
  0,
  -1
);

// ---------------------------------------------------------------------------
// Meta
// ---------------------------------------------------------------------------

const meta: Meta<typeof DataTable> = {
  title: "refresh-components/table/DataTable",
  component: DataTable,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <div style={{ maxWidth: 960, padding: 16 }}>
          <Story />
        </div>
      </TooltipPrimitive.Provider>
    ),
  ],
  parameters: {
    layout: "padded",
  },
};

export default meta;
type Story = StoryObj<typeof DataTable>;

// ---------------------------------------------------------------------------
// Stories
// ---------------------------------------------------------------------------

/** Basic table with all default features: qualifier column, data columns, and actions. */
export const Default: Story = {
  render: () => (
    <DataTable<TeamMember>
      getRowId={(row) => row.id}
      data={MOCK_MEMBERS.slice(0, 8)}
      columns={defaultColumns}
    />
  ),
};

/** Table with summary-mode footer showing "Showing X~Y of Z" and list pagination. */
export const WithSummaryFooter: Story = {
  render: () => (
    <DataTable<TeamMember>
      getRowId={(row) => row.id}
      data={MOCK_MEMBERS}
      columns={defaultColumns}
      pageSize={5}
      footer={{ mode: "summary" }}
    />
  ),
};

/** Table with selection-mode footer showing selected count and count pagination. */
export const WithSelectionFooter: Story = {
  render: () => (
    <DataTable<TeamMember>
      getRowId={(row) => row.id}
      data={MOCK_MEMBERS}
      columns={defaultColumns}
      pageSize={5}
      footer={{ mode: "selection" }}
    />
  ),
};

/** Table with initial sorting applied to the "name" column. */
export const WithInitialSorting: Story = {
  render: () => (
    <DataTable<TeamMember>
      getRowId={(row) => row.id}
      data={MOCK_MEMBERS}
      columns={defaultColumns}
      pageSize={5}
      footer={{ mode: "summary" }}
      initialSorting={[{ id: "name", desc: false }]}
    />
  ),
};

/** Table with some columns hidden by default via initialColumnVisibility. */
export const WithHiddenColumns: Story = {
  render: () => (
    <DataTable<TeamMember>
      getRowId={(row) => row.id}
      data={MOCK_MEMBERS.slice(0, 8)}
      columns={defaultColumns}
      initialColumnVisibility={{ email: false, lastActive: false }}
    />
  ),
};

/** Empty table with no data rows. */
export const EmptyState: Story = {
  render: () => (
    <DataTable<TeamMember>
      getRowId={(row) => row.id}
      data={[]}
      columns={defaultColumns}
      footer={{ mode: "summary" }}
    />
  ),
};

/** Small size variant with denser spacing. */
export const SmallSize: Story = {
  render: () => (
    <DataTable<TeamMember>
      getRowId={(row) => row.id}
      data={MOCK_MEMBERS.slice(0, 6)}
      columns={defaultColumns}
      size="small"
      footer={{ mode: "summary" }}
      pageSize={5}
    />
  ),
};

/** Table without actions column (no sorting/visibility popovers). */
export const WithoutActions: Story = {
  render: () => (
    <DataTable<TeamMember>
      getRowId={(row) => row.id}
      data={MOCK_MEMBERS.slice(0, 8)}
      columns={columnsWithoutActions}
    />
  ),
};

/** Table with a fixed max height and sticky header for scrollable content. */
export const ScrollableFixedHeight: Story = {
  render: () => (
    <DataTable<TeamMember>
      getRowId={(row) => row.id}
      data={MOCK_MEMBERS}
      columns={defaultColumns}
      height={300}
      headerBackground="var(--background-neutral-00)"
      pageSize={Infinity}
    />
  ),
};

/** Table with onRowClick handler instead of default selection toggle. */
export const WithRowClick: Story = {
  render: () => {
    function Demo() {
      const [clicked, setClicked] = React.useState<string | null>(null);
      return (
        <div>
          <DataTable<TeamMember>
            getRowId={(row) => row.id}
            data={MOCK_MEMBERS.slice(0, 5)}
            columns={defaultColumns}
            onRowClick={(row) => setClicked(row.name)}
          />
          {clicked && (
            <Text mainUiBody text03 className="p-4">
              Clicked: {clicked}
            </Text>
          )}
        </div>
      );
    }
    return <Demo />;
  },
};
