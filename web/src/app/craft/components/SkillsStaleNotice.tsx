"use client";

import { useState } from "react";
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
  const reload = async () => {
    setReloading(true);
    try {
      const state = await reloadSessionSkills(sessionId);
      updateSessionData(sessionId, { skillsStale: state.skills_stale });
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("toast.reloadFailed")
      );
    } finally {
      setReloading(false);
    }
  };

  if (turnActive) return null;

  return (
    <MessageCard
      variant="warning"
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
