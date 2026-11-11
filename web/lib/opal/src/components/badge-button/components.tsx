"use client";

import { Badge, type BadgeProps } from "@opal/components/badge/components";
import { Tooltip } from "@opal/components/tooltip/components";
import { Interactive } from "@opal/core";

type BadgeButtonProps = Omit<BadgeProps, "ref"> & {
  onClick: () => void;
  /** The hover tooltip and the button's name, since the title may be only a count. */
  tooltip: string;
  /** Set for a filter toggle. Badge has no pressed look, so a pressed toggle shows its title in the badge's colour. */
  pressed?: boolean;
};

/** A static `Badge` in an `Interactive` wrapper: a button, or a filter toggle with `pressed`. */
function BadgeButton({
  onClick,
  tooltip,
  pressed,
  size = 4,
  titleColor,
  ...badge
}: BadgeButtonProps) {
  // The focus ring follows the pill's corners.
  const container = (
    <Interactive.Container
      type="button"
      size="fit"
      rounding={size === 6 ? 2 : 1}
    >
      <Badge
        {...badge}
        size={size}
        titleColor={pressed ? undefined : titleColor}
      />
    </Interactive.Container>
  );
  return (
    <Tooltip tooltip={tooltip} side="top">
      {pressed === undefined ? (
        <Interactive.Stateless
          prominence="tertiary"
          aria-label={tooltip}
          onClick={onClick}
        >
          {container}
        </Interactive.Stateless>
      ) : (
        <Interactive.Stateful
          variant="select-light"
          state={pressed ? "selected" : "empty"}
          aria-label={tooltip}
          aria-pressed={pressed}
          onClick={onClick}
        >
          {container}
        </Interactive.Stateful>
      )}
    </Tooltip>
  );
}

export { BadgeButton, type BadgeButtonProps };
