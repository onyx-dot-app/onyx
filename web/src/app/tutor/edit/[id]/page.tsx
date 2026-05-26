"use client";

import { use, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { useAgent } from "@/hooks/useAgents";
import TutorEditorPage from "@/refresh-pages/admin/TutorPage/TutorEditorPage";

export interface PageProps {
  params: Promise<{ id: string }>;
}

export default function Page(props: PageProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { id } = use(props.params);
  const agentId = parseInt(id);
  const fallbackUrl = searchParams?.toString()
    ? `/tutor?${searchParams.toString()}`
    : "/tutor";

  const { agent, isLoading, refresh } = useAgent(
    isNaN(agentId) ? null : agentId
  );

  useEffect(() => {
    if (isNaN(agentId)) {
      router.push(fallbackUrl as Route);
    }
  }, [agentId, fallbackUrl, router]);

  useEffect(() => {
    if (!isLoading && !agent) {
      router.push(fallbackUrl as Route);
    }
  }, [isLoading, agent, fallbackUrl, router]);

  if (isLoading || !agent) return null;

  return <TutorEditorPage tutor={agent} refreshTutor={refresh} />;
}
