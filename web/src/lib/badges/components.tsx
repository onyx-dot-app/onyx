"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Badge, type BadgeProps } from "@opal/components";
import { SvgOrganization, SvgUsers } from "@opal/icons";
import type { IconFunctionComponent, RichStr, StatusColor } from "@opal/types";
import { Tier } from "@/lib/tiers/types";

// The app's standard badges. Each is the small (size 4) Badge: callers pick
// the kind, never the colour, icon or size, so every use reads the same.

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

/** Where a feature is in its life: a lowercase label in a status colour. */
export type Lifecycle =
  | "alpha"
  | "beta"
  | "coming-soon"
  | "deprecated"
  | "legacy"
  | "temporarily-unavailable";

const LIFECYCLE_BADGES: Record<
  Lifecycle,
  {
    color: StatusColor;
    // The label's key under `common.badges.lifecycle`.
    copyKey:
      | "alpha"
      | "beta"
      | "comingSoon"
      | "deprecated"
      | "legacy"
      | "temporarilyUnavailable";
  }
> = {
  alpha: { color: "queued", copyKey: "alpha" },
  beta: { color: "info", copyKey: "beta" },
  "coming-soon": { color: "success", copyKey: "comingSoon" },
  deprecated: { color: "default", copyKey: "deprecated" },
  legacy: { color: "pending", copyKey: "legacy" },
  "temporarily-unavailable": {
    color: "default",
    copyKey: "temporarilyUnavailable",
  },
};

/** A lifecycle badge's props, for a `tag` or `badge` slot. */
export function useLifecycleBadge(lifecycle: Lifecycle): BadgeProps {
  const t = useTranslations("common.badges.lifecycle");
  return useMemo(() => {
    const { color, copyKey } = LIFECYCLE_BADGES[lifecycle];
    return { title: t(copyKey), color, size: 4 };
  }, [t, lifecycle]);
}

export interface LifecycleBadgeProps {
  lifecycle: Lifecycle;
  tooltip?: string | RichStr;
}

/** A lifecycle badge on its own. */
export function LifecycleBadge({ lifecycle, tooltip }: LifecycleBadgeProps) {
  return <Badge {...useLifecycleBadge(lifecycle)} tooltip={tooltip} />;
}

// ---------------------------------------------------------------------------
// Label
// ---------------------------------------------------------------------------

/** A short fact about an item in a list, such as the default provider. */
export type Label = "default" | "defaultChat" | "defaultImage";

const LABEL_BADGES: Record<
  Label,
  {
    color: StatusColor;
    // The label's key under `common.badges.labels`.
    copyKey: "default" | "defaultChat" | "defaultImage";
  }
> = {
  default: { color: "info", copyKey: "default" },
  defaultChat: { color: "info", copyKey: "defaultChat" },
  defaultImage: { color: "info", copyKey: "defaultImage" },
};

/** A label badge's props, for a `tag` or `badge` slot. */
export function useLabelBadge(label: Label): BadgeProps {
  const t = useTranslations("common.badges.labels");
  return useMemo(() => {
    const { color, copyKey } = LABEL_BADGES[label];
    return { title: t(copyKey), color, size: 4 };
  }, [t, label]);
}

export interface LabelBadgeProps {
  label: Label;
  tooltip?: string | RichStr;
}

/** A label badge on its own. */
export function LabelBadge({ label, tooltip }: LabelBadgeProps) {
  return <Badge {...useLabelBadge(label)} tooltip={tooltip} />;
}

// ---------------------------------------------------------------------------
// Model type
// ---------------------------------------------------------------------------

/** What a model can do. */
export type ModelType = "chat" | "vision" | "decision" | "image";

/** Each capability has its own colour, so a row's tags read at a glance. */
const MODEL_TYPE_BADGES: Record<ModelType, { color: StatusColor }> = {
  chat: { color: "success" },
  vision: { color: "pending" },
  decision: { color: "warning" },
  image: { color: "queued" },
};

/** A model type badge's props, for a `tag` or `badge` slot. The label is
 *  the type's key under `common.badges.modelTypes`. */
export function useModelTypeBadge(modelType: ModelType): BadgeProps {
  const t = useTranslations("common.badges.modelTypes");
  return useMemo(
    () => ({ title: t(modelType), ...MODEL_TYPE_BADGES[modelType], size: 4 }),
    [t, modelType]
  );
}

export interface ModelTypeBadgeProps {
  modelType: ModelType;
  tooltip?: string | RichStr;
}

/** A model type badge on its own. */
export function ModelTypeBadge({ modelType, tooltip }: ModelTypeBadgeProps) {
  return <Badge {...useModelTypeBadge(modelType)} tooltip={tooltip} />;
}

// ---------------------------------------------------------------------------
// Plan
// ---------------------------------------------------------------------------

const PLAN_BADGES: Record<
  Tier,
  {
    color: StatusColor;
    icon: IconFunctionComponent | undefined;
    // The plan's key under `common.plans`; the UI calls COMMUNITY "Free".
    copyKey: "free" | "business" | "enterprise";
  }
> = {
  [Tier.COMMUNITY]: { color: "default", icon: undefined, copyKey: "free" },
  [Tier.BUSINESS]: { color: "success", icon: SvgUsers, copyKey: "business" },
  [Tier.ENTERPRISE]: {
    color: "pending",
    icon: SvgOrganization,
    copyKey: "enterprise",
  },
};

/** A plan badge's props: its title, colour and icon are always set. */
export type PlanBadgeTag = BadgeProps & {
  title: string;
  color: StatusColor;
  icon: IconFunctionComponent | undefined;
};

/** Every plan's badge props, by tier, for `tag` or `badge` slots. */
export function usePlanBadges(): Record<Tier, PlanBadgeTag> {
  const t = useTranslations("common.plans");
  return useMemo(() => {
    const badge = (tier: Tier): PlanBadgeTag => {
      const { color, icon, copyKey } = PLAN_BADGES[tier];
      return { title: t(`${copyKey}.title`), color, icon, size: 4 };
    };
    return {
      [Tier.COMMUNITY]: badge(Tier.COMMUNITY),
      [Tier.BUSINESS]: badge(Tier.BUSINESS),
      [Tier.ENTERPRISE]: badge(Tier.ENTERPRISE),
    };
  }, [t]);
}

/** One plan's badge props, for a `tag` or `badge` slot. */
export function usePlanBadge(plan: Tier): PlanBadgeTag {
  return usePlanBadges()[plan];
}

export interface PlanBadgeProps {
  plan: Tier;
  tooltip?: string | RichStr;
}

/** A plan's badge on its own. */
export function PlanBadge({ plan, tooltip }: PlanBadgeProps) {
  return <Badge {...usePlanBadge(plan)} tooltip={tooltip} />;
}
