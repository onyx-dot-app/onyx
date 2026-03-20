import type { Meta, StoryObj } from "@storybook/react";
import { Table, createTableColumns } from "@opal/components";

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

interface User {
  id: string;
  email: string;
  name: string;
  role: "admin" | "user" | "viewer";
  status: "active" | "invited" | "inactive";
}

const USERS: User[] = [
  {
    id: "1",
    email: "alice@example.com",
    name: "Alice Johnson",
    role: "admin",
    status: "active",
  },
  {
    id: "2",
    email: "bob@example.com",
    name: "Bob Smith",
    role: "user",
    status: "active",
  },
  {
    id: "3",
    email: "carol@example.com",
    name: "Carol White",
    role: "viewer",
    status: "invited",
  },
  {
    id: "4",
    email: "dave@example.com",
    name: "Dave Brown",
    role: "user",
    status: "inactive",
  },
  {
    id: "5",
    email: "eve@example.com",
    name: "Eve Davis",
    role: "admin",
    status: "active",
  },
  {
    id: "6",
    email: "frank@example.com",
    name: "Frank Miller",
    role: "viewer",
    status: "active",
  },
  {
    id: "7",
    email: "grace@example.com",
    name: "Grace Lee",
    role: "user",
    status: "invited",
  },
  {
    id: "8",
    email: "hank@example.com",
    name: "Hank Wilson",
    role: "user",
    status: "active",
  },
  {
    id: "9",
    email: "iris@example.com",
    name: "Iris Taylor",
    role: "viewer",
    status: "active",
  },
  {
    id: "10",
    email: "jack@example.com",
    name: "Jack Moore",
    role: "admin",
    status: "active",
  },
  {
    id: "11",
    email: "kate@example.com",
    name: "Kate Anderson",
    role: "user",
    status: "inactive",
  },
  {
    id: "12",
    email: "leo@example.com",
    name: "Leo Thomas",
    role: "viewer",
    status: "active",
  },
];

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

const tc = createTableColumns<User>();

const columns = [
  tc.qualifier({
    content: "avatar-user",
    getInitials: (r) =>
      r.name
        .split(" ")
        .map((n) => n[0])
        .join(""),
  }),
  tc.column("name", { header: "Name", weight: 25, minWidth: 120 }),
  tc.column("email", { header: "Email", weight: 30, minWidth: 160 }),
  tc.column("role", { header: "Role", weight: 15, minWidth: 80 }),
  tc.column("status", { header: "Status", weight: 15, minWidth: 80 }),
  tc.actions(),
];

// ---------------------------------------------------------------------------
// Story
// ---------------------------------------------------------------------------

const meta: Meta<typeof Table> = {
  title: "opal/components/Table",
  component: Table,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Table>;

export const Default: Story = {
  render: () => (
    <Table
      data={USERS}
      columns={columns}
      getRowId={(r) => r.id}
      pageSize={8}
      footer={{ mode: "summary" }}
    />
  ),
};
