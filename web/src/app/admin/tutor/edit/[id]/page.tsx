"use client";

import { use, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAgent } from "@/hooks/useAgents";
import TutorEditorPage from "@/refresh-pages/admin/TutorPage/TutorEditorPage";

export interface PageProps {
  params: Promise<{ id: string }>;
}

export default function Page(props: PageProps) {
  const router = useRouter();
  const { id } = use(props.params);
  const agentId = parseInt(id);

  const { agent, isLoading, refresh } = useAgent(
    isNaN(agentId) ? null : agentId
  );

  useEffect(() => {
    if (isNaN(agentId)) {
      router.push("/admin/tutor");
    }
  }, [agentId, router]);

  useEffect(() => {
    if (!isLoading && !agent) {
      router.push("/admin/tutor");
    }
  }, [isLoading, agent, router]);

  if (isLoading || !agent) return null;

  return <TutorEditorPage tutor={agent} refreshTutor={refresh} />;
}
