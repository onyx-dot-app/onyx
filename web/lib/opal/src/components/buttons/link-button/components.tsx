import { Interactive, type InteractiveStatelessProps } from "@opal/core";
import { Text, Tooltip, type TooltipSide } from "@opal/components";
import SvgExternalLink from "@opal/icons/external-link";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type LinkButtonProps = Pick<
  InteractiveStatelessProps,
  "onClick" | "href" | "target" | "ref" | "group" | "disabled"
> & {
  /** Visible label rendered as underlined link text. */
  children: string;

  /** Tooltip text shown on hover. */
  tooltip?: string;

  /** Which side the tooltip appears on. @default "top" */
  tooltipSide?: TooltipSide;
};

// ---------------------------------------------------------------------------
// LinkButton
// ---------------------------------------------------------------------------

/**
 * A compact, link-style button with an external-link icon.
 *
 * Renders as `text` + external-link icon, both in `text-03`. The text is
 * always underlined. Backed by `Interactive.Stateless` (`internal` prominence)
 * so it picks up the standard hover/active background tints.
 *
 * Use `href` (with optional `target="_blank"`) to render as a link, or
 * `onClick` for a button.
 */
function LinkButton({
  children,
  onClick,
  href,
  target,
  ref,
  group,
  disabled,
  tooltip,
  tooltipSide = "top",
}: LinkButtonProps) {
  const button = (
    <Interactive.Stateless
      prominence="internal"
      onClick={onClick}
      href={href}
      target={target}
      ref={ref}
      group={group}
      disabled={disabled}
      type={href ? undefined : "button"}
    >
      <Interactive.Container
        type={href ? undefined : "button"}
        heightVariant="fit"
        roundingVariant="xs"
      >
        <div className="flex flex-row items-center gap-0.5">
          <span className="underline">
            <Text font="secondary-body" color="text-03">
              {children}
            </Text>
          </span>
          <div className="p-0.5">
            <SvgExternalLink size={12} className="text-text-03" />
          </div>
        </div>
      </Interactive.Container>
    </Interactive.Stateless>
  );

  return (
    <Tooltip tooltip={tooltip} side={tooltipSide}>
      {button}
    </Tooltip>
  );
}

export { LinkButton, type LinkButtonProps };
