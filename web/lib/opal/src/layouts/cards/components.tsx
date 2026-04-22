// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CardHeaderProps {
  /** Content rendered in the header slot — typically a {@link ContentAction} block. */
  children?: React.ReactNode;

  /** Content rendered below `children`, in a right-aligned column. */
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
 * A card header layout with a main content slot, an optional right-aligned
 * column below, and a full-width `bottomChildren` slot.
 *
 * ```
 * +-----------------------------------+
 * | children                    |
 * +                  +----------------+
 * |                  | bottomRight    |
 * +------------------+----------------+
 * | bottomChildren (full width)       |
 * +-----------------------------------+
 * ```
 *
 * For the typical icon/title/description + right-action pattern, pass a
 * {@link ContentAction} into `children` with `rightChildren` for
 * the action button.
 *
 * @example
 * ```tsx
 * <Card.Header
 *   bottomRightChildren={
 *     <>
 *       <Button icon={SvgUnplug} size="sm" prominence="tertiary" />
 *       <Button icon={SvgSettings} size="sm" prominence="tertiary" />
 *     </>
 *   }
 * >
 *   <ContentAction
 *     icon={SvgGlobe}
 *     title="Google"
 *     description="Search engine"
 *     sizePreset="main-ui"
 *     variant="section"
 *     padding="lg"
 *     rightChildren={<Button>Connect</Button>}
 *   />
 * </Card.Header>
 * ```
 */
function Header({
  children,
  bottomRightChildren,
  bottomChildren,
}: CardHeaderProps) {
  return (
    <div className="flex flex-col w-full">
      <div className="flex flex-row items-start w-full">
        {children != null && (
          <div className="self-start grow min-w-0">{children}</div>
        )}
        {bottomRightChildren != null && (
          <div className="flex flex-col items-end shrink-0">
            <div className="flex flex-row">{bottomRightChildren}</div>
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
