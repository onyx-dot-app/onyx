import type { Meta, StoryObj } from "@storybook/react-vite";
import { LineItemButton } from "@opal/components";
import SvgSearch from "@opal/icons/search";

const meta: Meta<typeof LineItemButton> = {
  title: "opal/components/LineItemButton",
  component: LineItemButton,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof LineItemButton>;

export const Default: Story = {
  render: () => (
    <div className="w-96">
      <LineItemButton
        icon={SvgSearch}
        title="Internal Search"
        sizePreset="main-ui"
        variant="section"
      />
    </div>
  ),
};

export const States: Story = {
  render: () => (
    <div className="flex w-96 flex-col gap-1">
      <LineItemButton
        icon={SvgSearch}
        title="Empty"
        sizePreset="main-ui"
        variant="section"
      />
      <LineItemButton
        icon={SvgSearch}
        title="Selected"
        state="selected"
        sizePreset="main-ui"
        variant="section"
      />
      <LineItemButton
        icon={SvgSearch}
        title="Disabled"
        disabled
        sizePreset="main-ui"
        variant="section"
      />
    </div>
  ),
};

/**
 * Disabled has to win over `color`, and over the description's own colour.
 *
 * `color` replaces the `"interactive"` mode `LineItemButton` passes by
 * default, and that mode is what lets the interactive colour variables reach
 * the content. Every row below is disabled: each one should read as disabled
 * — title, icon and description alike — rather than keeping the colour it has
 * when enabled. The enabled row is there to compare against.
 */
export const DisabledOutranksColor: Story = {
  render: () => (
    <div className="flex w-96 flex-col gap-1">
      <LineItemButton
        icon={SvgSearch}
        title="Enabled, muted"
        description="Reads as muted"
        color="muted"
        sizePreset="main-ui"
        variant="section"
      />
      <LineItemButton
        icon={SvgSearch}
        title="Disabled, no colour"
        description="Reads as disabled"
        disabled
        sizePreset="main-ui"
        variant="section"
      />
      <LineItemButton
        icon={SvgSearch}
        title="Disabled, muted"
        description="Reads as disabled, not muted"
        color="muted"
        disabled
        sizePreset="main-ui"
        variant="section"
      />
      <LineItemButton
        icon={SvgSearch}
        title="Disabled, danger"
        description="Reads as disabled, not danger"
        color="danger"
        disabled
        sizePreset="main-ui"
        variant="section"
      />
    </div>
  ),
};

/**
 * `color={undefined}` has to mean "no colour given", not `"default"`.
 *
 * `color={condition ? "muted" : undefined}` is the obvious way to colour a row
 * conditionally, and the falsy arm has to leave the row on the `"interactive"`
 * mode that lets the interactive colour variables through. The two rows below
 * must be indistinguishable, in every state — if the explicit `undefined` ever
 * pins the row to `"default"` again, it stops responding to selection and
 * disablement and this story shows it.
 */
export const UndefinedColorIsNoColor: Story = {
  render: () => (
    <div className="flex w-96 flex-col gap-1">
      <LineItemButton
        icon={SvgSearch}
        title="Colour omitted, selected"
        description="Baseline"
        state="selected"
        sizePreset="main-ui"
        variant="section"
      />
      <LineItemButton
        icon={SvgSearch}
        title="Colour undefined, selected"
        description="Must match the row above"
        color={undefined}
        state="selected"
        sizePreset="main-ui"
        variant="section"
      />
      <LineItemButton
        icon={SvgSearch}
        title="Colour omitted, disabled"
        description="Baseline"
        disabled
        sizePreset="main-ui"
        variant="section"
      />
      <LineItemButton
        icon={SvgSearch}
        title="Colour undefined, disabled"
        description="Must match the row above"
        color={undefined}
        disabled
        sizePreset="main-ui"
        variant="section"
      />
    </div>
  ),
};
