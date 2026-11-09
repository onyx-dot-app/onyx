"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, MessageCard } from "@opal/components";
import { SvgRefreshCw } from "@opal/icons";
import { toast } from "@opal/layouts";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { reloadSessionSkills } from "@/app/craft/services/apiServices";

interface SkillsStaleNoticeProps {
  sessionId: string;
  turnActive: boolean;
}

export default function SkillsStaleNotice({
  sessionId,
  turnActive,
}: SkillsStaleNoticeProps) {
  const t = useTranslations("craft.skillsStale");
  const [reloading, setReloading] = useState(false);
  const updateSessionData = useBuildSessionStore(
    (state) => state.updateSessionData
  );
  const request = useRef(0);
  useEffect(() => {
    setReloading(false);
    return () => {
      request.current += 1;
    };
  }, [sessionId]);
  const reload = async () => {
    const owner = useBuildSessionStore.getState().sessions.get(sessionId);
    if (!owner) return;
    const attempt = ++request.current;
    const revision = owner.skillsStaleRevision + 1;
    updateSessionData(sessionId, {
      skillsStale: owner.skillsStale,
      skillsReloadRevision: revision,
    });
    const isCurrent = () => {
      const current = useBuildSessionStore.getState().sessions.get(sessionId);
      return (
        request.current === attempt &&
        current?.instanceId === owner.instanceId &&
        current.turnGeneration === owner.turnGeneration &&
        current.skillsStaleRevision === revision
      );
    };
    setReloading(true);
    try {
      const state = await reloadSessionSkills(sessionId);
      if (!isCurrent()) return;
      updateSessionData(sessionId, {
        skillsStale: state.skills_stale,
        skillRuntimeNotice: state.skill_runtime_notice,
      });
    } catch (error) {
      if (!isCurrent()) return;
      toast.error(
        error instanceof Error ? error.message : t("toast.reloadFailed")
      );
    } finally {
      const current = useBuildSessionStore.getState().sessions.get(sessionId);
      if (
        current?.instanceId === owner.instanceId &&
        current.skillsReloadRevision === revision
      )
        updateSessionData(sessionId, { skillsReloadRevision: null });
      if (request.current === attempt) setReloading(false);
    }
  };

  if (turnActive) return null;

  return (
    <MessageCard
      variant="info"
      title={t("notice.title")}
      description={t("notice.description")}
      rightChildren={
        <Button icon={SvgRefreshCw} onClick={reload} disabled={reloading}>
          {reloading ? t("reload.inProgress") : t("reload.button")}
        </Button>
      }
    />
  );
}
