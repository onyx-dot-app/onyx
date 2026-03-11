import type { Meta, StoryObj } from "@storybook/react";
import { Card } from "@opal/components";

const BACKGROUND_VARIANTS = ["none", "light", "heavy"] as const;
const BORDER_VARIANTS = ["none", "dashed", "solid"] as const;
const SIZE_VARIANTS = ["lg", "md", "sm", "xs", "2xs", "fit"] as const;

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
      <p>Default card with light background, no border, lg size.</p>
    </Card>
  ),
};

export const BackgroundVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      {BACKGROUND_VARIANTS.map((bg) => (
        <Card key={bg} backgroundVariant={bg} borderVariant="solid">
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
        <Card key={border} borderVariant={border}>
          <p>borderVariant: {border}</p>
        </Card>
      ))}
    </div>
  ),
};

export const SizeVariants: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      {SIZE_VARIANTS.map((size) => (
        <Card key={size} sizeVariant={size} borderVariant="solid">
          <p>sizeVariant: {size}</p>
        </Card>
      ))}
    </div>
  ),
};

export const Combined: Story = {
  render: () => (
    <div className="flex flex-col gap-4 w-96">
      <Card backgroundVariant="heavy" borderVariant="solid" sizeVariant="sm">
        <p>Heavy background, solid border, sm size</p>
      </Card>
      <Card backgroundVariant="none" borderVariant="dashed" sizeVariant="lg">
        <p>No background, dashed border, lg size</p>
      </Card>
      <Card backgroundVariant="light" borderVariant="none" sizeVariant="xs">
        <p>Light background, no border, xs size</p>
      </Card>
    </div>
  ),
};
