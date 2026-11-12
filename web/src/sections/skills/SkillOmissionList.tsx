"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { Section, toast } from "@opal/layouts";
import {
  useSkillLimitCopy,
  type SkillLimitNotice,
  type SkillOmission,
} from "@/lib/skills/limits";

interface SkillOmissionListProps {
  label: string;
  description: string;
  skills: SkillOmission[];
  children?: React.ReactNode;
}

/** The skills a limit left out, each with its size, for a toast's content. */
export default function SkillOmissionList({
  label,
  description,
  skills,
  children,
}: SkillOmissionListProps) {
  const { omissionLabel } = useSkillLimitCopy();
  return (
    <Section alignItems="stretch" gap={0.5} padding={0.5}>
      <section
        aria-label={label}
        // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Focus lets keyboard users scroll the list.
        tabIndex={0}
        className="max-h-[min(20rem,25dvh)] overflow-y-auto"
      >
        <Text as="p" font="secondary-body" color="text-03">
          {description}
        </Text>
        <ul className="list-disc ps-4">
          {skills.map((skill) => (
            <Text
              key={skill.plugin_id}
              as="li"
              font="secondary-body"
              color="text-03"
              wordWrap="wrap-anywhere"
            >
              {omissionLabel(skill)}
            </Text>
          ))}
        </ul>
      </section>
      {children}
    </Section>
  );
}

interface SkillsLeftOffContentProps {
  notice: SkillLimitNotice;
}

function SkillsLeftOffContent({ notice }: SkillsLeftOffContentProps) {
  const t = useTranslations("skills.limit.leftOff");
  const { formatSize } = useSkillLimitCopy();
  return (
    <SkillOmissionList
      label={t("listLabel")}
      description={t("description", { maxSize: formatSize(notice.max_bytes) })}
      skills={notice.skills}
    />
  );
}

/** Shows which app skills a connect left off for the skill limit, and why. */
export function useSkillsLeftOffToast(): (
  notice: SkillLimitNotice | null
) => void {
  const t = useTranslations("skills.limit.leftOff");
  return useCallback(
    (notice: SkillLimitNotice | null) => {
      if (!notice?.skills.length) return;
      toast.warning(t("title", { count: notice.skills.length }), {
        duration: Infinity,
        content: <SkillsLeftOffContent notice={notice} />,
      });
    },
    [t]
  );
}
