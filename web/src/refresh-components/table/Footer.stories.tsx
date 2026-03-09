import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import Footer from "./Footer";
import { TableSizeProvider } from "./TableSizeContext";

const meta: Meta<typeof Footer> = {
  title: "refresh-components/table/Footer",
  component: Footer,
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
type Story = StoryObj<typeof Footer>;

// ---------------------------------------------------------------------------
// Stories
// ---------------------------------------------------------------------------

/** Summary mode footer showing "Showing X~Y of Z" with list pagination. */
export const SummaryMode: Story = {
  render: function SummaryModeStory() {
    const [page, setPage] = React.useState(1);
    return (
      <Footer
        mode="summary"
        rangeStart={(page - 1) * 10 + 1}
        rangeEnd={Math.min(page * 10, 47)}
        totalItems={47}
        currentPage={page}
        totalPages={5}
        onPageChange={setPage}
      />
    );
  },
};

/** Summary mode on the last page. */
export const SummaryLastPage: Story = {
  render: function SummaryLastPageStory() {
    const [page, setPage] = React.useState(5);
    return (
      <Footer
        mode="summary"
        rangeStart={(page - 1) * 10 + 1}
        rangeEnd={Math.min(page * 10, 47)}
        totalItems={47}
        currentPage={page}
        totalPages={5}
        onPageChange={setPage}
      />
    );
  },
};

/** Selection mode with no items selected. */
export const SelectionNone: Story = {
  render: function SelectionNoneStory() {
    const [page, setPage] = React.useState(1);
    return (
      <Footer
        mode="selection"
        multiSelect
        selectionState="none"
        selectedCount={0}
        onClear={() => {}}
        pageSize={10}
        totalItems={47}
        currentPage={page}
        totalPages={5}
        onPageChange={setPage}
      />
    );
  },
};

/** Selection mode with some items selected. */
export const SelectionPartial: Story = {
  render: function SelectionPartialStory() {
    const [page, setPage] = React.useState(1);
    return (
      <Footer
        mode="selection"
        multiSelect
        selectionState="partial"
        selectedCount={3}
        onView={() => alert("View selected")}
        onClear={() => alert("Clear selection")}
        pageSize={10}
        totalItems={47}
        currentPage={page}
        totalPages={5}
        onPageChange={setPage}
      />
    );
  },
};

/** Selection mode with all items selected. */
export const SelectionAll: Story = {
  render: function SelectionAllStory() {
    const [page, setPage] = React.useState(1);
    return (
      <Footer
        mode="selection"
        multiSelect
        selectionState="all"
        selectedCount={10}
        onView={() => alert("View selected")}
        onClear={() => alert("Clear selection")}
        pageSize={10}
        totalItems={47}
        currentPage={page}
        totalPages={5}
        onPageChange={setPage}
      />
    );
  },
};

/** Single-select mode (no multi-select). */
export const SingleSelect: Story = {
  render: function SingleSelectStory() {
    const [page, setPage] = React.useState(1);
    return (
      <Footer
        mode="selection"
        multiSelect={false}
        selectionState="partial"
        selectedCount={1}
        onClear={() => alert("Clear selection")}
        pageSize={10}
        totalItems={47}
        currentPage={page}
        totalPages={5}
        onPageChange={setPage}
      />
    );
  },
};

/** Small size variant. */
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
  render: function SmallSizeStory() {
    const [page, setPage] = React.useState(1);
    return (
      <Footer
        mode="summary"
        rangeStart={(page - 1) * 10 + 1}
        rangeEnd={Math.min(page * 10, 47)}
        totalItems={47}
        currentPage={page}
        totalPages={5}
        onPageChange={setPage}
      />
    );
  },
};
