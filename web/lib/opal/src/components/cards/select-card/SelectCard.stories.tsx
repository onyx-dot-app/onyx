import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
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

const STATES = ["empty", "filled", "selected"] as const;
const PADDING_VARIANTS = [0, 0.5, 1, 2, 4, 6] as const;
const ROUNDING_VARIANTS = [1, 2, 3, 4] as const;

const meta = {
  title: "opal/components/SelectCard",
  component: SelectCard,
  tags: ["autodocs"],

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
      <SelectCard state="empty">
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
        <SelectCard key={state} state={state}>
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
      <SelectCard state="empty" onClick={() => alert("Card clicked")}>
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
    <div className="flex flex-col gap-4 w-112">
      {/* Disconnected */}
      <SelectCard state="empty" onClick={() => {}}>
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
      <SelectCard state="filled">
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
      <SelectCard state="selected">
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

export const PaddingVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      {PADDING_VARIANTS.map((padding) => (
        <SelectCard key={padding} state="filled" padding={padding}>
          <Content
            sizePreset="main-ui"
            variant="section"
            icon={SvgGlobe}
            title={`padding: ${padding}`}
            description="Shows padding differences."
          />
        </SelectCard>
      ))}
    </div>
  ),
};

export const RoundingVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      {ROUNDING_VARIANTS.map((rounding) => (
        <SelectCard key={rounding} state="filled" rounding={rounding}>
          <Content
            sizePreset="main-ui"
            variant="section"
            icon={SvgGlobe}
            title={`rounding: ${rounding}`}
            description="Shows rounding differences."
          />
        </SelectCard>
      ))}
    </div>
  ),
};

/** Expandable: the header toggles, the fold holds the body. Selected while
 * open paints as `expandedState`, so no blue survives the expansion. */
export const Expandable: Story = {
  render: function ExpandableStory() {
    const [open, setOpen] = useState(false);
    return (
      <div className="w-96">
        <SelectCard
          expandable
          expanded={open}
          state={open ? "selected" : "empty"}
          onClick={() => setOpen((value) => !value)}
          expandedContent={
            <div className="p-4">
              <Content
                sizePreset="main-ui"
                variant="body"
                title="Fold body"
                description="Clicks in here belong to the body, not the card."
              />
            </div>
          }
        >
          <Content
            sizePreset="main-ui"
            variant="section"
            icon={SvgGlobe}
            title="New account"
            description="Click the header to expand."
          />
        </SelectCard>
      </div>
    );
  },
};

/** `expandableContentHeight="full"` drops the 20rem cap on the fold. */
export const ExpandableFitHeight: Story = {
  render: function ExpandableFitHeightStory() {
    const [open, setOpen] = useState(true);
    return (
      <div className="w-96">
        <SelectCard
          expandable
          expanded={open}
          expandableContentHeight="full"
          state="filled"
          onClick={() => setOpen((value) => !value)}
          expandedContent={
            <div className="flex flex-col gap-2 p-4">
              {Array.from({ length: 8 }, (_, index) => (
                <Content
                  key={index}
                  sizePreset="secondary"
                  variant="body"
                  title={`Row ${index + 1}`}
                />
              ))}
            </div>
          }
        >
          <Content
            sizePreset="main-ui"
            variant="section"
            icon={SvgGlobe}
            title="Tall body"
            description="No max-height, no scrollbar."
          />
        </SelectCard>
      </div>
    );
  },
};

/** `expandedState="empty"` keeps an open card transparent instead of filled. */
export const ExpandableStaysEmpty: Story = {
  render: function ExpandableStaysEmptyStory() {
    const [open, setOpen] = useState(true);
    return (
      <div className="w-96">
        <SelectCard
          expandable
          expanded={open}
          expandedState="empty"
          state="selected"
          onClick={() => setOpen((value) => !value)}
          expandedContent={
            <div className="p-4">
              <Content
                sizePreset="main-ui"
                variant="body"
                title="Transparent while open"
                description="Collapse it to see the selection blue come back."
              />
            </div>
          }
        >
          <Content
            sizePreset="main-ui"
            variant="section"
            icon={SvgGlobe}
            title="Selected, but open"
            description="No blue while the fold shows."
          />
        </SelectCard>
      </div>
    );
  },
};
