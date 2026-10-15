import type { Meta, StoryObj } from "@storybook/react-vite";
import { SvgProgressRing } from "@opal/icons";
import type { SvgProgressRingProps } from "@opal/icons/progress-ring";

const meta: Meta<typeof SvgProgressRing> = {
  title: "opal/icons/SvgProgressRing",
  component: SvgProgressRing,
  tags: ["autodocs"],
  args: { size: 32, success: 3, error: 1, warning: 1, neutral: 1, rest: 2 },
};

export default meta;
type Story = StoryObj<typeof SvgProgressRing>;

export const Default: Story = {};

const EXAMPLES: Array<{ label: string; props: SvgProgressRingProps }> = [
  {
    label: "every part",
    props: { success: 3, error: 1, warning: 1, neutral: 1, rest: 2 },
  },
  { label: "all success", props: { success: 5 } },
  { label: "4 success, 1 error", props: { success: 4, error: 1 } },
  { label: "3 success, 1 warning", props: { success: 3, warning: 1 } },
  {
    label: "2 success, 1 neutral, 2 rest",
    props: { success: 2, neutral: 1, rest: 2 },
  },
  { label: "1 of 12 success", props: { success: 1, rest: 11 } },
  { label: "only rest: the spinner", props: { rest: 3 } },
  { label: "all zero: full success", props: {} },
];

// Each case at the common icon sizes.
export const Examples: Story = {
  render: () => (
    <div className="flex flex-col gap-4">
      {EXAMPLES.map(({ label, props }) => (
        <div key={label} className="flex items-center gap-4">
          {[16, 20, 32].map((size) => (
            <SvgProgressRing key={size} size={size} {...props} />
          ))}
          <span className="font-secondary-body text-text-03">{label}</span>
        </div>
      ))}
    </div>
  ),
};
