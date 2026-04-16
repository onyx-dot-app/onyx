import "@opal/components/buttons/link-button/styles.css";
import type { RichStr } from "@opal/types";
import type { TooltipSide } from "@opal/components/tooltip/components";

// Direct file imports to avoid circular resolution through the @opal/components
// and @opal/icons barrels, which break CJS-based test runners (jest).
import { Tooltip } from "@opal/components/tooltip/components";
import SvgExternalLink from "@opal/icons/external-link";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LinkButtonProps {
  /** Visible label. Always rendered as underlined link text. */
  children: string;

  /** Destination URL. When provided, the component renders as an `<a>`. */
  href?: string;

  /** Anchor `target` attribute (e.g. `"_blank"`). Only meaningful with `href`. */
  target?: string;

  /** Click handler. When provided without `href`, the component renders as a `<button>`. */
  onClick?: () => void;

  /** Applies disabled styling + suppresses navigation/clicks. */
  disabled?: boolean;

  /** Tooltip text shown on hover. Pass `markdown(...)` for inline markdown. */
  tooltip?: string | RichStr;

  /** Which side the tooltip appears on. @default "top" */
  tooltipSide?: TooltipSide;
}

// ---------------------------------------------------------------------------
// LinkButton
// ---------------------------------------------------------------------------

/**
 * A bare, anchor-styled link with a trailing external-link glyph. Renders
 * as `<a>` when given `href`, or `<button>` when given `onClick`. Intended
 * for inline references — "Pricing", "Docs", etc. — not for interactive
 * surfaces that need hover backgrounds or prominence tiers (use `Button`
 * for those).
 *
 * Deliberately does NOT use `Interactive.Stateless` / `Interactive.Container`
 * — those come with height/rounding/padding and a colour matrix that are
 * wrong for an inline text link. Styling is kept to: underlined label,
 * small external-link icon, a subtle color shift on hover, and disabled
 * opacity.
 */
function LinkButton({
  children,
  href,
  target,
  onClick,
  disabled,
  tooltip,
  tooltipSide = "top",
}: LinkButtonProps) {
  const inner = (
    <>
      <span className="opal-link-button-label font-secondary-body">
        {children}
      </span>
      <SvgExternalLink size={12} />
    </>
  );

  // Always stop propagation so clicks don't bubble to interactive ancestors
  // (cards, list rows, etc. that commonly wrap a LinkButton). If disabled,
  // also preventDefault on anchors so the browser doesn't navigate.
  const handleAnchorClick = (e: React.MouseEvent<HTMLAnchorElement>) => {
    e.stopPropagation();
    if (disabled) e.preventDefault();
  };

  const handleButtonClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    if (disabled) return;
    onClick?.();
  };

  const element = href ? (
    <a
      className="opal-link-button"
      href={disabled ? undefined : href}
      target={target}
      rel={target === "_blank" ? "noopener noreferrer" : undefined}
      aria-disabled={disabled || undefined}
      data-disabled={disabled || undefined}
      onClick={handleAnchorClick}
    >
      {inner}
    </a>
  ) : (
    <button
      type="button"
      className="opal-link-button"
      onClick={handleButtonClick}
      disabled={disabled}
      data-disabled={disabled || undefined}
    >
      {inner}
    </button>
  );

  return (
    <Tooltip tooltip={tooltip} side={tooltipSide}>
      {element}
    </Tooltip>
  );
}

export { LinkButton, type LinkButtonProps };
