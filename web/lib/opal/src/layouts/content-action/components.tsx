import "@opal/layouts/content-action/styles.css";
import {
  Content,
  ContentDescription,
  contentColorStyle,
  hasIconGap,
  type ContentProps,
} from "@opal/layouts/content/components";
import { cn } from "@opal/utils";
import { spacingToRem } from "@opal/shared";
import type { Spacing } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentActionProps = ContentProps & {
  /** Content rendered on the right side, stretched to full height. */
  rightChildren?: React.ReactNode;

  /**
   * Padding applied around the `Content` area, as a spacing step (`N / 4` rem).
   *
   * Narrowed to the four paddings `Interactive.Container` applies at its size
   * presets. Matching them is the point of this prop — it is what lines a label
   * up with an adjacent button of the same size — so an arbitrary step would
   * only ever break that alignment.
   *
   * @default 2
   */
  padding?: 0 | 0.5 | 1 | 1.5 | 2;

  /**
   * The gap between the `Content` area and `rightChildren`, as a spacing
   * step (`N / 4` rem). Ignored in the `responsive` branch.
   *
   * @default 4
   */
  gapping?: Spacing;

  /**
   * When true, vertically centers the Content and rightChildren.
   * When false (default), Content is top-aligned and rightChildren
   * stretches to full height.
   *
   * @default false
   */
  center?: boolean;

  /**
   * When true, `rightChildren` reflows responsively: it sits to the right of
   * the title and description on desktop, and between them on narrow
   * viewports. `center` and `gapping` are ignored in this mode.
   *
   * @default false
   */
  responsive?: boolean;

  /**
   * When true, the `rightChildren` column grows to fill the row (capped at
   * `--block-width-form-input-column-max`) instead of hugging its content.
   * Intended for full-width form inputs; leave off for compact controls like
   * toggles/buttons. In the `responsive` branch it applies on desktop, where
   * the control sits beside the title; stacked on narrow viewports, the
   * control always spans the full width.
   *
   * @default false
   */
  fillRight?: boolean;
};

// ---------------------------------------------------------------------------
// ContentAction
// ---------------------------------------------------------------------------

/**
 * A row layout that pairs a {@link Content} block with optional right-side
 * action children (e.g. buttons, badges).
 *
 * The `Content` area receives padding controlled by `padding`, whose four steps
 * are the paddings `Interactive.Container` applies at its size presets — so a row
 * lines up with an adjacent button. The `rightChildren` wrapper stretches to the
 * full height of the row.
 *
 * @example
 * ```tsx
 * import { ContentAction } from "@opal/layouts";
 * import { Button } from "@opal/components";
 * import SvgSettings from "@opal/icons/settings";
 *
 * <ContentAction
 *   icon={SvgSettings}
 *   title="OpenAI"
 *   description="GPT"
 *   font="main-content-emphasis"
 *   padding={2}
 *   rightChildren={<Button icon={SvgSettings} prominence="tertiary" />}
 * />
 * ```
 */
function ContentAction({
  rightChildren,
  padding = 2,
  gapping = 4,
  center = false,
  responsive = false,
  fillRight = false,
  ...contentProps
}: ContentActionProps) {
  const paddingStyle = { padding: spacingToRem(padding) };

  // Responsive: the title, the control and the description share a grid that
  // puts the control on the right on desktop, and between the title and the
  // description on narrow widths.
  if (responsive && rightChildren) {
    const { description, descriptionMaxLines, ...titleProps } = contentProps;
    const font = contentProps.font ?? "main-ui-action";
    // Only an icon before the title pushes the title in; reversed or
    // stacked, the description already lines up with it.
    const indent =
      !!contentProps.icon &&
      (contentProps.orientation ?? "inline") === "inline";
    // Full width: in a flex-col `align-items: start` parent (e.g. InputHorizontal's
    // Section) a wrapper without w-full shrinks to content width, so the input
    // wouldn't fill the row.
    return (
      <div
        className="opal-content-action-responsive w-full min-w-0"
        data-fill={fillRight || undefined}
        data-content-color={contentProps.color ?? "default"}
        // The same colour variables Content sets, so the description and the
        // control inherit the content's colours.
        style={{
          ...paddingStyle,
          ...contentColorStyle(
            contentProps.color ?? "default",
            contentProps.titleColor
          ),
        }}
      >
        <div className="opal-content-action-responsive-title">
          <Content {...(titleProps as ContentProps)} />
        </div>
        <div className="opal-content-action-responsive-control">
          {rightChildren}
        </div>
        {description && (
          // With an icon, the description lines up under the title: one icon
          // box (`1lh` of the title font) and the gap in.
          <div
            className={cn(
              "opal-content-action-responsive-description",
              indent && `font-${font}`
            )}
            data-indent={indent || undefined}
            data-flush={(indent && !hasIconGap(font)) || undefined}
          >
            <ContentDescription
              description={description}
              maxLines={descriptionMaxLines}
            />
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className="opal-content-action"
      data-centered={center || undefined}
      style={{ gap: spacingToRem(gapping) }}
    >
      <div className="opal-content-action-content" style={paddingStyle}>
        <Content {...contentProps} />
      </div>
      {rightChildren && (
        <div
          className="opal-content-action-right"
          data-fill={fillRight || undefined}
        >
          {rightChildren}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { ContentAction, type ContentActionProps };
