import type { Meta, StoryObj } from "@storybook/react";
import { Interactive } from "@opal/core";

// ---------------------------------------------------------------------------
// Variant / Prominence mappings for the matrix story
// ---------------------------------------------------------------------------

const VARIANT_PROMINENCE_MAP: Record<string, string[]> = {
  default: ["primary", "secondary", "tertiary", "internal"],
  action: ["primary", "secondary", "tertiary", "internal"],
  danger: ["primary", "secondary", "tertiary", "internal"],
  select: ["light", "heavy"],
  sidebar: ["light"],
  none: [],
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

/** Basic Interactive.Base + Container with text content. */
export const Default: StoryObj = {
  render: () => (
    <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
      <Interactive.Base
        variant="default"
        prominence="secondary"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Secondary</span>
        </Interactive.Container>
      </Interactive.Base>

      <Interactive.Base
        variant="default"
        prominence="primary"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Primary</span>
        </Interactive.Container>
      </Interactive.Base>

      <Interactive.Base
        variant="default"
        prominence="tertiary"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Tertiary</span>
        </Interactive.Container>
      </Interactive.Base>
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
            <Interactive.Base variant="none" onClick={() => {}}>
              <Interactive.Container border>
                <span>none (no prominence)</span>
              </Interactive.Container>
            </Interactive.Base>
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
                  <Interactive.Base
                    // Cast required because the discriminated union can't be
                    // resolved from dynamic strings at the type level.
                    {...({ variant, prominence } as any)}
                    onClick={() => {}}
                  >
                    <Interactive.Container border>
                      <span>{prominence}</span>
                    </Interactive.Container>
                  </Interactive.Base>
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
        <Interactive.Base
          key={size}
          variant="default"
          prominence="secondary"
          onClick={() => {}}
        >
          <Interactive.Container border heightVariant={size}>
            <span>{size}</span>
          </Interactive.Container>
        </Interactive.Base>
      ))}
    </div>
  ),
};

/** Container with widthVariant="full" stretching to fill its parent. */
export const WidthFull: StoryObj = {
  render: () => (
    <div style={{ width: 400 }}>
      <Interactive.Base
        variant="default"
        prominence="secondary"
        onClick={() => {}}
      >
        <Interactive.Container border widthVariant="full">
          <span>Full width container</span>
        </Interactive.Container>
      </Interactive.Base>
    </div>
  ),
};

/** All rounding variants side by side. */
export const Rounding: StoryObj = {
  render: () => (
    <div style={{ display: "flex", gap: "0.75rem" }}>
      {ROUNDING_VARIANTS.map((rounding) => (
        <Interactive.Base
          key={rounding}
          variant="default"
          prominence="secondary"
          onClick={() => {}}
        >
          <Interactive.Container border roundingVariant={rounding}>
            <span>{rounding}</span>
          </Interactive.Container>
        </Interactive.Base>
      ))}
    </div>
  ),
};

/** Disabled state prevents clicks and shows disabled styling. */
export const Disabled: StoryObj = {
  render: () => (
    <div style={{ display: "flex", gap: "0.75rem" }}>
      <Interactive.Base
        variant="default"
        prominence="secondary"
        onClick={() => {}}
        disabled
      >
        <Interactive.Container border>
          <span>Disabled</span>
        </Interactive.Container>
      </Interactive.Base>

      <Interactive.Base
        variant="default"
        prominence="secondary"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Enabled</span>
        </Interactive.Container>
      </Interactive.Base>
    </div>
  ),
};

/** Transient prop forces the hover/active visual state. */
export const Transient: StoryObj = {
  render: () => (
    <div style={{ display: "flex", gap: "0.75rem" }}>
      <Interactive.Base
        variant="default"
        prominence="secondary"
        onClick={() => {}}
        transient
      >
        <Interactive.Container border>
          <span>Forced hover</span>
        </Interactive.Container>
      </Interactive.Base>

      <Interactive.Base
        variant="default"
        prominence="secondary"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Normal</span>
        </Interactive.Container>
      </Interactive.Base>
    </div>
  ),
};

/** Container with border={true}. */
export const WithBorder: StoryObj = {
  render: () => (
    <div style={{ display: "flex", gap: "0.75rem" }}>
      <Interactive.Base
        variant="default"
        prominence="secondary"
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>With border</span>
        </Interactive.Container>
      </Interactive.Base>

      <Interactive.Base
        variant="default"
        prominence="secondary"
        onClick={() => {}}
      >
        <Interactive.Container>
          <span>Without border</span>
        </Interactive.Container>
      </Interactive.Base>
    </div>
  ),
};

/** Using href to render as a link. */
export const AsLink: StoryObj = {
  render: () => (
    <Interactive.Base variant="action" href="/settings">
      <Interactive.Container border>
        <span>Go to Settings</span>
      </Interactive.Container>
    </Interactive.Base>
  ),
};

/** Select variant with selected and unselected states. */
export const SelectVariant: StoryObj = {
  render: () => (
    <div style={{ display: "flex", gap: "0.75rem" }}>
      <Interactive.Base
        variant="select"
        prominence="light"
        selected
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Selected (light)</span>
        </Interactive.Container>
      </Interactive.Base>

      <Interactive.Base variant="select" prominence="light" onClick={() => {}}>
        <Interactive.Container border>
          <span>Unselected (light)</span>
        </Interactive.Container>
      </Interactive.Base>

      <Interactive.Base
        variant="select"
        prominence="heavy"
        selected
        onClick={() => {}}
      >
        <Interactive.Container border>
          <span>Selected (heavy)</span>
        </Interactive.Container>
      </Interactive.Base>

      <Interactive.Base variant="select" prominence="heavy" onClick={() => {}}>
        <Interactive.Container border>
          <span>Unselected (heavy)</span>
        </Interactive.Container>
      </Interactive.Base>
    </div>
  ),
};
