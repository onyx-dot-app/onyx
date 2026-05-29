"use client";

import { useMemo } from "react";
import { Text } from "@opal/components";
import { cn } from "@opal/utils";
import { useSubagents } from "@/app/craft/hooks/useBuildSessionStore";
import AgentPill from "@/app/craft/components/AgentPill";

export default function AgentStrip() {
  const subagents = useSubagents();

  const sorted = useMemo(() => {
    return Array.from(subagents.values()).sort((a, b) => {
      const aRunning = a.status === "running";
      const bRunning = b.status === "running";
      if (aRunning !== bRunning) return aRunning ? -1 : 1;
      return b.startedAt - a.startedAt;
    });
  }, [subagents]);

  if (sorted.length === 0) return null;

  return (
    <div
      role="region"
      aria-label="Agents"
      className={cn("flex flex-col gap-1.5 pb-2")}
    >
      <Text font="figure-small-label" color="text-02">
        Agents
      </Text>
      <div className="flex flex-wrap gap-1.5">
        {sorted.map((s) => (
          <AgentPill key={s.sessionId} subagent={s} />
        ))}
      </div>
    </div>
  );
}
