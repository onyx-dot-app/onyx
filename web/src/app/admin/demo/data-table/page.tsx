"use client";
"use no memo";

import { useState } from "react";
import { Content } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import DataTable from "@/refresh-components/table/DataTable";
import { createTableColumns } from "@/refresh-components/table/columns";
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
// Column definitions (module scope — stable reference)
// ---------------------------------------------------------------------------

const tc = createTableColumns<TeamMember>();

const columns = [
  tc.qualifier({ content: "avatar-user", getInitials: (r) => r.initials }),
  tc.column("name", {
    header: "Name",
    weight: 200,
    minWidth: 120,
    cell: (value) => (
      <Content sizePreset="main-ui" variant="body" title={value} />
    ),
  }),
  tc.column("email", {
    header: "Email",
    weight: 240,
    minWidth: 150,
    cell: (value) => (
      <Content
        sizePreset="main-ui"
        variant="body"
        title={value}
        prominence="muted"
      />
    ),
  }),
  tc.column("role", {
    header: "Role",
    weight: 140,
    minWidth: 80,
    cell: (value) => (
      <Content sizePreset="main-ui" variant="body" title={value} />
    ),
  }),
  tc.column("department", {
    header: "Department",
    weight: 160,
    minWidth: 100,
    cell: (value) => (
      <Content sizePreset="main-ui" variant="body" title={value} />
    ),
  }),
  tc.column("status", {
    header: "Status",
    weight: 120,
    minWidth: 80,
    cell: (value) => {
      const { icon } = STATUS_CONFIG[value];
      return (
        <Content
          sizePreset="main-ui"
          variant="body"
          icon={icon}
          title={value.charAt(0).toUpperCase() + value.slice(1)}
        />
      );
    },
  }),
  tc.actions({
    sortingFooterText:
      "Everyone in your organization will see the explore agents list in this order.",
  }),
];

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

const PAGE_SIZE = 10;

export default function DataTableDemoPage() {
  const [items, setItems] = useState(DATA);

  return (
    <div className="p-6 space-y-8">
      <div className="flex flex-col space-y-4">
        <Text headingH2>Data Table Demo</Text>
        <Text mainContentMuted text03>
          Demonstrates Onyx table primitives wired to TanStack Table with
          sorting, column resizing, row selection, and pagination.
        </Text>
      </div>

      <DataTable
        data={items}
        columns={columns}
        pageSize={PAGE_SIZE}
        initialColumnVisibility={{ department: false }}
        draggable={{
          getRowId: (row) => row.id,
          onReorder: (ids, changedOrders) => {
            setItems(ids.map((id) => items.find((r) => r.id === id)!));
            console.log("Changed sort orders:", changedOrders);
          },
        }}
        footer={{ mode: "selection" }}
      />

      <div className="space-y-4">
        <Text headingH3>Small Variant</Text>
        <Text mainContentMuted text03>
          Same table rendered with the small size variant for denser layouts.
        </Text>
      </div>

      <div className="border border-border-01 rounded-lg overflow-hidden">
        <DataTable
          data={DATA}
          columns={columns}
          pageSize={PAGE_SIZE}
          size="small"
          initialColumnVisibility={{ department: false }}
          footer={{ mode: "selection" }}
        />
      </div>
    </div>
  );
}
