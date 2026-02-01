"use client";

import { use, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAgent } from "@/hooks/useAgents";
import AgentEditorPage from "@/refresh-pages/AgentEditorPage";
import * as AppLayouts from "@/layouts/app-layouts";

export interface PageProps {
  params: Promise<{ id: string }>;
}

export default function Page(props: PageProps) {
  const router = useRouter();
  const { id } = use(props.params);
  const agentId = parseInt(id);

  // Call hook unconditionally (passes null when ID is invalid)
  const { agent, isLoading, refresh } = useAgent(
    isNaN(agentId) ? null : agentId
  );

  // Handle invalid ID (NaN)
  useEffect(() => {
    if (isNaN(agentId)) {
      router.push("/chat");
    }
  }, [agentId, router]);

  // Redirect to home if agent not found after loading completes
  useEffect(() => {
    if (!isLoading && !agent) {
      router.push("/chat");
    }
  }, [isLoading, agent, router]);

  // Show nothing while redirecting or loading
  if (isLoading || !agent) return null;

  return (
    <AppLayouts.Root>
      <AgentEditorPage agent={agent} refreshAgent={refresh} />
    </AppLayouts.Root>
  );
}
