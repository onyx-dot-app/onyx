"use client";

import { use, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAgent } from "@/lib/agents/hooks";
import AgentEditorPage from "@/views/AgentEditorPage/page";
import AgentEditorLoading from "@/views/AgentEditorPage/loading";

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
      router.push("/app");
    }
  }, [agentId, router]);

  // Redirect to home if agent not found after loading completes
  useEffect(() => {
    if (!isLoading && !agent) {
      router.push("/app");
    }
  }, [isLoading, agent, router]);

  // The editor's loader while the agent loads or the page redirects.
  if (isLoading || !agent) return <AgentEditorLoading />;

  return <AgentEditorPage agent={agent} refreshAgent={refresh} />;
}
