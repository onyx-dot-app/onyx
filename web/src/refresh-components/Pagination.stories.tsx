import React from "react";
import type { Meta, StoryObj } from "@storybook/react";
import Pagination from "./Pagination";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";

const meta: Meta<typeof Pagination> = {
  title: "refresh-components/Pagination",
  component: Pagination,
  tags: ["autodocs"],
  decorators: [
    (Story) => (
      <TooltipPrimitive.Provider>
        <Story />
      </TooltipPrimitive.Provider>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof Pagination>;

function PaginationDemo({
  totalPages,
  initialPage = 1,
}: {
  totalPages: number;
  initialPage?: number;
}) {
  const [page, setPage] = React.useState(initialPage);
  return (
    <Pagination
      currentPage={page}
      totalPages={totalPages}
      onPageChange={setPage}
    />
  );
}

export const Default: Story = {
  render: () => <PaginationDemo totalPages={10} />,
};

export const FewPages: Story = {
  render: () => <PaginationDemo totalPages={5} />,
};

export const ManyPages: Story = {
  render: () => <PaginationDemo totalPages={50} initialPage={25} />,
};

export const FirstPage: Story = {
  render: () => <PaginationDemo totalPages={20} initialPage={1} />,
};

export const LastPage: Story = {
  render: () => <PaginationDemo totalPages={20} initialPage={20} />,
};
