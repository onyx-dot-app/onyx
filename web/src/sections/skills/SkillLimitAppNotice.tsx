"use client";

import type { ReactNode } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { MessageCard, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { useExternalAppSkillLimitBlocks } from "@/lib/externalApps/hooks";
import { useOwnSkillUsage } from "@/lib/skills/hooks";
import { formatSkillSize } from "@/lib/skills/limits";

interface SkillLimitAppNoticeProps {
  appId: number;
  appName: string;
  /** Rendered below the message, such as a link to manage Skills. */
  action?: ReactNode;
}

/**
 * Explains app Skills that a successful connection left off for the Skill
 * limit, with the user's current usage. Renders nothing when none are off.
 */
export default function SkillLimitAppNotice({
  appId,
  appName,
  action,
}: SkillLimitAppNoticeProps) {
  const t = useTranslations("skills.limit.app");
  const format = useFormatter();
  const blocked = useExternalAppSkillLimitBlocks(appId);
  const { usage } = useOwnSkillUsage(blocked.length > 0);
  if (blocked.length === 0) return null;

  const limit = blocked.some((skill) => skill.skill_limit_block === "bytes")
    ? "bytes"
    : "files";
  const retry = blocked.every((skill) => skill.can_toggle)
    ? "toggle"
    : "reconnect";

  return (
    <MessageCard
      variant="warning"
      outerPadding={1}
      innerPadding={1}
      title={t("title", { count: blocked.length, app: appName })}
      bottomChildren={
        <Section height="auto" alignItems="start" gap={1} className="my-2">
          <Text as="p" font="secondary-body" color="text-03">
            {t("description", { limit, retry, app: appName })}
          </Text>
          <ul className="m-0 list-disc ps-6">
            {blocked.map((skill) => (
              <Text
                key={skill.id}
                as="li"
                font="secondary-body"
                color="text-04"
                wordWrap="wrap-anywhere"
              >
                {skill.name}
              </Text>
            ))}
          </ul>
          {usage && (
            <Text as="p" font="secondary-body" color="text-03">
              {t(usage.unknown_skill_count > 0 ? "usageEstimated" : "usage", {
                size: formatSkillSize(format, usage.charged_bytes),
                maxSize: formatSkillSize(format, usage.max_bytes),
                files: usage.charged_files,
                maxFiles: usage.max_files,
              })}
            </Text>
          )}
          {action}
        </Section>
      }
    />
  );
}
