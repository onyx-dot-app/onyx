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
   * Padding and gap applied around the `Content` area.
   * Uses the shared `SizeVariant` scale from `@opal/shared`.
   *
   * @default "lg"
   * @see {@link ContainerSizeVariants} for the full list of presets.
   */
  paddingVariant?: ContainerSizeVariants;
};

// ---------------------------------------------------------------------------
// ContentAction
// ---------------------------------------------------------------------------

/**
 * A row layout that pairs a {@link Content} block with optional right-side
 * action children (e.g. buttons, badges).
 *
 * The `Content` area receives padding controlled by `paddingVariant`, using
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
 *   paddingVariant="lg"
 *   rightChildren={<Button icon={SvgSettings} prominence="tertiary" />}
 * />
 * ```
 */
function ContentAction({
  rightChildren,
  paddingVariant = "lg",
  ...contentProps
}: ContentActionProps) {
  const { padding, gap } = containerSizeVariants[paddingVariant];

  return (
    <div className={cn("flex flex-row items-stretch w-full", gap)}>
      <div className={cn("flex-1 min-w-0 self-center", padding)}>
        <Content {...contentProps} />
      </div>
      {rightChildren && (
        <div className="flex items-stretch shrink-0">{rightChildren}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { ContentAction, type ContentActionProps };
