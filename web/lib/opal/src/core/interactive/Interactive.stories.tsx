import type { Meta, StoryObj } from "@storybook/react";
import { Interactive, Disabled } from "@opal/core";

// ---------------------------------------------------------------------------
// Variant / Prominence mappings for the matrix story
// ---------------------------------------------------------------------------

const VARIANT_PROMINENCE_MAP: Record<string, string[]> = {
  default: ["primary", "secondary", "tertiary", "internal"],
  action: ["primary", "secondary", "tertiary", "internal"],
  danger: ["primary", "secondary", "tertiary", "internal"],
};

const SIZE_VARIANTS = ["lg", "md", "sm", "xs", "2xs", "fit"] as const;
const ROUNDING_VARIANTS = ["default", "compact", "mini"] as const;

// ---------------------------------------------------------------------------
// Meta
// ---------------------------------------------------------------------------

const meta: Meta = {
  title: "Core/Interactive",
  tags: ["autodocs"],
  parameters: {
    layout: "centered",
  },
};

export default meta;

// ---------------------------------------------------------------------------
// Stories
// ---------------------------------------------------------------------------

/** Basic Interactive.Stateless + Container with text content. */
export const Default: StoryObj = {
  render: () => (
    <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
      <Interactive.Stateless
        variant="default"
        prominence="secondary"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Secondary</span>
        </Interactive.Container>
      </Interactive.Stateless>

      <Interactive.Stateless
        variant="default"
        prominence="primary"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Primary</span>
        </Interactive.Container>
      </Interactive.Stateless>

      <Interactive.Stateless
        variant="default"
        prominence="tertiary"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Tertiary</span>
        </Interactive.Container>
      </Interactive.Stateless>
    </div>
  ),
};

/** All variant x prominence combinations displayed in a grid. */
export const VariantMatrix: StoryObj = {
  render: () => (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.5rem" }}>
      {Object.entries(VARIANT_PROMINENCE_MAP).map(([variant, prominences]) => (
        <div key={variant}>
          <div
            style={{
              fontSize: "0.75rem",
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              paddingBottom: "0.5rem",
            }}
          >
            {variant}
          </div>

          {prominences.length === 0 ? (
            <Interactive.Stateless variant="none" onClick={() => {}}>
              <Interactive.Container border>
                <span style={{ color: "var(--text-01)" }}>
                  none (no prominence)
                </span>
              </Interactive.Container>
            </Interactive.Stateless>
          ) : (
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              {prominences.map((prominence) => (
                <div
                  key={prominence}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    gap: "0.25rem",
                  }}
                >
                  <Interactive.Stateless
                    // Cast required because the discriminated union can't be
                    // resolved from dynamic strings at the type level.
                    {...({ variant, prominence } as any)}
                    onClick={() => {}}
                  >
                    <Interactive.Container border>
                      <span>{prominence}</span>
                    </Interactive.Container>
                  </Interactive.Stateless>
                  <span
                    style={{
                      fontSize: "0.625rem",
                      opacity: 0.6,
                    }}
                  >
                    {prominence}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  ),
};

/** All heightVariant sizes (lg, md, sm, xs, 2xs, fit). */
export const Sizes: StoryObj = {
  render: () => (
    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
      {SIZE_VARIANTS.map((size) => (
        <Interactive.Stateless
          key={size}
          variant="default"
          prominence="secondary"
          onClick={() => {}}
        >
          <Interactive.Container border heightVariant={size}>
            <span>{size}</span>
          </Interactive.Container>
        </Interactive.Stateless>
      ))}
    </div>
  ),
};

/** Container with widthVariant="full" stretching to fill its parent. */
export const WidthFull: StoryObj = {
  render: () => (
    <div style={{ width: 400 }}>
      <Interactive.Stateless
        variant="default"
        prominence="secondary"
        onClick={() => {}}
      >
        <Interactive.Container border widthVariant="full">
          <span>Full width container</span>
        </Interactive.Container>
      </Interactive.Stateless>
    </div>
  ),
};

/** All rounding variants side by side. */
export const Rounding: StoryObj = {
  render: () => (
    <div style={{ display: "flex", gap: "0.75rem" }}>
      {ROUNDING_VARIANTS.map((rounding) => (
        <Interactive.Stateless
          key={rounding}
          variant="default"
          prominence="secondary"
          onClick={() => {}}
        >
          <Interactive.Container border roundingVariant={rounding}>
            <span>{rounding}</span>
          </Interactive.Container>
        </Interactive.Stateless>
      ))}
    </div>
  ),
};

/** Disabled state prevents clicks and shows disabled styling. */
export const DisabledStory: StoryObj = {
  name: "Disabled",
  render: () => (
    <div style={{ display: "flex", gap: "0.75rem" }}>
      <Disabled disabled>
        <Interactive.Stateless
          variant="default"
          prominence="secondary"
          onClick={() => {}}
        >
          <Interactive.Container border>
            <span>Disabled</span>
          </Interactive.Container>
        </Interactive.Stateless>
      </Disabled>

      <Interactive.Stateless
        variant="default"
        prominence="secondary"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Enabled</span>
        </Interactive.Container>
      </Interactive.Stateless>
    </div>
  ),
};

/** Interaction override forces the hover/active visual state. */
export const Interaction: StoryObj = {
  render: () => (
    <div style={{ display: "flex", gap: "0.75rem" }}>
      <Interactive.Stateless
        variant="default"
        prominence="secondary"
        interaction="hover"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Forced hover</span>
        </Interactive.Container>
      </Interactive.Stateless>

      <Interactive.Stateless
        variant="default"
        prominence="secondary"
        interaction="active"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Forced active</span>
        </Interactive.Container>
      </Interactive.Stateless>

      <Interactive.Stateless
        variant="default"
        prominence="secondary"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Normal (rest)</span>
        </Interactive.Container>
      </Interactive.Stateless>
    </div>
  ),
};

/** Container with border={true}. */
export const WithBorder: StoryObj = {
  render: () => (
    <div style={{ display: "flex", gap: "0.75rem" }}>
      <Interactive.Stateless
        variant="default"
        prominence="secondary"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>With border</span>
        </Interactive.Container>
      </Interactive.Stateless>

      <Interactive.Stateless
        variant="default"
        prominence="secondary"
        onClick={() => {}}
      >
        <Interactive.Container>
          <span>Without border</span>
        </Interactive.Container>
      </Interactive.Stateless>
    </div>
  ),
};

/** Using href to render as a link. */
export const AsLink: StoryObj = {
  render: () => (
    <Interactive.Stateless variant="action" href="/settings">
      <Interactive.Container border>
        <span>Go to Settings</span>
      </Interactive.Container>
    </Interactive.Stateless>
  ),
};

/** Stateful select variant with selected and unselected states. */
export const SelectVariant: StoryObj = {
  render: () => (
    <div style={{ display: "flex", gap: "0.75rem" }}>
      <Interactive.Stateful
        variant="select-light"
        state="selected"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Selected (light)</span>
        </Interactive.Container>
      </Interactive.Stateful>

      <Interactive.Stateful
        variant="select-light"
        state="empty"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Unselected (light)</span>
        </Interactive.Container>
      </Interactive.Stateful>

      <Interactive.Stateful
        variant="select-heavy"
        state="selected"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Selected (heavy)</span>
        </Interactive.Container>
      </Interactive.Stateful>

      <Interactive.Stateful
        variant="select-heavy"
        state="empty"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Unselected (heavy)</span>
        </Interactive.Container>
      </Interactive.Stateful>
    </div>
  ),
};
