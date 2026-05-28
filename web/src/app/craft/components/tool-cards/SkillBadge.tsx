"use client";

import { Tag } from "@opal/components";
import { SvgSparkle } from "@opal/icons";

interface SkillBadgeProps {
  name: string;
}

/**
 * SkillBadge - Small chip rendered in a ToolCardHeader when a tool call
 * originated from a skill (skill-namespaced tool name).
 */
export default function SkillBadge({ name }: SkillBadgeProps) {
  return <Tag icon={SvgSparkle} title={name} color="blue" size="sm" />;
}
