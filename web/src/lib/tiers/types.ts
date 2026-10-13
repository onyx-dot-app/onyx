import type { TagProps } from "@opal/components";
import type { IconFunctionComponent, RichStr } from "@opal/types";

/** The plans a feature can be limited to, lowest first. */
export type Plan = "free" | "business" | "enterprise";

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
