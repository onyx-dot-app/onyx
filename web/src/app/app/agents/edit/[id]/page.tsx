"use client";

import { useNavigation } from "@opal/navigation";
import { use, useEffect } from "react";
import { useAgent } from "@/lib/agents/hooks";
import AgentEditorPage from "@/views/AgentEditorPage/page";
import AgentEditorLoading from "@/views/AgentEditorPage/loading";

export interface PageProps {
  params: Promise<{ id: string }>;
}

export default function Page(props: PageProps) {
  const navigation = useNavigation();
  const { id } = use(props.params);
  const agentId = parseInt(id);

  // Call hook unconditionally (passes null when ID is invalid)
  const { agent, isLoading, refresh } = useAgent(
    isNaN(agentId) ? null : agentId
  );

  // Handle invalid ID (NaN)
  useEffect(() => {
    if (isNaN(agentId)) {
      navigation.go("/app");
    }
  }, [agentId, navigation]);

  // Redirect to home if agent not found after loading completes
  useEffect(() => {
    if (!isLoading && !agent) {
      navigation.go("/app");
    }
  }, [isLoading, agent, navigation]);

  // The editor's loader while the agent loads or the page redirects.
  if (isLoading || !agent) return <AgentEditorLoading />;

  return <AgentEditorPage agent={agent} refreshAgent={refresh} />;
}
