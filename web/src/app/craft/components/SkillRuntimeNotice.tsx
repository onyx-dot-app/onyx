"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Button, MessageCard } from "@opal/components";
import { Section } from "@opal/layouts";
import { useNavigation } from "@opal/navigation";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { CRAFT_SKILLS_PATH } from "@/app/craft/v1/constants";
import { useSkillLimitCopy } from "@/lib/skills/limits";

interface SkillRuntimeNoticeProps {
  sessionId: string;
}

/** The skills that the run-time limit left out of the session's sandbox. It
 * waits while the session's skills are stale. Key it by session id: a dismiss
 * lasts for that session's page view. */
export default function SkillRuntimeNotice({
  sessionId,
}: SkillRuntimeNoticeProps) {
  const t = useTranslations("craft.skillRuntimeNotice");
  const format = useFormatter();
  const { formatSize } = useSkillLimitCopy();
  const navigation = useNavigation();
  const [dismissed, setDismissed] = useState(false);
  const notice = useBuildSessionStore(
    (state) => state.sessions.get(sessionId)?.skillOmissions ?? null
  );
  const skillsStale = useBuildSessionStore(
    (state) => state.sessions.get(sessionId)?.skillsStale ?? false
  );
  if (dismissed || skillsStale || !notice?.skills.length) return null;

  return (
    <div className="pb-2">
      <MessageCard
        variant="warning"
        title={t("title", { count: notice.skills.length })}
        description={t("description", {
          names: format.list(notice.skills.map((skill) => skill.name)),
          maxSize: formatSize(notice.max_bytes),
          maxFiles: notice.max_files,
        })}
        rightChildren={
          <Section flexDirection="row" width="auto" height="auto" gap={0.5}>
            <Button prominence="tertiary" onClick={() => setDismissed(true)}>
              {t("dismiss")}
            </Button>
            <Button
              prominence="secondary"
              {...navigation.linkTo(CRAFT_SKILLS_PATH)}
            >
              {t("manage")}
            </Button>
          </Section>
        }
      />
    </div>
  );
}
