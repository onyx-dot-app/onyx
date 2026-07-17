import "@opal/components/buttons/text-button/styles.css";
import type { HTMLAttributes } from "react";
import type { Route } from "next";
import Link from "next/link";
import { Interactive } from "@opal/core";
import type { RichStr, WithoutStyles } from "@opal/types";
import { Text, type TextFont } from "@opal/components";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TextButtonProps extends WithoutStyles<
  Omit<HTMLAttributes<HTMLElement>, "color" | "children">
> {
  /** Font preset. Default: `"main-ui-body"`. */
  font?: TextFont;

  /** Prevent text wrapping. Default: `true` (unlike `Text`, which defaults to `false`). */
  nowrap?: boolean;

  /** Destination URL. When provided, the component renders as a link. */
  href?: string;

  /** Anchor `target` attribute (e.g. `"_blank"`). Only meaningful with `href`. */
  target?: string;

  /** Applies disabled styling and suppresses clicks/navigation. */
  disabled?: boolean;

  /** Plain string or `markdown()` for inline markdown. */
  children: string | RichStr;
}

// ---------------------------------------------------------------------------
// TextButton
// ---------------------------------------------------------------------------

/**
 * A clickable `Text` — same hover/active color animation as `Button` (driven
 * by `Interactive.Stateless`, always at `variant="default"` /
 * `prominence="tertiary"`), but with no `Interactive.Container` underneath:
 * no background, no border, no padding, no rounding. Props are intentionally
 * shaped like `Text` (`font`, `nowrap`, required `children`) rather than
 * `Button` (no `icon`/`rightIcon`, `variant`, `prominence`, `tooltip`, or
 * `size`).
 *
 * Renders its `<Link>`/`<button>` directly as `Interactive.Stateless`'s
 * single child — Radix `Slot` auto-merges `className`, data-attributes, and
 * `onClick` onto it (`className`/`style` are joined, handlers are chained,
 * everything else falls through), so no separate surface component is
 * needed the way `Button` needs `Interactive.Container`.
 */
function TextButton({
  font = "main-ui-body",
  nowrap = true,
  disabled,
  href,
  target,
  children,
  ...rest
}: TextButtonProps) {
  const label = (
    <Text font={font} color="inherit" nowrap={nowrap}>
      {children}
    </Text>
  );

  return (
    <Interactive.Stateless
      type="button"
      variant="default"
      prominence="tertiary"
      disabled={disabled}
      href={href}
      target={target}
      {...rest}
    >
      {href ? (
        <Link
          href={(disabled ? undefined : href) as Route}
          target={target}
          rel={target === "_blank" ? "noopener noreferrer" : undefined}
          className="opal-text-button interactive-foreground"
        >
          {label}
        </Link>
      ) : (
        <button
          type="button"
          disabled={disabled}
          className="opal-text-button interactive-foreground"
        >
          {label}
        </button>
      )}
    </Interactive.Stateless>
  );
}

export { TextButton, type TextButtonProps };
