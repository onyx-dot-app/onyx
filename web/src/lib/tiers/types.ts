import type { TagProps } from "@opal/components";
import type { IconFunctionComponent, RichStr } from "@opal/types";

/**
 * The workspace's subscription tier, lowest first. The UI calls a tier a
 * plan ("Business Plan"); COMMUNITY is shown as the Free plan.
 */
export enum Tier {
  COMMUNITY = "community",
  BUSINESS = "business",
  ENTERPRISE = "enterprise",
}

export type PlanColor = NonNullable<TagProps["color"]>;

/** Everything that marks a feature as limited to a plan. */
export interface PlanMetadata {
  title: string;
  icon: IconFunctionComponent | undefined;
  color: PlanColor;
  /** For a `tag` slot, such as `Content`'s or an option's. */
  tag: TagProps;
  /** Why the feature is off below this plan, linking to billing. */
  tooltip: RichStr;
}
