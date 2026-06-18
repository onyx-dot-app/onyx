// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CardHeaderProps {
  /** Content rendered in the header slot — typically a {@link ContentAction} block. */
  children?: React.ReactNode;

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
 * A card header layout with a main content slot and a full-width
 * `bottomChildren` slot.
 *
 * ```
 * +-----------------------------------+
 * | children                          |
 * +-----------------------------------+
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
 * <Card.Header>
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
function Header({ children, bottomChildren }: CardHeaderProps) {
  return (
    <div className="flex flex-col w-full">
      <div className="flex flex-row items-start w-full">
        {children != null && (
          <div className="self-start grow min-w-0">{children}</div>
        )}
      </div>
      {bottomChildren && <div className="w-full">{bottomChildren}</div>}
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
