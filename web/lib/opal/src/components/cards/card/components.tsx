import "@opal/components/cards/shared.css";
import "@opal/components/cards/card/styles.css";
import type {
  PaddingVariants,
  RoundingVariants,
  StatusVariants,
} from "@opal/types";
import {
  paddingVariants,
  cardRoundingVariants,
  cardTopRoundingVariants,
  cardBottomRoundingVariants,
} from "@opal/shared";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type BackgroundVariant = "none" | "light" | "heavy";
type BorderVariant = "none" | "dashed" | "solid";

/**
 * Props shared by both plain and expandable Card modes.
 */
type CardBaseProps = {
  /**
   * Padding preset.
   *
   * | Value   | Class   |
   * |---------|---------|
   * | `"lg"`  | `p-6`   |
   * | `"md"`  | `p-4`   |
   * | `"sm"`  | `p-2`   |
   * | `"xs"`  | `p-1`   |
   * | `"2xs"` | `p-0.5` |
   * | `"fit"` | `p-0`   |
   *
   * In expandable mode, applied to both the header region and the content
   * body (so both slots share the same inner padding).
   *
   * @default "md"
   */
  padding?: PaddingVariants;

  /**
   * Border-radius preset.
   *
   * | Value  | Class        |
   * |--------|--------------|
   * | `"xs"` | `rounded-04` |
   * | `"sm"` | `rounded-08` |
   * | `"md"` | `rounded-12` |
   * | `"lg"` | `rounded-16` |
   *
   * In expandable mode when expanded, rounding applies only to the header's
   * top corners and the content's bottom corners so the two join seamlessly.
   * When collapsed, rounding applies to all four corners of the header.
   *
   * @default "md"
   */
  rounding?: RoundingVariants;

  /**
   * Background fill intensity.
   * - `"none"`: transparent background.
   * - `"light"`: subtle tinted background (`bg-background-tint-00`).
   * - `"heavy"`: stronger tinted background (`bg-background-tint-01`).
   *
   * @default "light"
   */
  background?: BackgroundVariant;

  /**
   * Border style.
   * - `"none"`: no border.
   * - `"dashed"`: dashed border.
   * - `"solid"`: solid border.
   *
   * @default "none"
   */
  border?: BorderVariant;

  /**
   * Border color, drawn from the same status palette as {@link MessageCard}.
   * Has no visual effect when `border="none"`.
   *
   * @default "default"
   */
  borderColor?: StatusVariants;

  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;

  /**
   * In plain mode, the card body. In expandable mode, the always-visible
   * header region (the part that stays put whether expanded or collapsed).
   */
  children?: React.ReactNode;
};

type CardPlainProps = CardBaseProps & {
  /**
   * When `false` (or omitted), renders a plain card — same behavior as before
   * this prop existed. No fold behavior, no `content` slot.
   *
   * @default false
   */
  expandable?: false;
};

type CardExpandableProps = CardBaseProps & {
  /**
   * Enables the expandable variant. Renders `children` as the always-visible
   * header and `content` as the body that animates open/closed based on
   * `expanded`.
   */
  expandable: true;

  /**
   * Controlled expanded state. The caller owns the state and any trigger
   * (click-to-toggle) — Card is purely visual and never mutates this value.
   *
   * @default false
   */
  expanded?: boolean;

  /**
   * The expandable body. Rendered below the header, animating open/closed
   * when `expanded` changes. If `undefined`, the card behaves visually like
   * a plain card (no divider, no bottom slot).
   */
  content?: React.ReactNode;
};

type CardProps = CardPlainProps | CardExpandableProps;

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------

/**
 * A container with configurable background, border, padding, and rounding.
 *
 * Has two mutually-exclusive modes:
 *
 * - **Plain** (default): renders `children` inside a single styled `<div>`.
 *   Same shape as the original Card.
 *
 * - **Expandable** (`expandable: true`): renders `children` as the header
 *   region and the `content` prop as an animating body below. Fold state is
 *   fully controlled via the `expanded` prop — Card does not own state and
 *   does not wire a click trigger. Callers attach their own
 *   `onClick={() => setExpanded(v => !v)}` to whatever element they want to
 *   act as the toggle.
 *
 * @example Plain
 * ```tsx
 * <Card padding="md" border="solid">
 *   <p>Hello</p>
 * </Card>
 * ```
 *
 * @example Expandable, controlled
 * ```tsx
 * const [open, setOpen] = useState(false);
 * <Card
 *   expandable
 *   expanded={open}
 *   content={<ModelList />}
 *   border="solid"
 * >
 *   <button onClick={() => setOpen(v => !v)}>Toggle</button>
 * </Card>
 * ```
 */
function Card(props: CardProps) {
  const {
    padding: paddingProp = "md",
    rounding: roundingProp = "md",
    background = "light",
    border = "none",
    borderColor = "default",
    ref,
    children,
  } = props;

  const padding = paddingVariants[paddingProp];

  // Plain mode — unchanged behavior
  if (!props.expandable) {
    return (
      <div
        ref={ref}
        className={cn("opal-card", padding, cardRoundingVariants[roundingProp])}
        data-background={background}
        data-border={border}
        data-opal-status-border={borderColor}
      >
        {children}
      </div>
    );
  }

  // Expandable mode
  const { expanded = false, content } = props;
  const showContent = expanded && content !== undefined;
  const headerRounding = showContent
    ? cardTopRoundingVariants[roundingProp]
    : cardRoundingVariants[roundingProp];

  return (
    <div ref={ref} className="opal-card-expandable">
      <div
        className={cn("opal-card-expandable-header", padding, headerRounding)}
        data-background={background}
        data-border={border}
        data-opal-status-border={borderColor}
      >
        {children}
      </div>
      {content !== undefined && (
        <div
          className="opal-card-expandable-wrapper"
          data-expanded={showContent ? "true" : "false"}
        >
          <div className="opal-card-expandable-inner">
            <div
              className={cn(
                "opal-card-expandable-body",
                padding,
                cardBottomRoundingVariants[roundingProp]
              )}
              data-border={border}
              data-opal-status-border={borderColor}
            >
              {content}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { Card, type CardProps, type BackgroundVariant, type BorderVariant };
