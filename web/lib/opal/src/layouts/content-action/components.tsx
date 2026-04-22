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
};

// ---------------------------------------------------------------------------
// ContentAction
// ---------------------------------------------------------------------------

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
  ...contentProps
}: ContentActionProps) {
  const { padding: paddingClass } = containerSizeVariants[padding];

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
