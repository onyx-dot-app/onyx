import type { Meta, StoryObj } from "@storybook/react-vite";
import AreaChart from "./AreaChart";

const meta: Meta<typeof AreaChart> = {
  title: "refresh-components/AreaChart",
  component: AreaChart,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof AreaChart>;

const DAILY_DATA = [
  { Day: "2026-08-01", Queries: 12, "Unique Users": 4 },
  { Day: "2026-08-02", Queries: 18, "Unique Users": 6 },
  { Day: "2026-08-03", Queries: 9, "Unique Users": 3 },
  { Day: "2026-08-04", Queries: 24, "Unique Users": 8 },
  { Day: "2026-08-05", Queries: 21, "Unique Users": 7 },
];

export const TwoSeries: Story = {
  args: {
    data: DAILY_DATA,
    categories: ["Queries", "Unique Users"],
    index: "Day",
    yAxisWidth: 60,
  },
};

export const Stacked: Story = {
  args: {
    ...TwoSeries.args,
    stacked: true,
  },
};

export const SingleSeries: Story = {
  args: {
    data: DAILY_DATA,
    categories: ["Queries"],
    index: "Day",
    allowDecimals: false,
  },
};

export const Empty: Story = {
  args: {
    data: [],
    categories: ["Queries"],
    index: "Day",
  },
};
