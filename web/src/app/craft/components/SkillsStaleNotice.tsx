"use client";

import { useState } from "react";
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
        error instanceof Error
          ? error.message
          : "Failed to reload session skills"
      );
    } finally {
      setReloading(false);
    }
  };

  return (
    <MessageCard
      variant="warning"
      title="Your skills have changed"
      description="Reload this session to update skills."
      rightChildren={
        <Button
          icon={SvgRefreshCw}
          onClick={reload}
          disabled={turnActive || reloading}
          tooltip={
            turnActive ? "Wait for the current turn to finish." : undefined
          }
        >
          {reloading ? "Reloading…" : "Reload skills"}
        </Button>
      }
    />
  );
}
