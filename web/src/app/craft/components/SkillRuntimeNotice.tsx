"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Button, MessageCard } from "@opal/components";
import { Section } from "@opal/layouts";
import { useNavigation } from "@opal/navigation";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { CRAFT_SKILLS_PATH } from "@/app/craft/v1/constants";
import { useFormatBytes } from "@/hooks/useFormatBytes";

interface SkillRuntimeNoticeProps {
  sessionId: string;
}

/** The skills that the run-time limit left out of the session's sandbox. It
 * waits while the session's skills are stale. Key it by session id: a dismiss
 * hides that list of skills for that session's page view. */
export default function SkillRuntimeNotice({
  sessionId,
}: SkillRuntimeNoticeProps) {
  const t = useTranslations("craft.skillRuntimeNotice");
  const format = useFormatter();
  const formatBytes = useFormatBytes();
  const navigation = useNavigation();
  const [dismissedList, setDismissedList] = useState<string | null>(null);
  const notice = useBuildSessionStore(
    (state) => state.sessions.get(sessionId)?.skillOmissions ?? null
  );
  const skillsStale = useBuildSessionStore(
    (state) => state.sessions.get(sessionId)?.skillsStale ?? false
  );
  if (skillsStale || !notice?.skills.length) return null;
  const list = notice.skills.map((skill) => skill.plugin_id).join(",");
  if (dismissedList === list) return null;

  return (
    <div className="pb-2">
      <MessageCard
        variant="warning"
        title={t("title", { count: notice.skills.length })}
        description={t("description", {
          names: format.list(notice.skills.map((skill) => skill.name)),
          maxSize: formatBytes(notice.max_bytes),
          maxFiles: notice.max_files,
        })}
        rightChildren={
          <Section flexDirection="row" width="auto" height="auto" gap={0.5}>
            <Button
              prominence="tertiary"
              onClick={() => setDismissedList(list)}
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
        }
      />
    </div>
  );
}
