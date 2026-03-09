import type { Meta, StoryObj } from "@storybook/react";
import { Hoverable } from "@opal/core";
import SvgX from "@opal/icons/x";

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------

const cardStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: "1rem",
  padding: "0.75rem 1rem",
  borderRadius: "0.5rem",
  border: "1px solid var(--border-02)",
  background: "var(--background-neutral-01)",
  minWidth: 220,
};

const labelStyle: React.CSSProperties = {
  fontSize: "0.875rem",
  fontWeight: 500,
};

// ---------------------------------------------------------------------------
// Meta
// ---------------------------------------------------------------------------

const meta: Meta = {
  title: "Core/Hoverable",
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;

// ---------------------------------------------------------------------------
// Stories
// ---------------------------------------------------------------------------

/**
 * Local hover mode -- no `group` prop on the Item.
 * The icon only appears when you hover directly over the Item element itself.
 */
export const LocalHover: StoryObj = {
  render: () => (
    <div style={cardStyle}>
      <span style={labelStyle}>Hover this card area</span>

      <Hoverable.Item variant="opacity-on-hover">
        <SvgX width={16} height={16} />
      </Hoverable.Item>
    </div>
  ),
};

/**
 * Group hover mode -- hovering anywhere inside the Root reveals the Item.
 */
export const GroupHover: StoryObj = {
  render: () => (
    <Hoverable.Root group="card">
      <div style={cardStyle}>
        <span style={labelStyle}>Hover anywhere on this card</span>

        <Hoverable.Item group="card" variant="opacity-on-hover">
          <SvgX width={16} height={16} />
        </Hoverable.Item>
      </div>
    </Hoverable.Root>
  ),
};

/**
 * Nested groups demonstrating isolation.
 *
 * - Hovering the outer card reveals only the outer icon.
 * - Hovering the inner card reveals only the inner icon.
 */
export const NestedGroups: StoryObj = {
  render: () => (
    <Hoverable.Root group="outer">
      <div
        style={{
          ...cardStyle,
          flexDirection: "column",
          alignItems: "stretch",
          gap: "0.75rem",
          padding: "1rem",
          minWidth: 300,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span style={labelStyle}>Outer card</span>

          <Hoverable.Item group="outer" variant="opacity-on-hover">
            <SvgX width={16} height={16} />
          </Hoverable.Item>
        </div>

        <Hoverable.Root group="inner">
          <div
            style={{
              ...cardStyle,
              background: "var(--background-neutral-02)",
            }}
          >
            <span style={labelStyle}>Inner card</span>

            <Hoverable.Item group="inner" variant="opacity-on-hover">
              <SvgX width={16} height={16} />
            </Hoverable.Item>
          </div>
        </Hoverable.Root>
      </div>
    </Hoverable.Root>
  ),
};
