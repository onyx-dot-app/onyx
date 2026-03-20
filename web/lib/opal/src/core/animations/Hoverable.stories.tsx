import type { Meta, StoryObj } from "@storybook/react";
import { Hoverable } from "@opal/core";

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

/** Group mode — hovering the root reveals hidden items. */
export const GroupMode: StoryObj = {
  render: () => (
    <Hoverable.Root group="demo">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.75rem",
          padding: "1rem",
          border: "1px solid var(--border-02)",
          borderRadius: "0.5rem",
          minWidth: 260,
        }}
      >
        <span style={{ color: "var(--text-01)" }}>Hover this card</span>
        <Hoverable.Item group="demo" variant="opacity-on-hover">
          <span style={{ color: "var(--text-03)" }}>✓ Revealed</span>
        </Hoverable.Item>
      </div>
    </Hoverable.Root>
  ),
};

/** Local mode — hovering the item itself reveals it (no Root needed). */
export const LocalMode: StoryObj = {
  render: () => (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.75rem",
        padding: "1rem",
      }}
    >
      <span style={{ color: "var(--text-01)" }}>Hover the icon →</span>
      <Hoverable.Item variant="opacity-on-hover">
        <span style={{ fontSize: "1.25rem" }}>🗑</span>
      </Hoverable.Item>
    </div>
  ),
};

/** Multiple independent groups on the same page. */
export const MultipleGroups: StoryObj = {
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
      {(["alpha", "beta"] as const).map((group) => (
        <Hoverable.Root key={group} group={group}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.75rem",
              padding: "1rem",
              border: "1px solid var(--border-02)",
              borderRadius: "0.5rem",
            }}
          >
            <span style={{ color: "var(--text-01)" }}>Group: {group}</span>
            <Hoverable.Item group={group} variant="opacity-on-hover">
              <span style={{ color: "var(--text-03)" }}>✓ Revealed</span>
            </Hoverable.Item>
          </div>
        </Hoverable.Root>
      ))}
    </div>
  ),
};

/** Multiple items revealed by a single root. */
export const MultipleItems: StoryObj = {
  render: () => (
    <Hoverable.Root group="multi">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.75rem",
          padding: "1rem",
          border: "1px solid var(--border-02)",
          borderRadius: "0.5rem",
        }}
      >
        <span style={{ color: "var(--text-01)" }}>Hover to reveal all</span>
        <Hoverable.Item group="multi" variant="opacity-on-hover">
          <span>Edit</span>
        </Hoverable.Item>
        <Hoverable.Item group="multi" variant="opacity-on-hover">
          <span>Delete</span>
        </Hoverable.Item>
        <Hoverable.Item group="multi" variant="opacity-on-hover">
          <span>Share</span>
        </Hoverable.Item>
      </div>
    </Hoverable.Root>
  ),
};

/** Nested groups — inner and outer hover independently. */
export const NestedGroups: StoryObj = {
  render: () => (
    <Hoverable.Root group="outer">
      <div
        style={{
          padding: "1rem",
          border: "1px solid var(--border-02)",
          borderRadius: "0.5rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.75rem",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <span style={{ color: "var(--text-01)" }}>Outer card</span>
          <Hoverable.Item group="outer" variant="opacity-on-hover">
            <span style={{ color: "var(--text-03)" }}>Outer action</span>
          </Hoverable.Item>
        </div>

        <Hoverable.Root group="inner">
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.75rem",
              padding: "0.75rem",
              border: "1px solid var(--border-03)",
              borderRadius: "0.375rem",
            }}
          >
            <span style={{ color: "var(--text-02)" }}>Inner card</span>
            <Hoverable.Item group="inner" variant="opacity-on-hover">
              <span style={{ color: "var(--text-03)" }}>Inner action</span>
            </Hoverable.Item>
          </div>
        </Hoverable.Root>
      </div>
    </Hoverable.Root>
  ),
};
