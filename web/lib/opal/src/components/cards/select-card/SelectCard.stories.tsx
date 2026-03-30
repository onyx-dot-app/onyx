import type { Meta, StoryObj } from "@storybook/react";
import { SelectCard } from "@opal/components";
import { Button } from "@opal/components";
import { Content } from "@opal/layouts";
import {
  SvgArrowExchange,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgGlobe,
  SvgSettings,
  SvgUnplug,
} from "@opal/icons";
import { Interactive } from "@opal/core";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { Decorator } from "@storybook/react";

const withTooltipProvider: Decorator = (Story) => (
  <TooltipPrimitive.Provider>
    <Story />
  </TooltipPrimitive.Provider>
);

const STATES = ["empty", "filled", "selected"] as const;
const SIZE_VARIANTS = ["lg", "md", "sm", "xs", "2xs", "fit"] as const;

const meta = {
  title: "opal/components/SelectCard",
  component: SelectCard,
  tags: ["autodocs"],
  decorators: [withTooltipProvider],
  parameters: {
    layout: "centered",
  },
} satisfies Meta<typeof SelectCard>;

export default meta;

type Story = StoryObj<typeof meta>;

// ---------------------------------------------------------------------------
// Stories
// ---------------------------------------------------------------------------

export const Default: Story = {
  render: () => (
    <div className="w-96">
      <SelectCard variant="select-card" state="empty">
        <div className="p-2">
          <Content
            sizePreset="main-ui"
            variant="section"
            icon={SvgGlobe}
            title="Google Search"
            description="Web search provider"
          />
        </div>
      </SelectCard>
    </div>
  ),
};

export const AllStates: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      {STATES.map((state) => (
        <SelectCard key={state} variant="select-card" state={state}>
          <div className="p-2">
            <Content
              sizePreset="main-ui"
              variant="section"
              icon={SvgGlobe}
              title={`State: ${state}`}
              description="Hover to see interaction states."
            />
          </div>
        </SelectCard>
      ))}
    </div>
  ),
};

export const Clickable: Story = {
  render: () => (
    <div className="w-96">
      <SelectCard
        variant="select-card"
        state="empty"
        onClick={() => alert("Card clicked")}
      >
        <div className="p-2">
          <Content
            sizePreset="main-ui"
            variant="section"
            icon={SvgGlobe}
            title="Clickable Card"
            description="Click anywhere on this card."
          />
        </div>
      </SelectCard>
    </div>
  ),
};

export const WithActions: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-[28rem]">
      {/* Disconnected */}
      <SelectCard variant="select-card" state="empty" onClick={() => {}}>
        <div className="flex flex-row items-stretch w-full">
          <div className="flex-1 p-2">
            <Content
              sizePreset="main-ui"
              variant="section"
              icon={SvgGlobe}
              title="Disconnected"
              description="Click to connect."
            />
          </div>
          <div className="flex items-center">
            <Button prominence="tertiary" rightIcon={SvgArrowExchange}>
              Connect
            </Button>
          </div>
        </div>
      </SelectCard>

      {/* Connected with foldable */}
      <SelectCard variant="select-card" state="filled">
        <div className="flex flex-row items-stretch w-full">
          <div className="flex-1 p-2">
            <Content
              sizePreset="main-ui"
              variant="section"
              icon={SvgGlobe}
              title="Connected"
              description="Hover to reveal Set as Default."
            />
          </div>
          <div className="flex flex-col items-end justify-between">
            <div className="interactive-foldable-host flex items-center">
              <Interactive.Foldable>
                <Button prominence="tertiary" rightIcon={SvgArrowRightCircle}>
                  Set as Default
                </Button>
              </Interactive.Foldable>
            </div>
            <div className="flex flex-row px-1 pb-1">
              <Button
                icon={SvgUnplug}
                tooltip="Disconnect"
                prominence="tertiary"
                size="sm"
              />
              <Button
                icon={SvgSettings}
                tooltip="Edit"
                prominence="tertiary"
                size="sm"
              />
            </div>
          </div>
        </div>
      </SelectCard>

      {/* Selected */}
      <SelectCard variant="select-card" state="selected">
        <div className="flex flex-row items-stretch w-full">
          <div className="flex-1 p-2">
            <Content
              sizePreset="main-ui"
              variant="section"
              icon={SvgGlobe}
              title="Selected"
              description="Currently the default provider."
            />
          </div>
          <div className="flex flex-col items-end justify-between">
            <Button
              variant="action"
              prominence="tertiary"
              icon={SvgCheckSquare}
            >
              Current Default
            </Button>
            <div className="flex flex-row px-1 pb-1">
              <Button
                icon={SvgUnplug}
                tooltip="Disconnect"
                prominence="tertiary"
                size="sm"
              />
              <Button
                icon={SvgSettings}
                tooltip="Edit"
                prominence="tertiary"
                size="sm"
              />
            </div>
          </div>
        </div>
      </SelectCard>
    </div>
  ),
};

export const SizeVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      {SIZE_VARIANTS.map((size) => (
        <SelectCard
          key={size}
          variant="select-card"
          state="filled"
          sizeVariant={size}
        >
          <Content
            sizePreset="main-ui"
            variant="section"
            icon={SvgGlobe}
            title={`sizeVariant: ${size}`}
            description="Shows padding and rounding differences."
          />
        </SelectCard>
      ))}
    </div>
  ),
};

export const SelectHeavyVariant: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      {STATES.map((state) => (
        <SelectCard key={state} variant="select-heavy" state={state}>
          <div className="p-2">
            <Content
              sizePreset="main-ui"
              variant="section"
              icon={SvgGlobe}
              title={`select-heavy / ${state}`}
              description="For comparison with select-card variant."
            />
          </div>
        </SelectCard>
      ))}
    </div>
  ),
};
