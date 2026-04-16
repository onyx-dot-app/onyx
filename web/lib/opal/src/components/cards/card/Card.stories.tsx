import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";
import { Card } from "@opal/components";

const BACKGROUND_VARIANTS = ["none", "light", "heavy"] as const;
const BORDER_VARIANTS = ["none", "dashed", "solid"] as const;
const PADDING_VARIANTS = ["fit", "2xs", "xs", "sm", "md", "lg"] as const;
const ROUNDING_VARIANTS = ["xs", "sm", "md", "lg"] as const;

const meta: Meta<typeof Card> = {
  title: "opal/components/Card",
  component: Card,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Card>;

export const Default: Story = {
  render: () => (
    <Card>
      <p>
        Default card with light background, no border, sm padding, md rounding.
      </p>
    </Card>
  ),
};

export const BackgroundVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      {BACKGROUND_VARIANTS.map((bg) => (
        <Card key={bg} background={bg} border="solid">
          <p>backgroundVariant: {bg}</p>
        </Card>
      ))}
    </div>
  ),
};

export const BorderVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      {BORDER_VARIANTS.map((border) => (
        <Card key={border} border={border}>
          <p>borderVariant: {border}</p>
        </Card>
      ))}
    </div>
  ),
};

export const PaddingVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      {PADDING_VARIANTS.map((padding) => (
        <Card key={padding} padding={padding} border="solid">
          <p>paddingVariant: {padding}</p>
        </Card>
      ))}
    </div>
  ),
};

export const RoundingVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      {ROUNDING_VARIANTS.map((rounding) => (
        <Card key={rounding} rounding={rounding} border="solid">
          <p>roundingVariant: {rounding}</p>
        </Card>
      ))}
    </div>
  ),
};

export const AllCombinations: Story = {
  render: () => (
    <div className="flex flex-col gap-8">
      {PADDING_VARIANTS.map((padding) => (
        <div key={padding}>
          <p className="font-bold pb-2">paddingVariant: {padding}</p>
          <div className="grid grid-cols-3 gap-4">
            {BACKGROUND_VARIANTS.map((bg) =>
              BORDER_VARIANTS.map((border) => (
                <Card
                  key={`${padding}-${bg}-${border}`}
                  padding={padding}
                  background={bg}
                  border={border}
                >
                  <p className="text-xs">
                    bg: {bg}, border: {border}
                  </p>
                </Card>
              ))
            )}
          </div>
        </div>
      ))}
    </div>
  ),
};

// ─── Expandable mode ─────────────────────────────────────────────────────────

export const Expandable: Story = {
  render: function ExpandableStory() {
    const [open, setOpen] = useState(false);
    return (
      <div className="w-96">
        <Card
          expandable
          expanded={open}
          border="solid"
          content={
            <div className="flex flex-col gap-2">
              <p>First model</p>
              <p>Second model</p>
              <p>Third model</p>
            </div>
          }
        >
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="w-full text-left"
          >
            Toggle (expanded={String(open)})
          </button>
        </Card>
      </div>
    );
  },
};

export const ExpandableNoContent: Story = {
  render: function ExpandableNoContentStory() {
    const [open, setOpen] = useState(false);
    return (
      <div className="w-96">
        <Card expandable expanded={open} border="solid" content={undefined}>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="w-full text-left"
          >
            Toggle (no content — renders like a plain card)
          </button>
        </Card>
      </div>
    );
  },
};

export const ExpandableRoundingVariants: Story = {
  render: function ExpandableRoundingStory() {
    const [openKey, setOpenKey] =
      useState<(typeof ROUNDING_VARIANTS)[number]>("md");
    return (
      <div className="flex flex-col gap-4 w-96">
        {ROUNDING_VARIANTS.map((rounding) => (
          <Card
            key={rounding}
            expandable
            expanded={openKey === rounding}
            rounding={rounding}
            border="solid"
            content={<p>content for rounding={rounding}</p>}
          >
            <button
              type="button"
              onClick={() => setOpenKey(rounding)}
              className="w-full text-left"
            >
              rounding={rounding} (click to expand)
            </button>
          </Card>
        ))}
      </div>
    );
  },
};
