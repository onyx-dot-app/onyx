"use client";

import { Badge } from "@opal/components";
import { SvgSparkle } from "@opal/icons";

interface SkillBadgeProps {
  name: string;
}

/**
 * SkillBadge - Small chip rendered in a ToolCardHeader when a tool call
 * originated from a skill (skill-namespaced tool name).
 */
export default function SkillBadge({ name }: SkillBadgeProps) {
  return <Badge icon={SvgSparkle} title={name} color="info" size={4} />;
}
