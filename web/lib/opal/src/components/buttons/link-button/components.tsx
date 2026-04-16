import "@opal/components/buttons/link-button/styles.css";
import { Tooltip, type TooltipSide } from "@opal/components";
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

  /** Tooltip text shown on hover. */
  tooltip?: string;

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
      <span className="opal-link-button-label">{children}</span>
      <SvgExternalLink size={12} />
    </>
  );

  const element = href ? (
    <a
      className="opal-link-button"
      href={disabled ? undefined : href}
      target={target}
      rel={target === "_blank" ? "noopener noreferrer" : undefined}
      aria-disabled={disabled || undefined}
      data-disabled={disabled || undefined}
    >
      {inner}
    </a>
  ) : (
    <button
      type="button"
      className="opal-link-button"
      onClick={disabled ? undefined : onClick}
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
