import "@opal/components/buttons/text-button/styles.css";
import type { Route } from "next";
import Link from "next/link";
import { Interactive, type InteractiveStatelessProps } from "@opal/core";
import type {
  ButtonType,
  ContainerSizeVariants,
  IconFunctionComponent,
  RichStr,
  WithoutStyles,
} from "@opal/types";
import { Text, Tooltip, type TooltipSide } from "@opal/components";
import { iconWrapper } from "@opal/components/buttons/icon-wrapper";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TextButtonContentProps =
  | {
      icon?: IconFunctionComponent;
      children: string | RichStr;
      rightIcon?: IconFunctionComponent;
    }
  | {
      icon: IconFunctionComponent;
      children?: string | RichStr;
      rightIcon?: IconFunctionComponent;
    };

type TextButtonProps = Omit<InteractiveStatelessProps, "prominence"> & {
  /**
   * Color prominence within the variant.
   * @default "tertiary"
   *
   * Defaults to `"tertiary"` (not `"primary"`, unlike `Button`) because
   * `TextButton` never paints a background — `"primary"`'s white-on-color
   * foreground assumes a colored surface that `TextButton` doesn't provide.
   */
  prominence?: InteractiveStatelessProps["prominence"];
} & TextButtonContentProps & {
    /** Size preset — controls label text size and icon size. */
    size?: ContainerSizeVariants;

    /** Tooltip text shown on hover. */
    tooltip?: string;

    /** Which side the tooltip appears on. */
    tooltipSide?: TooltipSide;

    /** Applies disabled styling and suppresses clicks. */
    disabled?: boolean;
  };

interface TextButtonSurfaceProps extends WithoutStyles<
  React.HTMLAttributes<HTMLElement>
> {
  type?: ButtonType;
  href?: string;
  target?: string;
  rel?: string;
}

// ---------------------------------------------------------------------------
// TextButtonSurface
// ---------------------------------------------------------------------------

/**
 * Element selection for `TextButton` — mirrors `Interactive.Container`'s
 * `<Link> / <button> / <span>` branching, minus the height/rounding/padding/
 * border/background that `Container` applies. `TextButton` is deliberately
 * built without `Interactive.Container` so it never gets those "traditional
 * button" surroundings.
 */
function TextButtonSurface(props: TextButtonSurfaceProps) {
  const {
    className: slotClassName,
    href,
    target,
    rel,
    type,
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
        {...(sharedProps as React.HTMLAttributes<HTMLAnchorElement>)}
      />
    );
  }

  if (type) {
    const ariaDisabled = (rest as Record<string, unknown>)["aria-disabled"];
    const nativeDisabled =
      ariaDisabled === true || ariaDisabled === "true" || undefined;
    return (
      <button
        type={type}
        disabled={nativeDisabled}
        {...(sharedProps as React.HTMLAttributes<HTMLButtonElement>)}
      />
    );
  }

  return <span {...sharedProps} />;
}

// ---------------------------------------------------------------------------
// TextButton
// ---------------------------------------------------------------------------

/**
 * A clickable `Text` — same variant/prominence hover-and-active color
 * animation as `Button`, driven by `Interactive.Stateless`, but with no
 * `Interactive.Container` underneath. That means no background, no border,
 * no padding, no rounding: just the label (and optional icons) shifting
 * color on hover/active, exactly like the rest of the Opal buttons.
 */
function TextButton({
  icon: Icon,
  children,
  rightIcon: RightIcon,
  size = "lg",
  type = "button",
  prominence = "tertiary",
  tooltip,
  tooltipSide = "top",
  disabled,
  ...interactiveProps
}: TextButtonProps) {
  const isLarge = size === "lg";

  const labelEl = children ? (
    <Text
      font={isLarge ? "main-ui-body" : "secondary-body"}
      color="inherit"
      nowrap
    >
      {children}
    </Text>
  ) : null;

  const button = (
    <Interactive.Stateless
      type={type}
      prominence={prominence}
      disabled={disabled}
      {...interactiveProps}
    >
      <TextButtonSurface>
        {iconWrapper(Icon, size, !!children)}
        {labelEl}
        {iconWrapper(RightIcon, size, !!children)}
      </TextButtonSurface>
    </Interactive.Stateless>
  );

  return (
    <Tooltip tooltip={tooltip} side={tooltipSide}>
      {button}
    </Tooltip>
  );
}

export { TextButton, type TextButtonProps };
