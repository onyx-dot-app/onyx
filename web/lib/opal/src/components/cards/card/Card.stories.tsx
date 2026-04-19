import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";
import { Button, Card } from "@opal/components";

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
          <p>padding: {padding}</p>
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
          <p>rounding: {rounding}</p>
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
          <p className="font-bold pb-2">padding: {padding}</p>
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
          expandedContent={
            <div className="flex flex-col gap-2">
              <p>First model</p>
              <p>Second model</p>
              <p>Third model</p>
            </div>
          }
        >
          <Button
            prominence="tertiary"
            width="full"
            onClick={() => setOpen((v) => !v)}
          >
            Toggle (expanded={String(open)})
          </Button>
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
        <Card expandable expanded={open} border="solid">
          <Button
            prominence="tertiary"
            width="full"
            onClick={() => setOpen((v) => !v)}
          >
            Toggle (no content — renders like a plain card)
          </Button>
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
            expandedContent={<p>content for rounding={rounding}</p>}
          >
            <Button
              prominence="tertiary"
              width="full"
              onClick={() => setOpenKey(rounding)}
            >
              rounding={rounding} (click to expand)
            </Button>
          </Card>
        ))}
      </div>
    );
  },
};
