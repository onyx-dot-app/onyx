"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { Section, toast } from "@opal/layouts";
import { useNavigation } from "@opal/navigation";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { CRAFT_SKILLS_PATH } from "@/app/craft/v1/constants";
import { useSkillLimitCopy, type SkillLimitNotice } from "@/lib/skills/limits";
import SkillOmissionList from "@/sections/skills/SkillOmissionList";

export const SKILL_RUNTIME_NOTICE_TOAST_ID = "craft-skill-runtime-notice";

/** Identifies one omission set, so a poll with the same set raises no new toast. */
export function skillOmissionsKey(notice: SkillLimitNotice): string {
  return notice.skills
    .map((skill) => `${skill.plugin_id}:${skill.bytes}:${skill.files}`)
    .sort()
    .join(",");
}

interface SkillRuntimeNoticeContentProps {
  sessionId: string;
  notice: SkillLimitNotice;
  noticeKey: string;
}

function SkillRuntimeNoticeContent({
  sessionId,
  notice,
  noticeKey,
}: SkillRuntimeNoticeContentProps) {
  const t = useTranslations("craft.skillRuntimeNotice");
  const { formatSize } = useSkillLimitCopy();
  const navigation = useNavigation();
  const updateSessionData = useBuildSessionStore(
    (state) => state.updateSessionData
  );
  return (
    <SkillOmissionList
      label={t("listLabel")}
      description={t("description", {
        maxSize: formatSize(notice.max_bytes),
        maxFiles: notice.max_files,
      })}
      skills={notice.skills}
    >
      <Section flexDirection="row" justifyContent="end" gap={0.5} wrap>
        <Button
          prominence="tertiary"
          onClick={() =>
            updateSessionData(sessionId, {
              skillOmissionsDismissedKey: noticeKey,
            })
          }
        >
          {t("dismiss")}
        </Button>
        <Button
          prominence="secondary"
          {...navigation.linkTo(CRAFT_SKILLS_PATH)}
        >
          {t("manage")}
        </Button>
      </Section>
    </SkillOmissionList>
  );
}

interface SkillRuntimeNoticeProps {
  sessionId: string;
}

/**
 * Raises one error toast when the run-time skill limit left skills out of the
 * session's sandbox. It waits while the session's skills are stale, and stays
 * dismissed until the omission set changes.
 */
export default function SkillRuntimeNotice({
  sessionId,
}: SkillRuntimeNoticeProps) {
  const t = useTranslations("craft.skillRuntimeNotice");
  const noticeKey = useBuildSessionStore((state) => {
    const notice = state.sessions.get(sessionId)?.skillOmissions;
    return notice?.skills.length ? skillOmissionsKey(notice) : null;
  });
  const dismissedKey = useBuildSessionStore(
    (state) => state.sessions.get(sessionId)?.skillOmissionsDismissedKey ?? null
  );
  const skillsStale = useBuildSessionStore(
    (state) => state.sessions.get(sessionId)?.skillsStale ?? false
  );

  useEffect(() => {
    if (noticeKey === null || skillsStale || noticeKey === dismissedKey) return;
    const notice = useBuildSessionStore
      .getState()
      .sessions.get(sessionId)?.skillOmissions;
    if (!notice) return;
    toast.error(t("title", { count: notice.skills.length }), {
      id: SKILL_RUNTIME_NOTICE_TOAST_ID,
      duration: Infinity,
      dismissible: false,
      content: (
        <SkillRuntimeNoticeContent
          sessionId={sessionId}
          notice={notice}
          noticeKey={noticeKey}
        />
      ),
    });
    return () => toast.dismiss(SKILL_RUNTIME_NOTICE_TOAST_ID);
  }, [noticeKey, dismissedKey, skillsStale, sessionId, t]);

  return null;
}
