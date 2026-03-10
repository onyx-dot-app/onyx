import type { Meta, StoryObj } from "@storybook/react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import Table from "./Table";
import TableHeader from "./TableHeader";
import TableBody from "./TableBody";
import TableRow from "./TableRow";
import TableHead from "./TableHead";
import TableCell from "./TableCell";
import { TableSizeProvider } from "./TableSizeContext";
import Text from "@/refresh-components/texts/Text";

// ---------------------------------------------------------------------------
// Meta
// ---------------------------------------------------------------------------

const meta: Meta<typeof Table> = {
  title: "refresh-components/table/Table",
  component: Table,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <TableSizeProvider size="regular">
          <div style={{ maxWidth: 800, padding: 16 }}>
            <Story />
          </div>
        </TableSizeProvider>
      </TooltipPrimitive.Provider>
    ),
  ],
  parameters: {
    layout: "padded",
  },
};

export default meta;
type Story = StoryObj<typeof Table>;

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

const connectors = [
  {
    name: "Google Drive",
    type: "Cloud Storage",
    docs: 1_240,
    status: "Active",
  },
  { name: "Confluence", type: "Wiki", docs: 856, status: "Active" },
  { name: "Slack", type: "Messaging", docs: 3_102, status: "Syncing" },
  { name: "Notion", type: "Wiki", docs: 412, status: "Paused" },
  { name: "GitHub", type: "Code", docs: 2_890, status: "Active" },
];

// ---------------------------------------------------------------------------
// Stories
// ---------------------------------------------------------------------------

/** All primitive table components composed together (Table, TableHeader, TableBody, TableRow, TableHead, TableCell). */
export const ComposedPrimitives: Story = {
  render: () => (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead width={200}>Connector</TableHead>
          <TableHead width={150}>Type</TableHead>
          <TableHead width={120} alignment="right">
            Documents
          </TableHead>
          <TableHead width={120}>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {connectors.map((c) => (
          <TableRow key={c.name}>
            <TableCell>
              <Text mainUiBody>{c.name}</Text>
            </TableCell>
            <TableCell>
              <Text mainUiMuted text03>
                {c.type}
              </Text>
            </TableCell>
            <TableCell>
              <Text mainUiMono text03>
                {c.docs.toLocaleString()}
              </Text>
            </TableCell>
            <TableCell>
              <Text mainUiBody>{c.status}</Text>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  ),
};

/** Table rows with the "table" variant (bottom border instead of rounded corners). */
export const TableVariantRows: Story = {
  render: () => (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead width={200}>Connector</TableHead>
          <TableHead width={150}>Type</TableHead>
          <TableHead width={120}>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {connectors.map((c) => (
          <TableRow key={c.name} variant="table">
            <TableCell>
              <Text mainUiBody>{c.name}</Text>
            </TableCell>
            <TableCell>
              <Text mainUiMuted text03>
                {c.type}
              </Text>
            </TableCell>
            <TableCell>
              <Text mainUiBody>{c.status}</Text>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  ),
};

/** Row with selected state highlighted. */
export const SelectedRows: Story = {
  render: () => (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead width={200}>Connector</TableHead>
          <TableHead width={150}>Type</TableHead>
          <TableHead width={120}>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {connectors.map((c, i) => (
          <TableRow key={c.name} selected={i === 1 || i === 3}>
            <TableCell>
              <Text mainUiBody>{c.name}</Text>
            </TableCell>
            <TableCell>
              <Text mainUiMuted text03>
                {c.type}
              </Text>
            </TableCell>
            <TableCell>
              <Text mainUiBody>{c.status}</Text>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  ),
};

/** Sortable table headers with sort indicators. */
export const SortableHeaders: Story = {
  render: () => (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead width={200} sorted="ascending" onSort={() => {}}>
            Connector
          </TableHead>
          <TableHead width={150} sorted="none" onSort={() => {}}>
            Type
          </TableHead>
          <TableHead width={120} sorted="descending" onSort={() => {}}>
            Documents
          </TableHead>
          <TableHead width={120}>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {connectors.map((c) => (
          <TableRow key={c.name}>
            <TableCell>
              <Text mainUiBody>{c.name}</Text>
            </TableCell>
            <TableCell>
              <Text mainUiMuted text03>
                {c.type}
              </Text>
            </TableCell>
            <TableCell>
              <Text mainUiMono text03>
                {c.docs.toLocaleString()}
              </Text>
            </TableCell>
            <TableCell>
              <Text mainUiBody>{c.status}</Text>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  ),
};

/** Small size variant with denser spacing. */
export const SmallSize: Story = {
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <TableSizeProvider size="small">
          <div style={{ maxWidth: 800, padding: 16 }}>
            <Story />
          </div>
        </TableSizeProvider>
      </TooltipPrimitive.Provider>
    ),
  ],
  render: () => (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead width={200}>Connector</TableHead>
          <TableHead width={150}>Type</TableHead>
          <TableHead width={120}>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {connectors.map((c) => (
          <TableRow key={c.name}>
            <TableCell>
              <Text secondaryBody>{c.name}</Text>
            </TableCell>
            <TableCell>
              <Text secondaryBody text03>
                {c.type}
              </Text>
            </TableCell>
            <TableCell>
              <Text secondaryBody>{c.status}</Text>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  ),
};

/** Disabled rows styling. */
export const DisabledRows: Story = {
  render: () => (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead width={200}>Connector</TableHead>
          <TableHead width={150}>Type</TableHead>
          <TableHead width={120}>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {connectors.map((c, i) => (
          <TableRow key={c.name} disabled={i === 2 || i === 4}>
            <TableCell>
              <Text mainUiBody>{c.name}</Text>
            </TableCell>
            <TableCell>
              <Text mainUiMuted text03>
                {c.type}
              </Text>
            </TableCell>
            <TableCell>
              <Text mainUiBody>{c.status}</Text>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  ),
};
