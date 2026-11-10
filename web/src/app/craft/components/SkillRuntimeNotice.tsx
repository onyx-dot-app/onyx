"use client";

import { useEffect } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { Section, toast } from "@opal/layouts";
import { useNavigation } from "@opal/navigation";
import { formatSkillSize } from "@/lib/skills/limits";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import type { ApiSkillRuntimeOmission } from "@/app/craft/types/streamingTypes";

export const SKILL_RUNTIME_NOTICE_TOAST_ID = "craft-skill-runtime-notice";

interface SkillRuntimeNoticeProps {
  sessionId: string;
}

/**
 * Raises one error toast when the session's sandbox left Skills out for the
 * runtime limit. Dismissing it holds until the omission state changes.
 */
export default function SkillRuntimeNotice({
  sessionId,
}: SkillRuntimeNoticeProps) {
  const t = useTranslations("craft.skillRuntimeNotice");
  const format = useFormatter();
  const navigation = useNavigation();
  const notice = useBuildSessionStore(
    (state) => state.sessions.get(sessionId)?.skillRuntimeNotice ?? null
  );
  const dismissed = useBuildSessionStore(
    (state) =>
      state.sessions.get(sessionId)?.skillRuntimeNoticeDismissed ?? false
  );
  const updateSessionData = useBuildSessionStore(
    (state) => state.updateSessionData
  );

  const skillsStale = useBuildSessionStore(
    (state) => state.sessions.get(sessionId)?.skillsStale ?? false
  );

  useEffect(() => {
    if (!notice?.omissions.length || dismissed || skillsStale) return;
    const formatSize = (bytes: number): string =>
      formatSkillSize(format, bytes);
    const title = t("toast.title", { count: notice.omissions.length });
    const description = t("toast.description", {
      maxSize: formatSize(notice.max_bytes),
      maxFiles: notice.max_files,
    });
    const omissionLabel = (omission: ApiSkillRuntimeOmission): string => {
      const values = {
        name: omission.name,
        size: formatSize(omission.charged_bytes),
      };
      switch (omission.failed_limit) {
        case "bytes":
          return t("item.bytesLabel", values);
        case "files":
          return t("item.filesLabel", {
            ...values,
            files: omission.file_count,
          });
        case "directories":
          return t("item.directoriesLabel", {
            ...values,
            limit: notice.max_directories,
          });
        case "paths":
          return t("item.pathsLabel", {
            ...values,
            limit: notice.max_path_bytes,
            componentLimit: notice.max_path_component_bytes,
          });
      }
    };

    toast.error(title, {
      id: SKILL_RUNTIME_NOTICE_TOAST_ID,
      duration: Infinity,
      dismissible: false,
      children: (
        <Section alignItems="stretch" gap={2} padding={3}>
          <span role="alert" className="sr-only">
            <Text>{title}</Text>
            <Text>{description}</Text>
          </span>
          <section
            aria-label={t("list.label")}
            // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Focus lets keyboard users scroll the description and list.
            tabIndex={0}
            className="max-h-[min(20rem,25dvh)] overflow-y-auto"
          >
            <Text as="p" font="secondary-body" color="text-03">
              {description}
            </Text>
            <ul>
              {notice.omissions.map((omission) => (
                <Text
                  key={omission.skill_id}
                  as="li"
                  font="secondary-body"
                  color="text-03"
                  wordWrap="wrap-anywhere"
                >
                  {omissionLabel(omission)}
                </Text>
              ))}
            </ul>
          </section>
          <Section flexDirection="row" justifyContent="end" gap={1} wrap>
            <Button
              prominence="tertiary"
              size="md"
              onClick={() =>
                updateSessionData(sessionId, {
                  skillRuntimeNoticeDismissed: true,
                })
              }
            >
              {t("dismiss.button")}
            </Button>
            <Button
              prominence="secondary"
              size="md"
              {...navigation.linkTo("/craft/v1/skills")}
            >
              {t("manage.button")}
            </Button>
          </Section>
        </Section>
      ),
    });
    return () => toast.dismiss(SKILL_RUNTIME_NOTICE_TOAST_ID);
  }, [
    notice,
    dismissed,
    skillsStale,
    sessionId,
    updateSessionData,
    t,
    format,
    navigation,
  ]);

  return null;
}
