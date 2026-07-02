import "@opal/layouts/content-action/styles.css";
import { Content, type ContentProps } from "@opal/layouts/content/components";
import {
  containerSizeVariants,
  type ContainerSizeVariants,
} from "@opal/shared";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ContentActionProps = ContentProps & {
  /** Content rendered on the right side, stretched to full height. */
  rightChildren?: React.ReactNode;

  /**
   * Padding applied around the `Content` area.
   * Uses the shared `SizeVariant` scale from `@opal/shared`.
   *
   * @default "lg"
   * @see {@link ContainerSizeVariants} for the full list of presets.
   */
  padding?: ContainerSizeVariants;

  /**
   * When true, vertically centers the Content and rightChildren.
   * When false (default), Content is top-aligned and rightChildren
   * stretches to full height.
   *
   * @default false
   */
  center?: boolean;

  /**
   * When true, `rightChildren` reflows responsively — forwarded into the
   * `ContentMd` slot so it sits to the right of the title/description on desktop
   * and stacks between them on narrow viewports. Requires a `main-*` size
   * preset (the only ones with the slot); other presets fall back to the
   * standard right-hand column. `center` is ignored in this mode.
   *
   * @default false
   */
  responsive?: boolean;
};

// ---------------------------------------------------------------------------
// ContentAction
// ---------------------------------------------------------------------------

// Only the `main-*` presets route to ContentMd — the one layout with a
// `rightChildren` slot — so `responsive` can only reflow for those.
function routesToContentMd(props: {
  sizePreset?: string;
  variant?: string;
}): boolean {
  const isMdPreset =
    props.sizePreset === "main-content" ||
    props.sizePreset === "main-ui" ||
    props.sizePreset === "secondary";
  return isMdPreset && props.variant !== "body";
}

/**
 * A row layout that pairs a {@link Content} block with optional right-side
 * action children (e.g. buttons, badges).
 *
 * The `Content` area receives padding controlled by `padding`, using
 * the same size scale as `Interactive.Container` and `Button`. The
 * `rightChildren` wrapper stretches to the full height of the row.
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
 *   sizePreset="main-content"
 *   variant="section"
 *   padding="lg"
 *   rightChildren={<Button icon={SvgSettings} prominence="tertiary" />}
 * />
 * ```
 */
function ContentAction({
  rightChildren,
  padding = "lg",
  center = false,
  responsive = false,
  ...contentProps
}: ContentActionProps) {
  const { padding: paddingClass } = containerSizeVariants[padding];

  // Responsive: forward rightChildren into the ContentMd slot, which reflows it
  // to the right on desktop and between the title/description on narrow widths.
  if (responsive && rightChildren && routesToContentMd(contentProps)) {
    // Full width: in a flex-col `align-items: start` parent (e.g. InputHorizontal's
    // Section) a wrapper without w-full shrinks to content width, so the input
    // wouldn't fill the row.
    return (
      <div className={cn("w-full min-w-0", paddingClass)}>
        <Content {...({ ...contentProps, rightChildren } as ContentProps)} />
      </div>
    );
  }

  return (
    <div className="opal-content-action" data-centered={center || undefined}>
      <div className={cn("opal-content-action-content", paddingClass)}>
        <Content {...contentProps} />
      </div>
      {rightChildren && (
        <div className="opal-content-action-right">{rightChildren}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { ContentAction, type ContentActionProps };
