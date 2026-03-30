import { Content, type ContentProps } from "@opal/layouts/content/components";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type CardHeaderLayoutProps = ContentProps & {
  /** Content rendered to the right of the Content block. */
  rightChildren?: React.ReactNode;

  /** Content rendered below `rightChildren` in the same column. */
  bottomRightChildren?: React.ReactNode;
};

// ---------------------------------------------------------------------------
// CardHeaderLayout
// ---------------------------------------------------------------------------

/**
 * A card header layout that pairs a {@link Content} block (with `p-2`)
 * with a right-side column.
 *
 * The right column contains two vertically stacked slots —
 * `rightChildren` on top, `bottomRightChildren` below — with no
 * padding or gap between them.
 *
 * @example
 * ```tsx
 * <CardHeaderLayout
 *   icon={SvgGlobe}
 *   title="Google"
 *   description="Search engine"
 *   sizePreset="main-ui"
 *   variant="section"
 *   rightChildren={<Button>Connect</Button>}
 *   bottomRightChildren={
 *     <>
 *       <Button icon={SvgUnplug} size="sm" prominence="tertiary" />
 *       <Button icon={SvgSettings} size="sm" prominence="tertiary" />
 *     </>
 *   }
 * />
 * ```
 */
function CardHeaderLayout({
  rightChildren,
  bottomRightChildren,
  ...contentProps
}: CardHeaderLayoutProps) {
  const hasRight = rightChildren || bottomRightChildren;

  return (
    <div className="flex flex-row items-stretch w-full">
      <div className="flex-1 min-w-0 self-start p-2">
        <Content {...contentProps} />
      </div>
      {hasRight && (
        <div className="flex flex-col items-end shrink-0">
          <div className="flex-1">{rightChildren}</div>
          {bottomRightChildren && (
            <div className="flex flex-row">{bottomRightChildren}</div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { CardHeaderLayout, type CardHeaderLayoutProps };
