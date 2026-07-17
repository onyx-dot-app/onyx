import "@opal/components/buttons/text-button/styles.css";
import type { HTMLAttributes } from "react";
import type { Route } from "next";
import Link from "next/link";
import { Interactive } from "@opal/core";
import type { RichStr, WithoutStyles } from "@opal/types";
import { Text, type TextFont } from "@opal/components";
import { cn } from "@opal/utils";

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

interface TextButtonSurfaceProps extends WithoutStyles<
  HTMLAttributes<HTMLElement>
> {
  href?: string;
  target?: string;
  rel?: string;
}

// ---------------------------------------------------------------------------
// TextButtonSurface
// ---------------------------------------------------------------------------

/**
 * Element selection for `TextButton` — a trimmed-down copy of
 * `Interactive.Container`'s `<Link> / <button>` branching, minus the
 * height/rounding/padding/border/background that `Container` applies.
 * `TextButton` is deliberately built without `Interactive.Container` so it
 * never gets those "traditional button" surroundings.
 */
function TextButtonSurface(props: TextButtonSurfaceProps) {
  const {
    className: slotClassName,
    href,
    target,
    rel,
    ...rest
  } = props as TextButtonSurfaceProps & { className?: string };

  const sharedProps = {
    ...rest,
    className: cn("opal-text-button interactive-foreground", slotClassName),
  };

  if (href) {
    return (
      <Link
        href={href as Route}
        target={target}
        rel={rel}
        {...(sharedProps as HTMLAttributes<HTMLAnchorElement>)}
      />
    );
  }

  const ariaDisabled = (rest as Record<string, unknown>)["aria-disabled"];
  const nativeDisabled =
    ariaDisabled === true || ariaDisabled === "true" || undefined;

  return (
    <button
      type="button"
      disabled={nativeDisabled}
      {...(sharedProps as HTMLAttributes<HTMLButtonElement>)}
    />
  );
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
 */
function TextButton({
  font = "main-ui-body",
  nowrap = true,
  disabled,
  children,
  ...rest
}: TextButtonProps) {
  return (
    <Interactive.Stateless
      type="button"
      variant="default"
      prominence="tertiary"
      disabled={disabled}
      {...rest}
    >
      <TextButtonSurface>
        <Text font={font} color="inherit" nowrap={nowrap}>
          {children}
        </Text>
      </TextButtonSurface>
    </Interactive.Stateless>
  );
}

export { TextButton, type TextButtonProps };
