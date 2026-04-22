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
  centered?: boolean;
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
  centered = false,
  ...contentProps
}: ContentActionProps) {
  const { padding: paddingClass } = containerSizeVariants[padding];

  return (
    <div
      className={cn(
        "flex flex-row w-full",
        centered ? "items-center" : "items-stretch"
      )}
    >
      <div
        className={cn(
          "flex-1 min-w-0",
          centered ? "self-center" : "self-start",
          paddingClass
        )}
      >
        <Content {...contentProps} />
      </div>
      {rightChildren && (
        <div
          className={cn(
            "flex shrink-0",
            centered ? "items-center" : "items-stretch"
          )}
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
