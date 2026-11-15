import type { InteractiveStatefulInteraction } from "@opal/core";

/** The attributes a trigger merges onto its child that say the list is open. */
export interface TriggerOpenAttributes {
  /** Set by Radix triggers. */
  "data-state"?: string;
  /** Set by an Opal Dropdown trigger. */
  "aria-expanded"?: boolean | "true" | "false";
}

/**
 * A trigger button's interaction: the caller's own, else "hover" while the
 * list it opens is open. "hover" turns the chevron and keeps the highlight.
 */
export function resolveTriggerInteraction(
  interaction: InteractiveStatefulInteraction | undefined,
  trigger: TriggerOpenAttributes
): InteractiveStatefulInteraction {
  if (interaction !== undefined) return interaction;
  const isOpen =
    trigger["data-state"] === "open" ||
    trigger["aria-expanded"] === true ||
    trigger["aria-expanded"] === "true";
  return isOpen ? "hover" : "rest";
}
