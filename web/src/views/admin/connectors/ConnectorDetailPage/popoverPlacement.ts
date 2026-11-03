import type { ComponentProps } from "react";
import type { Popover } from "@opal/components";

/** Where a card's pill popover opens: beside the card, or below it with its end at the card's end. */
export type PopoverPlacement = "beside" | "below";

export const PLACEMENT_PROPS = {
  beside: { side: "left", align: "start" },
  below: { side: "bottom", align: "end" },
} as const satisfies Record<
  PopoverPlacement,
  Pick<ComponentProps<typeof Popover.Content>, "side" | "align">
>;
