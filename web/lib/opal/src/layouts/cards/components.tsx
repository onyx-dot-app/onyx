import { Content, type ContentProps } from "@opal/layouts/content/components";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type CardHeaderProps = ContentProps & {
  /** Content rendered to the right of the Content block. */
  rightChildren?: React.ReactNode;

  /** Content rendered below `rightChildren` in the same column. */
  bottomRightChildren?: React.ReactNode;

  /**
   * Content rendered below the header row, full-width.
   * Use for expandable sections, search bars, or any content
   * that should appear beneath the icon/title/actions row.
   */
  children?: React.ReactNode;
};

// ---------------------------------------------------------------------------
// Card.Header
// ---------------------------------------------------------------------------

/**
 * A card header layout that pairs a {@link Content} block (with `p-2`)
 * with a right-side column.
 *
 * The right column contains two vertically stacked slots —
 * `rightChildren` on top, `bottomRightChildren` below — with no
 * padding or gap between them.
 *
 * The optional `children` slot renders below the full header row,
 * spanning the entire width.
 *
 * @example
 * ```tsx
 * <Card.Header
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
function Header({
  rightChildren,
  bottomRightChildren,
  children,
  ...contentProps
}: CardHeaderProps) {
  const hasRight = rightChildren || bottomRightChildren;

  return (
    <div className="flex flex-col w-full">
      <div className="flex flex-row items-stretch w-full">
        <div className="flex-1 min-w-0 self-start p-2">
          <Content {...contentProps} />
        </div>
        {hasRight && (
          <div className="flex flex-col items-end shrink-0">
            {rightChildren && <div className="flex-1">{rightChildren}</div>}
            {bottomRightChildren && (
              <div className="flex flex-row">{bottomRightChildren}</div>
            )}
          </div>
        )}
      </div>
      {children && <div className="w-full">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Card namespace
// ---------------------------------------------------------------------------

const Card = { Header };

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { Card, type CardHeaderProps };
