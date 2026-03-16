import type { Meta, StoryObj } from "@storybook/react";
import { Pagination } from "@opal/components";
import { useState } from "react";

const meta: Meta<typeof Pagination> = {
  title: "opal/components/Pagination",
  component: Pagination,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Pagination>;

// ===========================================================================
// variant="simple"
// ===========================================================================

export const Simple: Story = {
  args: {
    variant: "simple",
    currentPage: 3,
    totalPages: 10,
  },
};

export const SimpleSmall: Story = {
  args: {
    variant: "simple",
    currentPage: 2,
    totalPages: 8,
    size: "sm",
  },
};

export const SimpleWithUnits: Story = {
  args: {
    variant: "simple",
    currentPage: 1,
    totalPages: 5,
    units: "pages",
  },
};

export const SimpleArrowsOnly: Story = {
  args: {
    variant: "simple",
    currentPage: 2,
    totalPages: 8,
    showSummary: false,
  },
};

export const SimpleAllSizes: Story = {
  render: () => (
    <div className="flex flex-col gap-4 items-start">
      {(["lg", "md", "sm"] as const).map((size) => (
        <div key={size} className="flex flex-col gap-1">
          <span className="font-secondary-body text-text-03">
            size=&quot;{size}&quot;
          </span>
          <Pagination
            variant="simple"
            currentPage={3}
            totalPages={10}
            size={size}
          />
        </div>
      ))}
    </div>
  ),
};

// ===========================================================================
// variant="count"
// ===========================================================================

export const Count: Story = {
  args: {
    variant: "count",
    pageSize: 10,
    totalItems: 95,
    currentPage: 2,
    totalPages: 10,
  },
};

// ===========================================================================
// variant="list" (default)
// ===========================================================================

export const List: Story = {
  args: {
    currentPage: 5,
    totalPages: 20,
  },
};

export const ListFewPages: Story = {
  args: {
    currentPage: 2,
    totalPages: 4,
  },
};

export const ListAllSizes: Story = {
  render: () => (
    <div className="flex flex-col gap-4 items-start">
      {(["lg", "md", "sm"] as const).map((size) => (
        <div key={size} className="flex flex-col gap-1">
          <span className="font-secondary-body text-text-03">
            size=&quot;{size}&quot;
          </span>
          <Pagination
            currentPage={3}
            totalPages={10}
            onChange={() => {}}
            size={size}
          />
        </div>
      ))}
    </div>
  ),
};

// ===========================================================================
// Interactive
// ===========================================================================

function InteractiveSimpleDemo() {
  const [page, setPage] = useState(1);
  return (
    <div className="flex flex-col gap-4 items-start">
      <Pagination
        variant="simple"
        currentPage={page}
        totalPages={15}
        onArrowClick={setPage}
        units="pages"
      />
      <span className="font-secondary-body text-text-03">
        Current page: {page}
      </span>
    </div>
  );
}

export const InteractiveSimple: Story = {
  render: () => <InteractiveSimpleDemo />,
};

function InteractiveListDemo() {
  const [page, setPage] = useState(1);
  return (
    <div className="flex flex-col gap-4 items-start">
      <Pagination currentPage={page} totalPages={15} onChange={setPage} />
      <span className="font-secondary-body text-text-03">
        Current page: {page}
      </span>
    </div>
  );
}

export const InteractiveList: Story = {
  render: () => <InteractiveListDemo />,
};
