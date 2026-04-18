// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CardHeaderProps {
  /** Content rendered in the top-left header slot — typically a {@link Content} block. */
  headerChildren?: React.ReactNode;

  /** Content rendered to the right of `headerChildren` (top of right column). */
  topRightChildren?: React.ReactNode;

  /** Content rendered below `topRightChildren`, in the same column. */
  bottomRightChildren?: React.ReactNode;

  /**
   * Content rendered below the entire header (left + right columns),
   * spanning the full width. Use for expandable sections, search bars, or
   * any content that should appear beneath the icon/title/actions row.
   */
  bottomChildren?: React.ReactNode;
}

// ---------------------------------------------------------------------------
// Card.Header
// ---------------------------------------------------------------------------

/**
 * A card header layout with three optional slots arranged in two independent
 * columns, plus a full-width `bottomChildren` slot below.
 *
 * ```
 * +------------------+----------------+
 * | headerChildren   | topRight       |
 * +                  +----------------+
 * |                  | bottomRight    |
 * +------------------+----------------+
 * | bottomChildren (full width)       |
 * +-----------------------------------+
 * ```
 *
 * The left column grows to fill available space; the right column shrinks
 * to fit its content. The two columns are independent in height.
 *
 * For the typical icon/title/description pattern, pass a {@link Content}
 * (or {@link ContentAction}) into `headerChildren`.
 *
 * @example
 * ```tsx
 * <Card.Header
 *   headerChildren={
 *     <Content
 *       icon={SvgGlobe}
 *       title="Google"
 *       description="Search engine"
 *       sizePreset="main-ui"
 *       variant="section"
 *     />
 *   }
 *   topRightChildren={<Button>Connect</Button>}
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
  headerChildren,
  topRightChildren,
  bottomRightChildren,
  bottomChildren,
}: CardHeaderProps) {
  const hasRight = topRightChildren != null || bottomRightChildren != null;

  return (
    <div className="flex flex-col w-full">
      <div className="flex flex-row items-start w-full">
        {headerChildren != null && (
          <div className="self-start p-2 grow min-w-0">{headerChildren}</div>
        )}
        {hasRight && (
          <div className="flex flex-col items-end shrink-0">
            {topRightChildren != null && <div>{topRightChildren}</div>}
            {bottomRightChildren != null && (
              <div className="flex flex-row">{bottomRightChildren}</div>
            )}
          </div>
        )}
      </div>
      {bottomChildren != null && <div className="w-full">{bottomChildren}</div>}
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
